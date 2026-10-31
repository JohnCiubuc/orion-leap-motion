"""Gesture plugin API.

Four families, each with a decorator that turns a small function into a
registered gesture class:

    @pose("fist", hold=0.3)                   fn(hand, p) -> bool
    @motion("swipe", window=0.25, variants=…)  fn(track, p) -> None | True | "variant"
    @continuous("zoom", hands=2, mode="ratio") fn(left, right, p) -> measure | None
    PathGesture                               ($P recogniser over drawn strokes)

Events: poses emit begin/end, motions and paths emit fire, continuous gestures
emit begin/update/end with a value. Extra keyword args on a decorator become
tunable params shown in the UI: name=(default, min, max) → slider,
name=(default, ("a", "b", …)) → dropdown.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np

from ..frame import Frame, Hand

REGISTRY: dict[str, type["Gesture"]] = {}
SIDES = ("left", "right")


@dataclass(slots=True)
class GestureEvent:
    name: str  # "fist", "swipe.left", "path.circle" …
    phase: str  # "begin" | "update" | "end" | "fire"
    value: Any = None
    hand: str | None = None
    t: float = 0.0

    def as_dict(self) -> dict:
        v = self.value.tolist() if isinstance(self.value, np.ndarray) else self.value
        return {"name": self.name, "phase": self.phase, "value": v, "hand": self.hand, "t": self.t}


# ── Base class ────────────────────────────────────────────────────────────────

class Gesture:
    name = ""
    family = "custom"
    doc = ""
    variants: tuple[str, ...] = ()
    params: dict[str, tuple] = {}  # name → (default, min, max) | (default, (choices…))

    def __init__(self, overrides: dict | None = None):
        self.p = {k: v[0] for k, v in self.params.items()}
        self.p.update({k: v for k, v in (overrides or {}).items() if k in self.p})

    def update(self, frame: Frame) -> Iterable[GestureEvent]:
        raise NotImplementedError

    def reset(self):
        self.__init__(self.p)

    @classmethod
    def events(cls) -> list[str]:
        return [f"{cls.name}.{v}" for v in cls.variants] or [cls.name]

    @classmethod
    def meta(cls) -> dict:
        return {"name": cls.name, "family": cls.family, "doc": (cls.doc or "").strip(),
                "events": cls.events(), "module": cls.__module__,
                "params": {k: [v[0], list(v[1])] if isinstance(v[1], tuple) else list(v)
                           for k, v in cls.params.items()}}


def register(cls):
    REGISTRY[cls.name] = cls
    return cls


def _make(base, name, fn, doc, params, **attrs):
    return register(type(name, (base,), {"name": name, "check": staticmethod(fn), "__module__": fn.__module__,
                                         "doc": doc or fn.__doc__ or "", "params": params, **attrs}))


# ── Pose: a hand shape held for `hold` seconds ────────────────────────────────

class Pose(Gesture):
    family = "pose"
    GRACE = 0.1  # tolerate brief tracking flicker (s)

    def __init__(self, overrides=None):
        super().__init__(overrides)
        self.since = {s: None for s in SIDES}  # when the shape first matched
        self.seen = {s: -1.0 for s in SIDES}  # last time it matched
        self.active = {s: False for s in SIDES}

    def update(self, frame):
        for side in SIDES:
            h = frame.hand(side)
            if h is not None and self.check(h, self.p):
                self.seen[side] = frame.t
                self.since[side] = self.since[side] or frame.t
            elif frame.t - self.seen[side] > self.GRACE:
                self.since[side] = None
                if self.active[side]:
                    self.active[side] = False
                    yield GestureEvent(self.name, "end", None, side, frame.t)
            if (self.since[side] and not self.active[side]
                    and frame.t - self.since[side] >= self.p["hold"]):
                self.active[side] = True
                yield GestureEvent(self.name, "begin", None, side, frame.t)


def pose(name, /, *, hold=0.25, doc="", **params):
    return lambda fn: _make(Pose, name, fn, doc, {"hold": (hold, 0.0, 2.0), **params})


# ── Motion: a movement pattern inside a short time window ─────────────────────

class Track:
    """Recent history of one hand: `track.palm` → (N, 3) array, etc."""

    def __init__(self, items):
        self.t = np.array([t for t, _ in items])
        self.hands: list[Hand] = [h for _, h in items]

    def __len__(self):
        return len(self.hands)

    def __getattr__(self, attr):  # palm, normal, velocity, stable, …
        return np.array([getattr(h, attr) for h in self.hands])

    def tip(self, finger: str) -> np.ndarray:
        return np.array([h[finger].tip for h in self.hands])

    @property
    def duration(self) -> float:
        return float(self.t[-1] - self.t[0]) if len(self.t) > 1 else 0.0


class Motion(Gesture):
    family = "motion"

    def __init__(self, overrides=None):
        super().__init__(overrides)
        self.hist = {s: deque() for s in SIDES}
        self.cool = {s: 0.0 for s in SIDES}

    def update(self, frame):
        for side in SIDES:
            h, q = frame.hand(side), self.hist[side]
            if h is None:
                q.clear()
                continue
            q.append((frame.t, h))
            while frame.t - q[0][0] > self.p["window"]:
                q.popleft()
            if frame.t < self.cool[side] or len(q) < 3:
                continue
            r = self.check(Track(q), self.p)
            if r:
                self.cool[side] = frame.t + self.p["cooldown"]
                q.clear()
                name = f"{self.name}.{r}" if isinstance(r, str) else self.name
                yield GestureEvent(name, "fire", None, side, frame.t)


def motion(name, /, *, window=0.3, cooldown=0.5, variants=(), doc="", **params):
    return lambda fn: _make(Motion, name, fn, doc, {"window": (window, 0.05, 2.0),
                            "cooldown": (cooldown, 0.0, 3.0), **params}, variants=tuple(variants))


# ── Continuous: a measured quantity streamed while a condition holds ──────────

class Continuous(Gesture):
    """`mode`: ratio (m / m0), delta (m - m0), step (m - previous), raw (m)."""
    family = "continuous"
    hands = 1
    mode = "ratio"

    def __init__(self, overrides=None):
        super().__init__(overrides)
        self.state = {}  # key → (m0, prev)

    def _value(self, m, m0, prev):
        return {"ratio": lambda: m / m0 if np.all(m0) else 1.0, "delta": lambda: m - m0,
                "step": lambda: m - prev, "raw": lambda: m}[self.mode]()

    def _emit(self, key, m, t):
        st = self.state.get(key)
        if m is None:
            if st:
                del self.state[key]
                yield GestureEvent(self.name, "end", None, key, t)
            return
        m = np.asarray(m, np.float64) if not np.isscalar(m) else float(m)
        if st is None:
            self.state[key] = (m, m)
            yield GestureEvent(self.name, "begin", self._value(m, m, m), key, t)
        else:
            self.state[key] = (st[0], m)
            yield GestureEvent(self.name, "update", self._value(m, *st), key, t)

    def update(self, frame):
        if self.hands == 2:
            l, r = frame.hand("left"), frame.hand("right")
            yield from self._emit("both", self.check(l, r, self.p) if l and r else None, frame.t)
        else:
            for side in SIDES:
                h = frame.hand(side)
                yield from self._emit(side, self.check(h, self.p) if h else None, frame.t)


def continuous(name, /, *, hands=1, mode="ratio", doc="", **params):
    return lambda fn: _make(Continuous, name, fn, doc, params, hands=hands, mode=mode)


# ── Built-ins (importing registers them) ──────────────────────────────────────

def load_builtins():
    from . import joystick, motions, paths, poses, twohand, oriondo  # noqa: F401
