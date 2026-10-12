"""Browser control via keyboard shortcuts (Zen / Firefox defaults; work in Chromium too)."""

from __future__ import annotations

import math

from . import action
from .uinput import tap_keys

OPS = {
    "next_tab": "ctrl+tab", "prev_tab": "ctrl+shift+tab", "new_tab": "ctrl+t",
    "close_tab": "ctrl+w", "reopen_tab": "ctrl+shift+t", "back": "alt+left",
    "forward": "alt+right", "reload": "f5", "zoom_in": "ctrl+equal", "zoom_out": "ctrl+minus",
    "zoom_reset": "ctrl+0", "top": "home", "bottom": "end", "page_down": "pagedown",
    "page_up": "pageup", "find": "ctrl+f", "fullscreen": "f11",
    "zen_compact": "ctrl+alt+c",  # Zen-specific (compact mode)
}
_zoom = {"steps": 0}


@action("browser", op="next_tab", choices={"op": list(OPS)})
def browser(ev, op):
    """Common browser commands (tabs, history, zoom, scrolling)."""
    tap_keys(OPS[op])


@action("browser.zoom", continuous=True, per_step=0.15)
def zoom(ev, per_step):
    """Page zoom for continuous gestures (e.g. two-hand zoom): one zoom step per `per_step` scale change."""
    if ev.phase == "begin":
        _zoom["steps"] = 0
    elif ev.phase == "update" and ev.value:
        target = round(math.log(ev.value) / math.log1p(per_step))
        while _zoom["steps"] != target:
            up = target > _zoom["steps"]
            tap_keys(OPS["zoom_in" if up else "zoom_out"])
            _zoom["steps"] += 1 if up else -1
