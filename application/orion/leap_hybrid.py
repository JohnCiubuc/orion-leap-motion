"""Leap hybrid source: the Leap is the body (position, motion, palm plane, hand identity), MediaPipe the fingers.

`Merger` puts MediaPipe's finger shape onto the Leap's hand; the Leap's own fingers are the fallback whenever MediaPipe
has no fresh hand on the same side. The pure parts need neither OpenCV nor MediaPipe.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from .frame import Finger, Hand

THUMB_HYSTERESIS = (-5.0, 3.0)  # mm around `thumb_out`: the thumb turns off below the first, on above the second


def thumb_lateral(hand: Hand) -> float:
    """How far the thumb tip is toward the thumb side of the palm, in mm across the image plane (Leap x, z).
    Signed along the line from the pinky knuckle to the index knuckle, so a thumb folded over the palm is small or negative."""
    axis = (hand["index"].joints[1] - hand["pinky"].joints[1])[[0, 2]].astype(np.float64)
    norm = float(np.hypot(*axis))
    if norm < 1e-6:
        return 0.0
    return float(axis @ (hand["thumb"].tip - hand.palm)[[0, 2]]) / norm


def _basis(hand: Hand) -> np.ndarray | None:
    """Orthonormal palm frame (along the fingers, across the palm, out of the palm), or None if the hand has no usable one."""
    d = np.asarray(hand.direction, np.float64)
    if np.linalg.norm(d) < 1e-6:
        return None
    d = d / np.linalg.norm(d)
    n = np.asarray(hand.normal, np.float64)
    n = n - (n @ d) * d
    if np.linalg.norm(n) < 1e-6:
        return None
    n = n / np.linalg.norm(n)
    return np.column_stack((d, np.cross(n, d), n))


class Merger:
    """`Merger(cfg)(leap, mp, age)`: `leap` with MediaPipe's fingers, or `leap` itself when MediaPipe has nothing usable.
    `cfg`: `max_age` (s a MediaPipe hand stays usable) and `thumb_out` (mm). Stateful: the thumb rule has hysteresis."""

    def __init__(self, cfg: dict):
        self.cfg, self._thumb = cfg, False

    def __call__(self, leap: Hand, mp: Hand | None, age: float) -> Hand:
        if mp is None or age > self.cfg["max_age"] or mp.side != leap.side:
            return leap
        a, b = _basis(leap), _basis(mp)
        R = a @ b.T if a is not None and b is not None else np.eye(3)  # MediaPipe's palm frame → the Leap's (its tilt is off by 15-25°)
        thumb = self._thumb_out(thumb_lateral(mp))
        fingers = tuple(Finger(f.name, thumb if f.name == "thumb" else f.extended,
                               (leap.palm + (f.joints - mp.palm) @ R.T).astype(np.float32)) for f in mp.fingers)
        return dataclasses.replace(leap, fingers=fingers, pinch=mp.pinch, grab=mp.grab)

    def _thumb_out(self, lateral: float) -> bool:
        low, high = (self.cfg["thumb_out"] + h for h in THUMB_HYSTERESIS)
        if lateral >= high:
            self._thumb = True
        elif lateral < low:
            self._thumb = False
        return self._thumb
