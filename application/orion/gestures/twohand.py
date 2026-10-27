"""Continuous gestures: values streamed while a condition holds."""

import math

import numpy as np

from . import Continuous, continuous, register
from .fingers import FingerMotion


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
    Fine control: cursor = hand position + a small `offset`. Slow movement is scaled down to `fine` times
    (so a 4K button is easy to land on), which builds the offset (at most `reach` mm); fast sweeps run 1:1
    and clear it by distance travelled; within `edge` mm of the view's limits it fades out, so a fully
    extended hand always reaches the screen edge. `rest` (mm) is a tiny latch that ignores tremor."""
    name, mode = "desktop_pointer", "raw"
    doc = __doc__
    params = {**Pointer.params, "steady": (0.6, 0.1, 5.0), "responsive": (0.16, 0.0, 0.2),
              "view_width": (251, 150, 800), "view_top": (351, 250, 700), "coverage": (0.85, 0.5, 1.0),
              "bottom": (150, 40, 300), "fine": (0.94, 0.05, 1.0), "fine_speed": (207, 10, 400),
              "reach": (34, 5, 150), "edge": (26, 1, 100), "rest": (0.22, 0.0, 2.0)}

    def __init__(self, overrides=None):
        super().__init__(overrides)
        self.cur = {}  # hand side → (offset mm, last hand mm, last time)
        self.held = {}  # hand side → hand position after the rest latch

    def check(self, h, p):
        fresh = h.side not in self.state
        hand = super().check(h, p)
        if hand is None:
            return None
        half = p["coverage"] * p["view_width"] / 2
        top = max(p["coverage"] * p["view_top"], p["bottom"] + 1)
        lo, hi = np.array([-half, p["bottom"]]), np.array([half, top])
        hand = np.clip(hand, lo, hi)
        held = self.held.get(h.side)
        if held is not None and not fresh:  # rest latch: tremor under `rest` mm leaves the hand "put"; beyond it we trail by `rest`
            d = hand - held
            n = float(np.linalg.norm(d))
            hand = held if n <= p["rest"] else held + d * (1 - p["rest"] / n)
        self.held[h.side] = hand
        offset, last, t = (np.zeros(2), hand, self.t) if fresh else self.cur.get(h.side, (np.zeros(2), hand, self.t))
        step = hand - last
        dist = float(np.linalg.norm(step))
        v2 = (dist / max(self.t - t, 1e-3)) ** 2
        fast = v2 / (v2 + p["fine_speed"] ** 2)  # 0 slow … 1 fast
        offset = (offset + (p["fine"] + (1 - p["fine"]) * fast - 1) * step) * math.exp(-dist * fast / 20)
        n = float(np.linalg.norm(offset))
        if n > p["reach"]:
            offset *= p["reach"] / n
        self.cur[h.side] = (offset, hand, self.t)
        room = min(float(np.min(hand - lo)), float(np.min(hi - hand))) / p["edge"]  # 0 at the limit
        room = min(max(room, 0.0), 1.0)
        cursor = np.clip(hand + offset * room * room * (3 - 2 * room), lo, hi)
        return np.clip(((cursor[0] + half) / (2 * half), (top - cursor[1]) / (top - p["bottom"])), 0.0, 1.0)


@continuous("pinch_drag", hands=1, mode="delta", strength=(0.85, 0.3, 1.0))
def pinch_drag(h, p):
    """Pinch and move. Value: (dx, dy, dz) mm from where the pinch started."""
    return h.palm if h.pinch > p["strength"] else None
