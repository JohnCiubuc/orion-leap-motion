"""OrionDo: a pose opens a radial menu, the index fingertip steers a marker, pulling it out fires an item."""

import math

import numpy as np

from . import REGISTRY, Gesture, GestureEvent, poses, register  # noqa: F401  (poses: registers what `trigger` can name)
from .fingers import FingerMotion

HYSTERESIS = 4.0  # degrees past a slice border before the hover switches


@register
class OrionDo(Gesture):
    """Radial menu. The trigger pose opens it (items come from the `items` list in the config, clockwise from
    the top, equally spaced); the index fingertip moves a marker from where it was at the open. Moving past
    `deadzone` mm hovers the slice in that direction, pulling out to `pull` mm fires it. A fingertip tap at the
    centre closes the menu without firing; so does losing the hand for `lost` s."""
    name = family = "oriondo"
    doc = __doc__
    params = {"trigger": ("peace", tuple(n for n, c in REGISTRY.items() if c.family == "pose")),
              "deadzone": (8, 2, 40), "pull": (35, 15, 120), "lost": (1.5, 0.2, 5.0), "cooldown": (0.6, 0.0, 3.0),
              "tap_trigger": (5, 1, 30), "tap_still": (60, 10, 200)}

    def __init__(self, overrides=None):
        super().__init__(overrides)
        self.items = list((overrides or {}).get("items") or [])  # not a slider param: the base class drops it
        self.allow = lambda: True  # the engine vetoes opening (paused, exclusive mode, no overlay)
        trigger = REGISTRY.get(self.p["trigger"])
        self.pose = trigger() if trigger and trigger.family == "pose" else None
        self.menu, self.cool = None, 0.0

    def reset(self):
        allow = self.allow
        self.__init__({**self.p, "items": self.items})
        self.allow = allow

    def update(self, frame):
        opener = None
        for ev in self.pose.update(frame) if self.pose else ():
            if ev.phase == "begin":
                opener = ev.hand
        if self.menu:
            yield from self._steer(frame)
        elif opener and frame.t >= self.cool and self.items and self.allow() and frame.hand(opener):
            self.menu = {"side": opener, "origin": frame.hand(opener)["index"].tip[:2].astype(np.float64),
                         "hover": None, "seen": frame.t, "tap": FingerMotion()}
            labels = [str(i.get("label", "")) for i in self.items]
            yield GestureEvent(self.name, "begin", {"labels": labels}, opener, frame.t)

    def _steer(self, frame):
        m, p = self.menu, self.p
        h = frame.hand(m["side"])
        if h is None:
            if frame.t - m["seen"] > p["lost"]:
                yield self._close(frame, "lost")
            return
        m["seen"] = frame.t
        v = h["index"].tip[:2].astype(np.float64) - m["origin"]
        r = float(np.hypot(*v))
        # the index only: dropping the trigger pose curls the other fingers, which must not read as a tap
        tapped = m["tap"].update(frame.t, np.array([h["index"].tip - h.palm]),
                                 float(np.linalg.norm(h.velocity)), p["tap_trigger"], p["tap_still"])
        if tapped and r < p["deadzone"]:
            yield self._close(frame, "tap")
            return
        m["hover"] = hover = self._sector(v, r, m["hover"])
        if r >= p["pull"] and hover is not None:
            yield GestureEvent(self.name, "fire", {"index": hover, "item": self.items[hover]}, m["side"], frame.t)
            yield self._close(frame, "fired")
            return
        progress = min(max((r - p["deadzone"]) / max(p["pull"] - p["deadzone"], 1e-6), 0.0), 1.0)
        value = {"x": float(v[0]) / p["pull"], "y": float(v[1]) / p["pull"], "hover": hover, "pull": progress}
        yield GestureEvent(self.name, "update", value, m["side"], frame.t)

    def _sector(self, v, r, current):
        """Slice under the marker (None in the centre); stays on `current` until the angle is clearly past its border."""
        if r < self.p["deadzone"]:
            return None
        n = len(self.items)
        width = 360 / n
        angle = math.degrees(math.atan2(v[0], v[1])) % 360  # clockwise from the top
        if current is not None and abs((angle - current * width + 180) % 360 - 180) <= width / 2 + HYSTERESIS:
            return current
        return round(angle / width) % n

    def _close(self, frame, reason):
        side, self.menu, self.cool = self.menu["side"], None, frame.t + self.p["cooldown"]
        return GestureEvent(self.name, "end", reason, side, frame.t)
