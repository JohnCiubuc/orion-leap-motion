"""Hyprland IPC: run dispatchers, and watch the focused window (drives per-app profiles)."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path
from typing import Callable

from . import action


def _sock(name: str) -> str:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        raise RuntimeError("not running under Hyprland")
    return str(Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "hypr" / sig / name)


def hyprctl(request: str) -> str:
    """One request on the command socket, e.g. "dispatch workspace e+1" or "j/activewindow"."""
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(_sock(".socket.sock"))
        s.sendall(request.encode())
        return b"".join(iter(lambda: s.recv(65536), b"")).decode()


# ── Dispatch: classic syntax ("workspace e+1") or Lua ("hl.dsp.focus({ workspace = "e+1" })") ──
# Hyprland with a Lua config (`configProvider: lua` in systeminfo) evaluates IPC dispatches as
# Lua, so classic commands are translated for it. Lua written as `hl.…` is always sent as-is.

_lua: bool | None = None  # None = not detected yet


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _fullscreen(arg):  # classic: 0 = fullscreen, 1 = maximise
    return f'hl.dsp.window.fullscreen({{ mode = "{"maximized" if arg.strip() == "1" else "fullscreen"}" }})'


CLASSIC = {  # classic dispatcher → Lua builder(arg)
    "workspace": lambda a: f"hl.dsp.focus({{ workspace = {_q(a)} }})",
    "movetoworkspace": lambda a: f"hl.dsp.window.move({{ workspace = {_q(a)}, follow = true }})",
    "movetoworkspacesilent": lambda a: f"hl.dsp.window.move({{ workspace = {_q(a)}, follow = false }})",
    "focusmonitor": lambda a: f"hl.dsp.focus({{ monitor = {_q(a)} }})",
    "movefocus": lambda a: f"hl.dsp.focus({{ direction = {_q(a)} }})",
    "movewindow": lambda a: f"hl.dsp.window.move({{ direction = {_q(a)} }})",
    "togglefloating": lambda a: 'hl.dsp.window.float({ action = "toggle" })',
    "fullscreen": _fullscreen,
    "killactive": lambda a: "hl.dsp.window.close()",
    "pin": lambda a: "hl.dsp.window.pin()",
    "pseudo": lambda a: "hl.dsp.window.pseudo()",
    "centerwindow": lambda a: "hl.dsp.window.center()",
    "cyclenext": lambda a: "hl.dsp.window.cycle_next()",
    "togglespecialworkspace": lambda a: f"hl.dsp.workspace.toggle_special({_q(a.removeprefix('special:')) if a else ''})",
    "togglegroup": lambda a: "hl.dsp.group.toggle()",
    "exec": lambda a: f"hl.dsp.exec_cmd({_q(a)})",
    "submap": lambda a: f"hl.dsp.submap({_q(a)})",
    "global": lambda a: f"hl.dsp.global({_q(a)})",
}


def to_lua(cmd: str) -> str:
    """Translate a classic dispatcher line to Hyprland's Lua dispatcher form."""
    cmd = cmd.strip()
    if cmd.startswith("hl."):
        return cmd
    name, _, arg = cmd.partition(" ")
    if name not in CLASSIC:
        raise RuntimeError(f'No Lua translation for "{name}". Write it as Lua, e.g. hl.dsp.focus({{ workspace = "1" }}) '
                           "(see wiki.hypr.land → Dispatchers)")
    return CLASSIC[name](arg.strip())


def lua_config() -> bool:
    global _lua
    if _lua is None:
        _lua = "configprovider: lua" in hyprctl("systeminfo").lower()
    return _lua


@action("hypr.dispatch", cmd="workspace e+1")
def dispatch(ev, cmd):
    """Run a Hyprland dispatcher. Classic syntax ("workspace e+1", "togglefloating", "fullscreen 1",
    "exec kitty") is translated automatically for Lua configs; Lua (hl.dsp.…) is sent as-is."""
    global _lua
    line = to_lua(cmd) if cmd.strip().startswith("hl.") or lua_config() else cmd
    out = hyprctl(f"dispatch {line}").strip()
    if "hl.dispatch" in out and line == cmd:  # mode changed under us (config switched to Lua): retry once
        _lua = True
        out = hyprctl(f"dispatch {to_lua(cmd)}").strip()
    if out not in ("ok", ""):
        raise RuntimeError(out)


@action("hypr.global", shortcut="kando:example-menu")
def global_shortcut(ev, shortcut):
    """Trigger a global shortcut an app registered through the desktop portal ("appid:name"),
    e.g. kando:example-menu. Same as the `global` dispatcher in a Hyprland bind."""
    dispatch(ev, f"global {shortcut}")


def global_shortcuts() -> list[dict]:
    """Shortcuts apps have registered (hyprctl globalshortcuts): [{"name", "description"}]."""
    try:
        data = json.loads(hyprctl("j/globalshortcuts") or "[]")
        return [{"name": d.get("name", ""), "description": d.get("description", "")} for d in data]
    except Exception:
        return []


def window_classes() -> set[str] | None:
    """Classes (and initial classes) of all open windows; None when Hyprland can't be asked."""
    try:
        return {c.get(k, "") for c in json.loads(hyprctl("j/clients") or "[]") for k in ("class", "initialClass")}
    except Exception:
        return None


def watch_active_window(callback: Callable[[str, str], None]):
    """Call callback(window_class, title) on every focus change. Reconnects forever."""
    def run():
        try:
            w = json.loads(hyprctl("j/activewindow") or "{}")
            callback(w.get("class", ""), w.get("title", ""))
        except Exception:
            pass
        while True:
            try:
                with socket.socket(socket.AF_UNIX) as s:
                    s.connect(_sock(".socket2.sock"))
                    for line in s.makefile(encoding="utf-8", errors="replace"):
                        if line.startswith("activewindow>>"):
                            cls, _, title = line[14:].rstrip("\n").partition(",")
                            callback(cls, title)
            except Exception:
                time.sleep(3)  # not under Hyprland, or compositor restarting

    threading.Thread(target=run, name="hypr-events", daemon=True).start()
