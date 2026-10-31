"""Relative "ratchet" gestures: pinch (or grab) to set a reference point, then move away from it.

Each time the hand travels `step` mm from the reference point, the gesture fires once
(`<name>.up/.down/.left/.right`) and the reference point jumps to where the hand is now.
So the distance moved, not the time held, decides how many events fire: lift a pinch 6 cm
with a 2 cm step and you get three scroll notches. `axis` sets what counts as up/down:
vertical (raise/lower), depth (push away/pull in) or both (up or away = up).
Event value: the new reference point [x, y, z] in mm.
"""

from __future__ import annotations

import numpy as np

from . import SIDES, Gesture, GestureEvent, register
from .fingers import pinch_strength


class Joystick(Gesture):
    family = "joystick"
    doc = __doc__
    variants = ("up", "down", "left", "right")
    params = {"step": (20, 5, 100), "axis": ("both", ("vertical", "depth", "both"))}

    def held(self, h, was_held: bool) -> bool:  # subclass: is the "clutch" engaged?
        raise NotImplementedError

    def __init__(self, overrides=None):
        super().__init__(overrides)
        self.anchor = {s: None for s in SIDES}

    def update(self, frame):
        p, t = self.p, frame.t
        held = {s: (h := frame.hand(s)) is not None and self.held(h, self.anchor[s] is not None) for s in SIDES}
        both = all(held.values())  # two hands clutched = zoom/rotate territory, not a joystick
        for side in SIDES:
            h, anchor = frame.hand(side), self.anchor[side]
            if not held[side] or both:
                if anchor is not None:
                    self.anchor[side] = None
                    yield GestureEvent(self.name, "end", None, side, t)
                continue
            if anchor is None:  # clutch engaged: remember where
                self.anchor[side] = h.palm.copy()
                yield GestureEvent(self.name, "begin", h.palm.tolist(), side, t)
                continue
            d = h.palm - anchor
            v = {"vertical": d[1], "depth": -d[2], "both": d[1] - d[2]}[p["axis"]]  # Leap +z points at you
            mag, way = max((abs(v), "up" if v > 0 else "down"), (abs(d[0]), "right" if d[0] > 0 else "left"))
            if mag >= p["step"]:
                self.anchor[side] = h.palm.copy()  # ratchet: measure the next step from here
                yield GestureEvent(f"{self.name}.{way}", "fire", np.round(h.palm, 1).tolist(), side, t)


@register
class PinchJoystick(Joystick):
    name = "pinch_joy"
    doc = "Pinch, then move: one event per step of distance, measured from where you last fired (scroll…)."
    params = {**Joystick.params, "strength": (0.85, 0.3, 1.0)}

    def held(self, h, was_held):
        return pinch_strength(h) > self.p["strength"] - (0.15 if was_held else 0)  # hysteresis: no flicker


@register
class GrabJoystick(Joystick):
    name = "grab_joy"
    doc = "Make a fist, then move: one event per step of distance, measured from where you last fired (volume…)."
    params = {**Joystick.params, "strength": (0.85, 0.3, 1.0)}

    def held(self, h, was_held):
        # a real fist: thumb tucked too, so thumbs up/down don't count
        return h.grab > self.p["strength"] - (0.15 if was_held else 0) and not h.extended
