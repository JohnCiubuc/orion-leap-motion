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


@action("hypr.dispatch", cmd="workspace e+1")
def dispatch(ev, cmd):
    """Run any Hyprland dispatcher: "workspace e+1", "togglefloating", "fullscreen 1", "exec kitty" …"""
    out = hyprctl(f"dispatch {cmd}")
    if out.strip() not in ("ok", ""):
        raise RuntimeError(out.strip())


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
