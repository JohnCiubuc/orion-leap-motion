"""Leap hybrid source: the Leap is the body (position, motion, palm plane, hand identity), MediaPipe the fingers.

`Merger` puts MediaPipe's finger shape onto the Leap's hand; the Leap's own fingers are the fallback whenever MediaPipe
has no fresh hand on the same side. The pure parts need neither OpenCV nor MediaPipe.
"""

from __future__ import annotations

import dataclasses
import logging
import time

import numpy as np

from .frame import Finger, Frame, Hand, from_leap
from .leap_mp import LeapMediaPipeSource

log = logging.getLogger(__name__)

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


class LeapHybridSource(LeapMediaPipeSource):
    """One frame per Leap tracking event, with MediaPipe's fingers on the Leap's hand. The MediaPipe worker (inherited from
    `LeapMediaPipeSource`) only publishes its newest hand. `frame.leap` keeps the Leap's own frame, which OrionDo reads."""
    name = "leap_hybrid"

    def __init__(self, on_frame, on_image, ir_fps: float = 30, *, cfg: dict, hybrid: dict, rectifier_factory=None, finder_factory=None):
        super().__init__(on_frame, on_image, ir_fps, cfg=cfg, rectifier_factory=rectifier_factory, finder_factory=finder_factory)
        self.merger, self._latest = Merger(hybrid), (0.0, None)  # (when, the worker's newest hand or None)
        self.status["fingers"] = "leap"

    def _emit(self, t: float, hands):
        self._latest = (t, hands[0] if hands else None)

    def _tracking(self, e):
        leap = from_leap(e)
        hands = leap.hands
        try:
            t, mp = self._latest
            age, merged = time.monotonic() - t, []
            for h in leap.hands:  # one MediaPipe hand: only the first Leap hand on its side takes it
                m = self.merger(h, mp, age)
                if m is not h:
                    mp = None
                merged.append(m)
            hands = tuple(merged)
        except Exception:  # the Leap's own hands are always a good answer
            log.exception("leap_hybrid: merge failed")
        self.status["fingers"] = "mediapipe" if any(a is not b for a, b in zip(hands, leap.hands)) else "leap"
        self.on_frame(Frame(t=leap.t, fps=leap.fps, hands=hands, source=self.name, leap=leap))
