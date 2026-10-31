"""Fingertip motion relative to the palm, shared by the air mouse and the desktop pointer."""

from collections import deque

import numpy as np


class FingerMotion:
    """Flags a tap: a fingertip moved `trigger` mm against the palm within `window` s while the palm was resting.
    One instance per hand side."""

    def __init__(self, window=0.12, hand_max=250.0):
        self.window, self.hand_max = window, hand_max  # window: per-frame speed is mostly noise, so judge over time
        self.hist = deque()  # (t, fingertips rel. palm, palm speed)

    def reset(self):
        self.hist.clear()

    def update(self, t, tips_rel_palm, speed, trigger, still):
        self.hist.append((t, tips_rel_palm, speed))
        while t - self.hist[0][0] > self.window:
            self.hist.popleft()
        if speed > self.hand_max:  # a deliberate sweep, not a tap
            return False
        _, then, then_speed = self.hist[0]
        moved = float(np.max(np.linalg.norm(tips_rel_palm - then, axis=1)))
        return moved >= trigger and then_speed < still


# ── Thumb contact ─────────────────────────────────────────────────────────────
# Leap's `pinch` is thumb-to-ANY-finger (it reads ~1.0 on a middle/ring/pinky touch, and on a peace sign),
# and `extended` is unreliable once the thumb touches, so contact is judged from the tips themselves.

TOUCH = 30.0  # mm across the camera's image plane (x, z): a fingertip this close to the thumb tip is touching. Depth (y) is ignored: a monocular source knows it worst, and touching tips coincide in the image
MARGIN = 6.0  # mm: when two tips are that close, the one level with the thumb tip (along the fingers) must lead by this much
SHAPE = {"grab": 0.7, "straight": 0.85}  # shortcut: tuned on one recording of loose curls, retune on other hand shapes


def straightness(finger) -> float:
    """1.0 for a straight finger, falling as it curls (tip distance from the knuckle over bone length)."""
    j = finger.joints[1:]
    return float(np.linalg.norm(j[-1] - j[0]) / np.linalg.norm(j[1:] - j[:-1], axis=1).sum())


def _tips(h):
    """[(|offset along the fingers|, distance across the image plane, name)] of each fingertip from the thumb tip."""
    tip, along = h["thumb"].tip, h.direction
    out = []
    for name in ("index", "middle", "ring", "pinky"):
        v = h[name].tip - tip
        out.append((abs(float(v @ along)), float(np.hypot(v[0], v[2])), name))
    return out


def thumb_contact(h):
    """The finger whose tip the thumb touches ("index"…"pinky"), or None when nothing, or no single finger, is."""
    near = sorted(t for t in _tips(h) if t[1] < TOUCH)
    if not near or (len(near) > 1 and near[1][0] - near[0][0] < MARGIN):
        return None
    return near[0][2]


def thumb_touch(h):
    """`thumb_contact` for middle, ring or pinky, unless it is a fist or a peace sign (thumb holding ring + pinky down)."""
    name = thumb_contact(h)
    if name in (None, "index") or h.grab >= SHAPE["grab"]:
        return None
    return None if name == "ring" and straightness(h["pinky"]) < SHAPE["straight"] else name


def pinch_strength(h) -> float:
    """Thumb-index pinch: Leap's value, except 0 while the thumb is on another finger (nearer the thumb tip's level than the index)."""
    tips = {name: (fwd, dist) for fwd, dist, name in _tips(h)}
    return 0.0 if any(d < TOUCH and f < tips["index"][0] for n, (f, d) in tips.items() if n != "index") else h.pinch
