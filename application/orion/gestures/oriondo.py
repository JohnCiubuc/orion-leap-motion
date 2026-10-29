"""OrionDo: a pose opens a radial menu, the index fingertip steers a marker, pulling it out fires an item."""

import math

import numpy as np

from . import REGISTRY, Gesture, GestureEvent, poses, register  # noqa: F401  (poses: registers what `trigger` can name)
from .fingers import FingerMotion

HYSTERESIS = 4.0  # degrees past a slice border before the hover switches
REANCHOR = 0.15  # s without the hand: wherever it comes back becomes the new centre
TAP_GRACE = 0.15  # s after entering or leaving a submenu in which a fingertip tap is ignored: the pull itself flicks the finger


def slot_angles(n: int, back: float | None) -> list[float]:
    """Centre angle (degrees clockwise from the top) of each of `n` items. The root spreads them evenly from the top;
    a submenu keeps the slot facing its parent (`back`) free and fills the rest clockwise from it."""
    if back is None:
        return [i * 360 / n for i in range(n)]
    return [(back + (i + 1) * 360 / (n + 1)) % 360 for i in range(n)]


def _labels(items):
    return [str(i.get("label", "")) for i in items]


def _subs(items):
    return [isinstance(i.get("items"), list) for i in items]


@register
class OrionDo(Gesture):
    """Radial menu. The trigger pose opens it (items come from the `items` list in the config, clockwise from
    the top, equally spaced); the index fingertip moves a marker from where it was at the open. Moving past
    `deadzone` mm hovers the slice in that direction, pulling out to `pull` mm fires it. A fingertip tap at the
    centre closes the menu without firing; so does losing the hand for `lost` s. An item with an `items` list is a
    submenu: pulling it re-centres the menu on the fingertip and shows its children, with the slot facing the parent
    left free; pulling toward that slot goes back one level."""
    name = family = "oriondo"
    doc = __doc__
    params = {"trigger": ("peace", tuple(n for n, c in REGISTRY.items() if c.family == "pose")),
              "deadzone": (8, 2, 40), "pull": (35, 15, 120), "lost": (1.5, 0.2, 5.0), "cooldown": (0.6, 0.0, 3.0),
              "tap_trigger": (5, 1, 30), "tap_still": (60, 10, 200)}

    def __init__(self, overrides=None):
        super().__init__(overrides)
        self.items = [i for i in (overrides or {}).get("items") or [] if isinstance(i, dict)]  # not a slider param: the base class drops it
        self.skin = str((overrides or {}).get("skin") or "aurora")  # nor is this: the overlay's drawing style
        self.allow = lambda: True  # the engine vetoes opening (paused, exclusive mode, no overlay)
        trigger = REGISTRY.get(self.p["trigger"])
        self.pose = trigger() if trigger and trigger.family == "pose" else None
        self.menu, self.cool = None, 0.0

    def reset(self):
        allow = self.allow
        self.__init__({**self.p, "items": self.items, "skin": self.skin})
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
                         "hover": None, "seen": frame.t, "tap": FingerMotion(), "items": self.items, "back": None,
                         "stack": [], "grace": 0.0}
            yield GestureEvent(self.name, "begin", {"labels": _labels(self.items), "subs": _subs(self.items),
                                                    "skin": self.skin}, opener, frame.t)

    def _steer(self, frame):
        m, p = self.menu, self.p
        if not self.allow():  # paused, an exclusive mode, or no overlay to show the pie: never fire blind
            yield self._close(frame, "blocked")
            return
        h = frame.hand(m["side"])
        if h is None:
            if frame.t - m["seen"] > p["lost"]:
                yield self._close(frame, "lost")
            return
        tip = h["index"].tip[:2].astype(np.float64)
        if frame.t - m["seen"] > REANCHOR:  # back from out of view: measured from where it left, it could fire at once
            m.update(origin=tip, hover=None, tap=FingerMotion())
        m["seen"] = frame.t
        v = tip - m["origin"]
        r = float(np.hypot(*v))
        # the index only: dropping the trigger pose curls the other fingers, which must not read as a tap
        if frame.t < m["grace"]:  # the pull just flicked the finger: start judging taps from a clean history afterwards
            m["tap"].reset()
            tapped = False
        else:
            tapped = m["tap"].update(frame.t, np.array([h["index"].tip - h.palm]),
                                     float(np.linalg.norm(h.velocity)), p["tap_trigger"], p["tap_still"])
        if tapped and r < p["deadzone"]:
            yield self._close(frame, "tap")
            return
        m["hover"] = hover = self._sector(v, r, m["hover"])
        if r >= p["pull"] and hover is not None:
            if hover < 0:  # the slot facing the parent
                yield self._leave(m, tip, frame)
                return
            item = m["items"][hover]
            if "items" not in item:
                yield GestureEvent(self.name, "fire", {"index": hover, "item": item}, m["side"], frame.t)
                yield self._close(frame, "fired")
                return
            kids = [k for k in item["items"] if isinstance(k, dict)] if isinstance(item["items"], list) else []
            if kids:
                yield self._enter(m, tip, frame, hover, item, kids)
                return
        progress = min(max((r - p["deadzone"]) / max(p["pull"] - p["deadzone"], 1e-6), 0.0), 1.0)
        value = {"x": float(v[0]) / p["pull"], "y": float(v[1]) / p["pull"], "hover": hover, "pull": progress}
        yield GestureEvent(self.name, "update", value, m["side"], frame.t)

    def _sector(self, v, r, current):
        """Slice under the marker (None in the centre); stays on `current` until the angle is clearly past its border."""
        if r < self.p["deadzone"]:
            return None
        back = self.menu["back"]
        shift = 0 if back is None else 1  # a submenu's slot 0 faces the parent, so slot = hover + 1
        slots = len(self.menu["items"]) + shift
        width = 360 / slots
        angle = (math.degrees(math.atan2(v[0], v[1])) - (back or 0)) % 360  # clockwise from the first slot
        if current is not None and abs((angle - (current + shift) * width + 180) % 360 - 180) <= width / 2 + HYSTERESIS:
            return current
        return round(angle / width) % slots - shift

    def _restart(self, m, tip, frame):
        """New level: the marker measures from where the fingertip is now, with nothing hovered, so it cannot fire at once."""
        m.update(origin=tip, hover=None, tap=FingerMotion(), seen=frame.t, grace=frame.t + TAP_GRACE)

    def _enter(self, m, tip, frame, hover, item, kids):
        back = (slot_angles(len(m["items"]), m["back"])[hover] + 180) % 360
        m["stack"].append({"items": m["items"], "back": m["back"], "parent": str(item.get("label", ""))})
        m.update(items=kids, back=back)
        self._restart(m, tip, frame)
        return GestureEvent(self.name, "enter", {"labels": _labels(m["items"]), "subs": _subs(m["items"]), "back": back,
                                                 "depth": len(m["stack"]), "parent": m["stack"][-1]["parent"]}, m["side"], frame.t)

    def _leave(self, m, tip, frame):
        away, level = m["back"], m["stack"].pop()
        m.update(items=level["items"], back=level["back"])
        self._restart(m, tip, frame)
        return GestureEvent(self.name, "back", {"labels": _labels(m["items"]), "subs": _subs(m["items"]), "back": m["back"],
                                                "depth": len(m["stack"]), "away": away}, m["side"], frame.t)

    def _close(self, frame, reason):
        side, self.menu, self.cool = self.menu["side"], None, frame.t + self.p["cooldown"]
        return GestureEvent(self.name, "end", reason, side, frame.t)
