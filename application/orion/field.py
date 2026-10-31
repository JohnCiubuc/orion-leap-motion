"""Ignore hands that are not fully inside the part of the field the Leap tracks well.

Near the edge of its view the Leap still reports a hand, but jittery and partly guessed, which
fires gestures by accident. A hand counts only while its palm and all five fingertips sit inside a
cone about the device's vertical axis (and above MIN_HEIGHT); once admitted it is kept until it is
HYSTERESIS degrees past the edge, so a hand on the boundary does not flicker in and out.
"""

from __future__ import annotations

import dataclasses
import math

from .frame import Frame, Hand

MIN_HEIGHT = 60  # mm above the device; closer than this the cameras see only part of the hand
HYSTERESIS = 8  # degrees


def _angle(p) -> float:
    return math.degrees(math.atan2(math.hypot(p[0], p[2]), max(p[1], 1e-3)))


class FieldGate:
    def __init__(self, config):
        self.cfg = config
        self.ok: set[int] = set()  # ids admitted so far

    def _inside(self, h: Hand, limit: float) -> bool:
        pts = (h.palm, *(f.tip for f in h.fingers))
        return all(p[1] >= MIN_HEIGHT and _angle(p) <= limit for p in pts)

    def __call__(self, frame: Frame) -> Frame:
        limit = float(self.cfg.general["field_angle"])
        if limit <= 0:
            return frame
        body = frame.leap or frame  # the hybrid's MediaPipe depth is poor; judge the Leap's own hand
        good = {h.id for h in body.hands if self._inside(h, limit + (HYSTERESIS if h.id in self.ok else 0))}
        self.ok = good
        if all(h.id in good for h in frame.hands):
            return frame
        keep = lambda f: dataclasses.replace(f, hands=tuple(h for h in f.hands if h.id in good))  # noqa: E731
        return dataclasses.replace(keep(frame), leap=keep(frame.leap) if frame.leap else None)
