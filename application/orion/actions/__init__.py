"""Action plugin API.

    @action("media", op="PlayPause", player="", choices={"op": [...]})
    def media(event, op, player): ...

Keyword args become the action's arguments (defaults shown in the UI). An
action marked `continuous=True` receives every phase of continuous gestures
(begin/update/end) and reads `event.value`; others run once per trigger.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("orion.actions")
ACTIONS: dict[str, "Action"] = {}
CTX: dict = {}  # runtime context for built-ins that need the engine (set by Engine)


@dataclass
class Action:
    name: str
    fn: Callable
    args: dict
    continuous: bool = False
    choices: dict = field(default_factory=dict)
    doc: str = ""
    module: str = ""

    def meta(self) -> dict:
        return {"name": self.name, "args": self.args, "continuous": self.continuous,
                "choices": self.choices, "doc": self.doc, "module": self.module}


def action(name, /, *, continuous=False, choices=None, **args):
    def wrap(fn):
        ACTIONS[name] = Action(name, fn, args, continuous, choices or {},
                               (fn.__doc__ or "").strip(), fn.__module__)
        return fn
    return wrap


# ── Executor: actions run off the tracking thread, in order ──────────────────

class Executor:
    def __init__(self, on_error: Callable = lambda name, err: None):
        self.q: queue.Queue = queue.Queue()
        self.on_error = on_error
        threading.Thread(target=self._loop, name="actions", daemon=True).start()

    def submit(self, act: Action, event, args: dict):
        self.q.put((act, event, {**act.args, **args}))

    def _loop(self):
        while True:
            act, event, args = self.q.get()
            try:
                act.fn(event, **args)
            except Exception as e:  # one broken action must never kill the app
                log.warning("action %s failed: %s", act.name, e)
                self.on_error(act.name, str(e))


def load_builtins():
    from . import audio, browser, hyprland, media, orion, shell, uinput  # noqa: F401
