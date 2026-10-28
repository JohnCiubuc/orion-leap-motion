"""Runs the gesture overlay (overlay_gtk.py) as a child process and feeds it events.

The overlay uses GTK4 + gtk4-layer-shell under the system Python, kept out of the Qt
process: the two toolkits don't share a process, and an overlay crash never takes Orion down.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .gestures import REGISTRY

log = logging.getLogger("orion.overlay")
SCRIPT = Path(__file__).with_name("overlay_gtk.py")
LIBS = ("/usr/lib/libgtk4-layer-shell.so*", "/usr/lib/*/libgtk4-layer-shell.so*")
QUIET = {"continuous", "oriondo"}  # families that would flood the overlay (pointer, zoom updates …)


def title(name: str) -> str:
    base, _, variant = name.partition(".")
    if base == "path":  # shapes: "Circle", not "Path circle"
        return variant.capitalize()
    return " ".join(w for w in (base.replace("_joy", "").replace("_", " "), variant) if w).capitalize()


class OverlayHost:
    def __init__(self, engine):
        self.engine, self.proc, self.cfg = engine, None, {}
        self.status, self.lock, self.ringing = "off", threading.Lock(), False
        self.menu_t = 0.0  # when the last menu update went out
        engine.listeners.append(self.on_engine)
        engine.overlay = self

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def configure(self, cfg: dict):
        self.cfg = cfg
        if not cfg.get("enabled", True):
            self.stop()
            self.status = "off"
            return
        if self.proc is None or self.proc.poll() is not None:
            self.start()
        self.send({"type": "config", **{k: cfg[k] for k in ("opacity", "seconds", "corner", "margin", "precision_ring") if k in cfg}})
        if self.ringing:  # a setting flip while the ring is up hides or restores it
            self.send({"type": "ring", "on": bool(cfg.get("precision_ring", True))})

    def start(self):
        if not os.environ.get("WAYLAND_DISPLAY"):
            self.status = "unavailable: not a Wayland session"
            return
        lib = next((p for pat in LIBS for p in sorted(glob.glob(pat))), None)
        python = os.environ.get("ORION_OVERLAY_PYTHON") or shutil.which("python3", path="/usr/bin:/bin")
        probe = 'import gi; gi.require_version("Gtk4LayerShell", "1.0"); from gi.repository import Gtk4LayerShell'
        if not lib or not python or subprocess.run([python, "-c", probe], capture_output=True, timeout=10).returncode:
            self.status = "unavailable: sudo pacman -S gtk4-layer-shell python-gobject"
            return
        env = {**os.environ, "LD_PRELOAD": lib, "GDK_BACKEND": "wayland"}  # layer-shell must load before libwayland
        self.proc = subprocess.Popen([python, str(SCRIPT)], stdin=subprocess.PIPE, env=env, start_new_session=True)
        self.status = "on"
        threading.Thread(target=self._watch, args=(self.proc,), daemon=True).start()

    def _watch(self, proc):
        code = proc.wait()
        if proc is self.proc and code not in (0, -15):
            self.status = f"stopped (exit {code}); check gtk4-layer-shell"
            log.warning("overlay exited with %s", code)

    def stop(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self.proc.stdin.close()  # EOF → overlay quits
            self.proc = None

    def send(self, msg: dict):
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                return
            try:
                self.proc.stdin.write((json.dumps(msg) + "\n").encode())
                self.proc.stdin.flush()
            except (BrokenPipeError, ValueError):
                self.proc = None

    def ring(self, on: bool):
        self.ringing = on
        if self.cfg.get("precision_ring", True):
            self.send({"type": "ring", "on": on})

    @property
    def ready(self) -> bool:
        proc = self.proc  # send() may clear it from another thread
        return proc is not None and proc.poll() is None and self.cfg.get("enabled", True)

    def menu(self, msg: dict):
        """OrionDo pie: marker updates are thinned to ~60 Hz (tracking is faster); everything else goes through."""
        if msg["op"] == "update":
            now = time.monotonic()
            if now - self.menu_t < 0.016:
                return
            self.menu_t = now
        self.send({"type": "menu", **msg})

    # ── Engine events → cards ─────────────────────────────────────────────────

    def show(self, title_: str, detail="", hand=None, key=None):
        self.send({"type": "show", "title": title_, "detail": detail, "hand": hand, "key": key})

    def on_engine(self, kind, payload):
        if not self.proc or not self.cfg.get("enabled", True):
            return
        if kind == "notice" and payload and payload.get("overlay", True):
            self.show(payload["text"])
        elif kind == "event" and payload["phase"] in ("begin", "fire"):
            g = REGISTRY.get(payload["name"].split(".")[0])
            if g is None or g.family in QUIET or (g.family == "joystick" and payload["phase"] == "begin"):
                return
            acts = payload["actions"]
            if not acts and not self.cfg.get("show_unbound", False):
                return
            prof = payload.get("profile", "default")
            detail = ", ".join(acts) + (f" in {prof}" if acts and prof != "default" else "") if acts else "No binding"
            if acts and self.engine.dry_run:
                detail = "Would run " + detail
            self.show(title(payload["name"]), detail, payload.get("hand"), key=f"{payload['name']}:{payload.get('hand')}")
