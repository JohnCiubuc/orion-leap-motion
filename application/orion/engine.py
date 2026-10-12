"""The engine: source → gestures → router → actions, plus state for the UI."""

from __future__ import annotations

import importlib.util
import logging
import sys
import threading
import time
from collections import deque

from . import actions, gestures
from .actions import ACTIONS, Executor
from .config import PLUGIN_DIR, RECORDINGS_DIR, TEMPLATES_FILE, Config
from .frame import Frame
from .gestures import REGISTRY, GestureEvent
from .gestures.paths import PathGesture
from .router import Router
from .sources import DemoSource, LeapSource, Recorder, ReplaySource

log = logging.getLogger("orion")


# ── Plugin discovery ──────────────────────────────────────────────────────────

def load_plugins() -> list[dict]:
    """Built-ins, then every ~/.config/orion-renewal/plugins/*.py (each may register gestures/actions)."""
    gestures.load_builtins()
    actions.load_builtins()
    found = []
    for path in sorted(PLUGIN_DIR.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"orion_plugin_{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            found.append({"file": str(path), "ok": True, "error": ""})
        except Exception as e:
            log.error("plugin %s failed: %s", path.name, e)
            found.append({"file": str(path), "ok": False, "error": str(e)})
    PathGesture.load_user(TEMPLATES_FILE)
    return found


class Engine:
    def __init__(self, config: Config, demo=False, dry_run=None):
        self.cfg, self.demo = config, demo
        self.dry_run = demo if dry_run is None else dry_run  # demo: show what would fire, do nothing
        self.plugins = load_plugins()
        actions.CTX["engine"] = self
        self.listeners = []  # UI hooks: fn(kind, payload); kind ∈ frame|image|event|state
        self.executor = Executor(on_error=lambda a, e: self.emit("error", {"action": a, "error": e}))
        self.router = Router(config, lambda *a: None if self.dry_run else self.executor.submit(*a))
        self.recorder = Recorder(RECORDINGS_DIR)
        self.feed = deque(maxlen=50)  # recent gesture events for the UI
        self.source = None
        self.lock = threading.Lock()
        self.last_frame = self.last_restart = time.monotonic()
        self._restarting = threading.Lock()
        self.build_gestures()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self, replay: str | None = None):
        kind = "demo" if self.demo else self.cfg.general["source"]
        cls = ReplaySource if replay else {"demo": DemoSource}.get(kind, LeapSource)
        kw = {"path": replay} if replay else {}
        self.source = cls(self.on_frame, lambda img: self.emit("image", img),
                          ir_fps=self.cfg.general["ir_fps"], **kw)
        self.source.start()
        if not getattr(self, "_watching", False):
            from .actions.hyprland import watch_active_window
            watch_active_window(self.on_window)
            self._watching = True

    def replay(self, path: str | None):
        """Switch to replaying a recording (or back to the live source with None)."""
        ir = self.source.ir if self.source else False
        if self.source:
            self.source.stop()
        self.start(replay=path)
        self.source.ir = ir
        self.emit_state()

    def build_gestures(self):
        conf = self.cfg["gestures"]
        with self.lock:
            self.gestures = [cls(conf.get(name)) for name, cls in REGISTRY.items()
                             if conf.get(name, {}).get("enabled", True)]

    def reload_config(self, data: dict | None = None):
        """Apply a config (from the UI) or re-read the file (hand edit)."""
        if data is not None:
            self.cfg.save(data)
        else:
            self.cfg.load()
        self.router.configure(self.cfg)
        self.build_gestures()
        if self.source:
            self.source.ir_fps = self.cfg.general["ir_fps"]
        self.emit_state()

    # ── Pipeline (runs on the source thread) ──────────────────────────────────

    def on_frame(self, frame: Frame):
        self.last_frame = time.monotonic()
        self.recorder.write(frame)
        with self.lock:
            events = [e for g in self.gestures for e in g.update(frame)]
        for ev in events:
            fired = self.router.route(ev)
            if ev.phase != "update":
                entry = {**ev.as_dict(), "actions": fired, "profile": self.router.profile}
                self.feed.append(entry)
                self.emit("event", entry)
                if ev.name == "path.recorded":
                    self.emit_state()
        self.emit("frame", frame)

    def on_window(self, cls: str, title: str):
        if cls == "orion-renewal":  # focusing the panel itself keeps the previous app's profile
            return
        before = self.router.profile
        self.router.window = cls
        if self.router.profile != before:
            self.emit_state()

    # ── Controls (UI, tray, orion.* actions) ──────────────────────────────────

    def set_mode(self, mode: str, on: bool | None = None):
        on = (mode not in self.router.modes) if on is None else on
        (self.router.modes.add if on else self.router.modes.discard)(mode)
        with self.lock:  # restart continuous gestures so the new bindings see a fresh "begin"
            for g in self.gestures:
                if g.family == "continuous":
                    g.reset()
        self.emit_state()

    def restart_device(self, service=False, reason=""):
        """Wake a sleeping controller (see device.py). Runs in the background; reports via notices."""
        def run():
            if not self._restarting.acquire(blocking=False):
                return  # one restart at a time
            try:
                self.last_restart = time.monotonic()
                self.emit("notice", {"text": f"Restarting the controller{reason}…"})
                self.emit("notice", {"text": self.source.restart(service=service), "ok": True})
                self.last_frame = time.monotonic()  # give it time to come back before calling it asleep
            except Exception as e:
                self.emit("notice", None)
                self.emit("error", {"action": "Restart controller", "error": str(e)})
            finally:
                self._restarting.release()
        threading.Thread(target=run, name="restart-device", daemon=True).start()

    def watchdog(self):
        """Called once a second: auto-wake when a connected controller stops streaming."""
        idle, limit = time.monotonic() - self.last_frame, self.cfg.general.get("auto_wake", 0)
        if (limit and isinstance(self.source, LeapSource) and self.source.status.get("connected")
                and idle > limit and time.monotonic() - self.last_restart > 60):
            self.restart_device(reason=f" (no frames for {int(idle)} s)")

    @property
    def streaming(self) -> bool:
        return time.monotonic() - self.last_frame < 2

    def set_paused(self, paused: bool):
        self.router.paused = paused
        self.emit_state()

    def capture_path(self, name: str):
        with self.lock:
            for g in self.gestures:
                if isinstance(g, PathGesture):
                    g.capture = name
        self.emit_state()

    def set_recording(self, on: bool) -> str:
        path = str(self.recorder.start()) if on and not self.recorder.active else ""
        if not on:
            self.recorder.stop()
        self.emit_state()
        return path

    # ── UI plumbing ───────────────────────────────────────────────────────────

    def emit(self, kind: str, payload):
        for fn in self.listeners:
            fn(kind, payload)

    def emit_state(self):
        self.emit("state", self.state())

    def status(self) -> dict:
        capture = next((g.capture for g in self.gestures if isinstance(g, PathGesture)), None)
        return {**(self.source.status if self.source else {}), "streaming": self.streaming, "paused": self.router.paused,
                "profile": self.router.profile, "window": self.router.window,
                "modes": sorted(self.router.modes), "recording": self.recorder.active,
                "capture": capture, "engage_required": self.router.engage_required,
                "armed": self.router.armed, "dry_run": self.dry_run, "time": time.time()}

    def state(self) -> dict:
        return {
            "status": self.status(),
            "config": self.cfg.data,
            "gestures": [cls.meta() for cls in REGISTRY.values()],
            "actions": [a.meta() for a in ACTIONS.values()],
            "plugins": self.plugins,
            "recordings": sorted((p.name for p in RECORDINGS_DIR.glob("*.orec")), reverse=True),
            "feed": list(self.feed),
        }
