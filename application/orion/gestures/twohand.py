"""Continuous gestures: values streamed while a condition holds."""

import math

import numpy as np

from . import Continuous, continuous, register


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

TRACK = {
    "palm": lambda h: h.stable,  # service-stabilised palm: steady, ignores finger taps
    "knuckles": lambda h: (h["index"].joints[1] + h["middle"].joints[1]) / 2,  # steady, quicker than palm
    "index": lambda h: h["index"].tip,
    "middle": lambda h: h["middle"].tip,
    "pinch": _pinch_point,
}


@register
class Pointer(Continuous):
    """Hand position while the hand is open-ish. Value: (dx, dy) mm since last frame — drives air mouse.
    `track` picks the point that steers; palm or knuckles stay put while you tap or pinch."""
    name, mode = "pointer", "step"
    doc = __doc__
    params = {"track": ("palm", tuple(TRACK)), "smoothing": (0.3, 0.0, 0.9), "max_grab": (0.6, 0.1, 1.0)}

    def __init__(self, overrides=None):
        super().__init__(overrides)
        self.ema = {}

    def check(self, h, p):
        if h.grab >= p["max_grab"]:
            self.ema.pop(h.side, None)
            return None
        pos = TRACK.get(p["track"], TRACK["palm"])(h)[:2].astype(np.float64)
        prev = self.ema.get(h.side) if h.side in self.state else None  # new session → no stale smoothing
        a = p["smoothing"]
        self.ema[h.side] = pos if prev is None else prev * a + pos * (1 - a)  # exponential smoothing
        return self.ema[h.side]


@continuous("pinch_drag", hands=1, mode="delta", strength=(0.85, 0.3, 1.0))
def pinch_drag(h, p):
    """Pinch and move. Value: (dx, dy, dz) mm from where the pinch started."""
    return h.palm if h.pinch > p["strength"] else None
