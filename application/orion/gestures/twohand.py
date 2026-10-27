"""Continuous gestures: values streamed while a condition holds."""

import math

import numpy as np

from . import Continuous, continuous, register
from .fingers import FingerMotion
from .precision import PrecisionLock


def _pinch_point(h):
    return (h["thumb"].tip + h["index"].tip) / 2


@continuous("zoom", hands=2, mode="ratio", pinch=(0.7, 0.3, 1.0))
def zoom(l, r, p):
    """Both hands pinching, pulled apart / pushed together. Value: scale (1.0 = start)."""
    if l.pinch > p["pinch"] and r.pinch > p["pinch"]:
        return float(np.linalg.norm(_pinch_point(r) - _pinch_point(l)))
    return None


@continuous("rotate", hands=2, mode="delta", pinch=(0.7, 0.3, 1.0))
def rotate(l, r, p):
    """Both hands pinching, turned like a steering wheel. Value: degrees from start (+ = clockwise)."""
    if l.pinch > p["pinch"] and r.pinch > p["pinch"]:
        d = _pinch_point(r) - _pinch_point(l)
        return -math.degrees(math.atan2(d[1], d[0]))
    return None


# ── Air-mouse pointer: which point of the hand steers the cursor ──────────────

def _stable(h):  # the service's stabilised palm, if it fills it in (it can be all zeros)
    return h.stable if np.any(h.stable) else h.palm


TRACK = {
    "palm": lambda h: h.palm,  # raw palm + Orion's filter: steady, ignores finger taps
    "palm_stable": _stable,  # the tracking service's own smoothing (adds lag)
    "knuckles": lambda h: (h["index"].joints[1] + h["middle"].joints[1]) / 2,  # steady, quicker than palm
    "index": lambda h: h["index"].tip,
    "middle": lambda h: h["middle"].tip,
    "pinch": _pinch_point,
}


class OneEuro:
    """One Euro filter: heavy smoothing when still (no jitter), light when moving fast (no lag)."""

    def __init__(self, min_cutoff, beta, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = self.dx = self.t = None

    def __call__(self, x, t):
        if self.t is None:
            self.x, self.dx, self.t = x, np.zeros_like(x), t
            return x
        dt = max(t - self.t, 1e-3)
        alpha = lambda fc: 1 / (1 + 1 / (2 * math.pi * fc * dt))  # noqa: E731
        self.dx = self.dx + alpha(self.d_cutoff) * ((x - self.x) / dt - self.dx)
        self.x = self.x + alpha(self.min_cutoff + self.beta * float(np.linalg.norm(self.dx))) * (x - self.x)
        self.t = t
        return self.x


@register
class Pointer(Continuous):
    """Hand position while the hand is open-ish. Value: (dx, dy) mm since last frame — drives air mouse.
    `track` picks the point that steers; palm or knuckles stay put while you tap or pinch.
    `steady` lowers jitter when still (lower = steadier), `responsive` cuts lag when moving.
    When a finger moves `tap_trigger` mm against the palm while the palm was resting (slower than
    `tap_still` mm/s), the cursor follows the hand over `tap_damp` seconds instead of at once, so a tap's
    palm wobble doesn't move it. It never applies to a hand that is already moving."""
    name, mode = "pointer", "step"
    doc = __doc__
    params = {"track": ("palm", tuple(TRACK)), "steady": (1.0, 0.1, 5.0), "responsive": (0.02, 0.0, 0.2),
              "max_grab": (0.6, 0.1, 1.0), "tap_damp": (0.4, 0.0, 1.5), "tap_trigger": (5, 1, 30), "tap_still": (60, 10, 200)}
    TAP_HOLD = 0.25  # s: stay damped this long after the finger stops (palm rebound)
    TAP_RELEASE = 0.08  # s: catch-up time once damping ends, so the cursor never jumps

    def __init__(self, overrides=None):
        super().__init__(overrides)
        self.filters, self.t = {}, 0.0
        self.damped = {}  # hand side → (cursor-side position, last time, damped until, FingerMotion)

    def _damp(self, h, pos, p, fresh):
        fm = FingerMotion() if fresh or h.side not in self.damped else self.damped[h.side][3]
        eff, t, until = (pos, self.t, 0.0) if fresh else self.damped.get(h.side, (pos, self.t, 0.0))[:3]
        speed = float(np.linalg.norm(self.filters[h.side].dx))  # filtered palm speed, mm/s
        if fm.update(self.t, np.array([f.tip - h.palm for f in h.fingers]), speed, p["tap_trigger"], p["tap_still"]):
            until = self.t + self.TAP_HOLD  # a finger moved while the palm was resting
        elif speed > fm.hand_max:
            until = 0.0
        tau = p["tap_damp"] if self.t < until else self.TAP_RELEASE
        eff = pos if tau <= 0 else pos + (eff - pos) * math.exp(-max(self.t - t, 1e-3) / tau)
        self.damped[h.side] = (eff, self.t, until, fm)
        return eff

    def update(self, frame):
        self.t = frame.t
        yield from super().update(frame)

    def check(self, h, p):
        if h.grab >= p["max_grab"]:
            return None
        if h.side not in self.state:  # new session → fresh filter, no stale position
            self.filters[h.side] = OneEuro(p["steady"], p["responsive"])
        pos = TRACK.get(p["track"], TRACK["palm"])(h)[:2].astype(np.float64)
        return self._damp(h, self.filters[h.side](pos, self.t), p, h.side not in self.state)


@register
class DesktopPointer(Pointer):
    """Hand position mapped onto the whole desktop (drives desktop mouse). Value: (u, v), 0…1 from the
    top-left. The view is `view_width` mm wide (centred over the device) and `view_top` mm tall above the device; the inner
    `coverage` of it reaches the left, right and top screen edges before the hand leaves view, and
    the bottom edge sits at `bottom` mm so the hand never has to come down to the device.
    Precision: after `dwell` s slower than `enter_speed` mm/s (and over `edge` mm from the view's limits) the
    cursor stops following the hand 1:1 and moves `precision` times as far, rising to 1:1 at `radius` mm from
    where it locked; tremor under `rest` mm is ignored. Faster than `exit_speed`, or near the limits, it
    glides back onto the hand over `glide` s, so the limits always reach the screen edges. A finger tap
    (`tap_trigger`, `tap_still`) undoes the palm's dip and holds the cursor until `tap_hold` s after."""
    name, mode = "desktop_pointer", "raw"
    doc = __doc__
    params = {**{k: v for k, v in Pointer.params.items() if k != "tap_damp"},
              "steady": (0.6, 0.1, 5.0), "responsive": (0.16, 0.0, 0.2),
              "view_width": (251, 150, 800), "view_top": (351, 250, 700), "coverage": (0.85, 0.5, 1.0),
              "bottom": (150, 40, 300), "precision": (0.2, 0.05, 1.0), "dwell": (0.10, 0.0, 1.0),
              "enter_speed": (40, 5, 200), "exit_speed": (150, 20, 600), "radius": (25, 1, 100),
              "edge": (20, 0, 100), "rest": (0.2, 0.0, 2.0), "glide": (0.12, 0.01, 1.0), "tap_hold": (0.30, 0.0, 1.0)}

    def __init__(self, overrides=None):
        super().__init__(overrides)
        self.locks = {}  # hand side → (PrecisionLock, FingerMotion)
        self.precise = set()  # hand sides currently in precision

    def _damp(self, h, pos, p, fresh):  # taps are handled by the PrecisionLock instead
        return pos

    def update(self, frame):
        yield from super().update(frame)
        self.precise &= set(self.state)  # a hand that left or made a fist is no longer precise

    def check(self, h, p):
        fresh = h.side not in self.state
        hand = super().check(h, p)
        if hand is None:
            return None
        half = max(p["coverage"] * p["view_width"] / 2, 1.0)
        top = max(p["coverage"] * p["view_top"], p["bottom"] + 1)
        lo, hi = np.array([-half, p["bottom"]]), np.array([half, top])
        if fresh:  # a returning hand starts in coarse mode, on the plain mapping
            self.locks[h.side] = (PrecisionLock(p), FingerMotion())
        lock, fm = self.locks[h.side]
        speed = float(np.linalg.norm(self.filters[h.side].dx))  # filtered palm speed, mm/s
        tap = fm.update(self.t, np.array([f.tip - h.palm for f in h.fingers]), speed, p["tap_trigger"], p["tap_still"])
        cursor = lock.step(self.t, np.clip(hand, lo, hi), speed, tap, lo, hi)
        (self.precise.add if lock.precise else self.precise.discard)(h.side)
        return np.clip(((cursor[0] + half) / (2 * half), (top - cursor[1]) / (top - p["bottom"])), 0.0, 1.0)


@continuous("pinch_drag", hands=1, mode="delta", strength=(0.85, 0.3, 1.0))
def pinch_drag(h, p):
    """Pinch and move. Value: (dx, dy, dz) mm from where the pinch started."""
    return h.palm if h.pinch > p["strength"] else None
