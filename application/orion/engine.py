"""The engine: source → gestures → router → actions, plus state for the UI."""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
import threading
import time
import tomllib
from collections import deque

from . import actions, gestures
from .actions import ACTIONS, Executor, hyprland, uinput
from .config import DEFAULT_FILE, PLUGIN_DIR, RECORDINGS_DIR, TEMPLATES_FILE, Config
from .frame import Frame
from .gestures import REGISTRY, GestureEvent
from .gestures.paths import PathGesture
from .handedness import Handedness
from .router import Router
from .sources import DemoSource, LeapSource, Recorder, ReplaySource
from .leap_mp import LeapMediaPipeSource
from .webcam import WebcamSource

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


def _label(mode: str) -> str:
    return mode.replace("_", " ").capitalize()


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
        self.handedness = Handedness(config)
        self.feed = deque(maxlen=50)  # recent gesture events for the UI
        self.source = self.overlay = None
        self._ring = False  # precision ring last signalled to the overlay
        self._menu_open = False  # OrionDo pie shown on the overlay
        self.lock = threading.Lock()
        self.last_frame = self.last_restart = time.monotonic()
        self._restarting = threading.Lock()
        self._follow: dict[str, dict] = {}  # mode → {since, seen}: modes that end when their app closes
        self.build_gestures()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self, replay: str | None = None):
        kind = "demo" if self.demo else self.cfg.general["source"]
        cls = ReplaySource if replay else {"demo": DemoSource, "webcam": WebcamSource, "leap_mp": LeapMediaPipeSource}.get(kind, LeapSource)
        kw = ({"path": replay} if replay else {"cfg": self.cfg["webcam"]} if cls is WebcamSource
              else {"cfg": self.cfg["leap_mp"]} if cls is LeapMediaPipeSource else {})
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
        conf = dict(self.cfg["gestures"])
        if self.cfg.general["source"] == "webcam" and not self.demo and self.cfg["webcam"]["trigger"]:
            conf["oriondo"] = {**conf.get("oriondo", {}), "trigger": self.cfg["webcam"]["trigger"]}  # the webcam sees an open palm best
        with self.lock:
            self.gestures = [cls(conf.get(name)) for name, cls in REGISTRY.items()
                             if conf.get(name, {}).get("enabled", True)]
            for g in self.gestures:
                if g.name == "oriondo":
                    g.allow, g.profile_menu = self._menu_ok, self._profile_menu
        self._menu_close()  # a rebuilt gesture has forgotten its open menu

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
        if self.overlay:
            self.overlay.configure(self.cfg["overlay"])
        self.emit_state()

    # ── Pipeline (runs on the source thread) ──────────────────────────────────

    def on_frame(self, frame: Frame):
        self.last_frame = time.monotonic()
        self.recorder.write(frame)  # raw labels, so replays go through the same filter
        frame = self.handedness(frame)
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
            if ev.name == "oriondo":
                self._oriondo(ev)
        self.emit("frame", frame)
        self._sync_ring()

    def _profile_menu(self):
        """The focused app's own OrionDo config (`[profiles.<name>.oriondo]`), or None."""
        return self.cfg["profiles"].get(self.router.profile, {}).get("oriondo")

    def _menu_ok(self) -> bool:
        """OrionDo may open: it needs the overlay to be seen, and stays out of paused and exclusive-mode use.
        An exclusive profile only has the menu it owns."""
        own_ok = not self.router.profile_exclusive or self._profile_menu() is not None
        return bool(self.overlay and self.overlay.ready) and not self.router.paused and not self.router.exclusive and own_ok

    def _menu_close(self):
        if self._menu_open:
            self._menu_open = False
            if self.overlay:
                self.overlay.menu({"op": "close"})

    def _oriondo(self, ev: GestureEvent):
        """Mirror the menu on the overlay; a fired item runs like any bound action."""
        v = ev.value
        op = ({"op": "open", **v} if ev.phase == "begin" else {"op": ev.phase, **v} if ev.phase in ("enter", "back", "update")
              else {"op": "fire", "index": v["index"]} if ev.phase == "fire" else {"op": "close"})
        self._menu_open = ev.phase != "end"
        if self.overlay:
            self.overlay.menu(op)
        if ev.phase == "fire":
            item = ev.value["item"]
            act = ACTIONS.get(item.get("action", ""))
            if act is None:
                self.emit("error", {"action": item.get("action", ""), "error": "unknown action"})
            elif not self.dry_run:
                self.executor.submit(act, ev, item.get("args", {}))

    def _sync_ring(self):
        on = any(g.precise for g in self.gestures if g.name == "desktop_pointer")
        if on != self._ring:
            self._ring = on
            if self.overlay:
                self.overlay.ring(on)

    def on_window(self, cls: str, title: str):
        if cls == "orion-renewal":  # focusing the panel itself keeps the previous app's profile
            return
        before = self.router.profile
        self.router.window = cls
        if self.router.profile != before:
            self.emit_state()

    # ── Controls (UI, tray, orion.* actions) ──────────────────────────────────

    def set_mode(self, mode: str, on: bool | None = None) -> bool:
        """Switch a mode on/off, running its on_enter/on_exit hooks. An exclusive mode is the only
        mode while it is on: enabling it turns the others off, and others can't be enabled meanwhile."""
        modes, cfg = self.router.modes, self.cfg["modes"]
        on = (mode not in modes) if on is None else on
        if on and mode in modes and mode in cfg:  # asked "on" again (not a toggle): rerun the hooks, e.g. reopen a menu
            if cfg[mode].get("follow_app"):
                self._follow[mode] = {"since": time.monotonic(), "seen": False}
            self._hooks(mode, "on_enter")
            return True
        if on == (mode in modes) or (on and mode not in cfg):
            return False
        if on:
            blocker = next((m for m in modes if cfg.get(m, {}).get("exclusive")), None)
            if blocker:
                self.emit("notice", {"text": f"{_label(blocker)} is exclusive. Turn it off first."})
                return False
            if cfg[mode].get("exclusive"):
                for other in list(modes):
                    self._leave(other)
            modes.add(mode)
            if cfg[mode].get("follow_app"):
                self._follow[mode] = {"since": time.monotonic(), "seen": False}
            self._hooks(mode, "on_enter")
        else:
            self._leave(mode)
        self.emit("notice", {"text": f"{_label(mode)} {'on' if on else 'off'}"})
        with self.lock:  # restart continuous gestures so the new bindings see a fresh "begin"
            for g in self.gestures:
                if g.family == "continuous":
                    g.reset()
        self.emit_state()
        return True

    def _leave(self, mode: str):
        self.router.modes.discard(mode)
        self._follow.pop(mode, None)
        self._hooks(mode, "on_exit")

    def _hooks(self, mode: str, when: str):
        """Run a mode's hook actions (launch an app, a Hyprland dispatch, a global shortcut…)."""
        for hook in self.cfg["modes"].get(mode, {}).get(when, []):
            act = ACTIONS.get(hook.get("action", ""))
            if act is None:
                self.emit("error", {"action": f"{mode} {when}", "error": f"unknown action {hook.get('action')}"})
            elif not self.dry_run:
                self.executor.submit(act, GestureEvent(f"mode.{mode}", "fire", when, None, 0.0), hook.get("args", {}))

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

        self._follow_apps()

    def _follow_apps(self):
        """Modes with follow_app: wait `follow_grace` s for a matching window, then switch the
        mode off once the last one closes (or if it never appeared)."""
        if not self._follow:
            return
        classes = hyprland.window_classes()
        if classes is None:
            return  # can't see windows (not under Hyprland): leave modes alone
        for mode, st in list(self._follow.items()):
            conf = self.cfg["modes"].get(mode, {})
            try:
                rx = re.compile(conf.get("follow_app", ""))
            except re.error:
                continue
            if any(c and rx.search(c) for c in classes):
                st["seen"] = True
            elif st["seen"]:
                self._auto_off(mode, "its app closed")
            elif time.monotonic() - st["since"] > conf.get("follow_grace", 15):
                self._auto_off(mode, "its app didn't open in time")

    def _auto_off(self, mode: str, why: str):
        self.set_mode(mode, False)
        self.emit("notice", {"text": f"{_label(mode)} off: {why}"})

    @property
    def streaming(self) -> bool:
        return time.monotonic() - self.last_frame < 2

    def set_paused(self, paused: bool):
        if paused != self.router.paused:
            self.emit("notice", {"text": "Gestures paused" if paused else "Gestures resumed"})
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
                "armed": self.router.armed, "dry_run": self.dry_run, "time": time.time(),
                "overlay": self.overlay.status if self.overlay else "off", "input": uinput.status}

    def state(self) -> dict:
        return {
            "status": self.status(),
            "config": self.cfg.data,
            "gesture_defaults": tomllib.loads(DEFAULT_FILE.read_text()).get("gestures", {}),
            "gestures": [cls.meta() for cls in REGISTRY.values()],
            "actions": [a.meta() for a in ACTIONS.values()],
            "plugins": self.plugins,
            "recordings": sorted((p.name for p in RECORDINGS_DIR.glob("*.orec")), reverse=True),
            "global_shortcuts": hyprland.global_shortcuts(),
            "feed": list(self.feed),
        }
