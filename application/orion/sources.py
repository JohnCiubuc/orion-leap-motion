"""Frame sources: live Leap device, synthetic demo, and recorded replay.

A source calls `on_frame(Frame)` for every tracking frame and `on_image(IRImage)`
for IR frames (only while `ir` is enabled, throttled to `ir_fps`).
"""

from __future__ import annotations

import gzip
import json
import threading
import time
from pathlib import Path

from .frame import IRImage, from_dict, from_leap, to_dict
from .sim import demo_frame, demo_ir


class Source:
    name = "none"

    def __init__(self, on_frame, on_image, ir_fps: float = 30):
        self.on_frame, self.on_image, self.ir_fps = on_frame, on_image, ir_fps
        self.status = {"source": self.name, "connected": False, "device": ""}
        self._ir, self._last_ir, self._stop = False, 0.0, threading.Event()

    @property
    def ir(self) -> bool:
        return self._ir

    @ir.setter
    def ir(self, on: bool):
        self._ir = on

    def _emit_ir(self, make):  # throttle; `make` builds the IRImage only when due
        now = time.monotonic()
        if self._ir and now - self._last_ir >= 1 / self.ir_fps:
            self._last_ir = now
            self.on_image(make())

    def start(self):
        threading.Thread(target=self.run, name=f"source-{self.name}", daemon=True).start()

    def stop(self):
        self._stop.set()

    def run(self):
        raise NotImplementedError

    def restart(self, service=False) -> str:
        raise RuntimeError(f"The {self.name} source has no controller to restart.")


# ── Live device (LeapC service) ───────────────────────────────────────────────

class LeapSource(Source):
    name = "leap"

    def run(self):
        import leap
        from leap.enums import PolicyFlag
        from leapc_cffi import ffi

        src = self

        class Listener(leap.Listener):
            def on_tracking_event(self, e):
                src.on_frame(from_leap(e))

            def on_image_event(self, e):
                def grab():  # copy now: the C buffer is only valid during this callback
                    bufs = []
                    for img in e.image:
                        p = img.c_data.properties
                        ptr = ffi.cast("uint8_t*", img.c_data.data) + img.c_data.offset
                        bufs.append(bytes(ffi.buffer(ptr, p.width * p.height * p.bpp)))
                    return IRImage(p.width, p.height * 2, b"".join(bufs))
                src._emit_ir(grab)

            def on_device_event(self, e):
                src.status.update(connected=True)
                try:
                    with e.device.open():
                        src.status["device"] = e.device.get_info().serial
                except Exception:  # serial is cosmetic
                    pass

            def on_device_lost_event(self, e):
                src.status.update(connected=False, device="")

            def on_connection_lost_event(self, e):
                src.status.update(connected=False)

        self._flag = PolicyFlag.Images
        self._kick = threading.Event()  # set → drop the connection and open a fresh one
        while not self._stop.is_set():  # retry until the tracking service is up
            conn = leap.Connection()
            conn.add_listener(Listener())
            try:
                with conn.open():
                    self._conn = conn
                    conn.set_tracking_mode(leap.TrackingMode.Desktop)
                    if self._ir:  # the UI may have asked for IR before we connected
                        conn.set_policy_flags(flags_to_set=[self._flag])
                    while not (self._stop.is_set() or self._kick.wait(0.5)):
                        pass
                    self._kick.clear()
            except Exception as e:
                self.status.update(connected=False, device="", error=str(e))
                self._stop.wait(3)

    # ── Recovery ("restart controller") ──────────────────────────────────────

    def _unpause(self):
        """Clear a service-side pause (user pause or the service's poor-performance pause)."""
        from leap.enums import PolicyFlag
        from leapc_cffi import libleapc
        self._conn.set_policy_flags(flags_to_set=[PolicyFlag.AllowPauseResume])
        libleapc.LeapSetPause(self._conn.get_connection_ptr()[0], False)

    def restart(self, service=False) -> str:
        """Unpause → USB reset (like replugging) → reconnect. `service` restarts the daemon first."""
        from . import device
        done = []
        if service:
            device.restart_service()
            done.append("restarted the tracking service")
        elif hasattr(self, "_conn"):
            try:
                self._unpause()
                done.append("unpaused tracking")
            except Exception:  # older service, or connection already gone: the reset still helps
                pass
        if not service:
            n = device.usb_reset()
            done.append(f"reset {n} controller{'s' * (n > 1)} over USB")
        self.status.update(connected=False, device="")
        if hasattr(self, "_kick"):
            self._kick.set()
            done.append("reconnected")
        return ", ".join(done).capitalize() + "."

    @Source.ir.setter
    def ir(self, on: bool):
        if on == self._ir or not hasattr(self, "_conn"):
            self._ir = on
            return
        self._ir = on
        kw = {"flags_to_set" if on else "flags_to_clear": [self._flag]}
        # set_policy_flags blocks on a reply from the poll thread → never call it from there
        threading.Thread(target=self._conn.set_policy_flags, kwargs=kw, daemon=True).start()


# ── Demo (no device needed) ───────────────────────────────────────────────────

class DemoSource(Source):
    name = "demo"

    def run(self):
        self.status.update(connected=True, device="DEMO")
        t0 = time.monotonic()
        while not self._stop.wait(1 / 110):
            t = time.monotonic() - t0
            self.on_frame(demo_frame(t))
            self._emit_ir(lambda: IRImage(640, 480, demo_ir(t)))


# ── Replay a recording (gzip JSON lines of Frame dicts) ───────────────────────

class ReplaySource(Source):
    name = "replay"

    def __init__(self, *a, path: Path, loop=True, **kw):
        super().__init__(*a, **kw)
        self.path, self.loop = Path(path), loop

    def run(self):
        self.status.update(connected=True, device=self.path.name)
        frames = [from_dict(json.loads(line)) for line in gzip.open(self.path, "rt")]
        while frames and not self._stop.is_set():
            t0, w0 = frames[0].t, time.monotonic()
            for f in frames:
                if self._stop.wait(max(0.0, (f.t - t0) - (time.monotonic() - w0))):
                    return
                self.on_frame(f)
            if not self.loop:
                break
        self.status["connected"] = False


class Recorder:
    """Streams frames to `<dir>/<timestamp>.orec` while active."""

    def __init__(self, folder: Path):
        self.folder, self._fh, self._lock = Path(folder), None, threading.Lock()

    @property
    def active(self) -> bool:
        return self._fh is not None

    def start(self) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / time.strftime("%Y-%m-%d_%H-%M-%S.orec")
        self._fh = gzip.open(self.path, "wt")
        return self.path

    def write(self, frame):
        with self._lock:
            if self._fh:
                self._fh.write(json.dumps(to_dict(frame)) + "\n")

    def stop(self):
        with self._lock:
            fh, self._fh = self._fh, None
            if fh:
                fh.close()
