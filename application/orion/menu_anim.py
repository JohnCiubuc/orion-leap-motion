"""Animation model for the OrionDo pie: messages in, per-frame view values out.

Pure Python with no imports from the rest of orion, so the GTK overlay script can import it by bare name and
tests can drive it with a fake clock. All times are monotonic seconds supplied by the caller. Marker x/y are in
units of the pull distance, as the engine sends them.
"""

import math
from dataclasses import dataclass, field

OPEN, STAGGER = 0.28, 0.025  # a slice's bloom, and the delay between neighbours
CLOSE, CLOSE_STAGGER = 0.12, 0.015  # collapse, in reverse order
FLASH = 0.14  # fired slice flashes this long before the pie collapses
FOLLOW = 0.04  # s: hover, pull and marker catch up to their targets (≈95 % in 0.12 s)
OVERSHOOT = 1.70158


def _clamp(t):
    return min(max(t, 0.0), 1.0)


def ease_out_cubic(t):
    return 1 - (1 - _clamp(t)) ** 3


def ease_out_back(t):
    if t <= 0 or t >= 1:
        return _clamp(t)  # exact endpoints: no float residue before the bloom or after it
    t -= 1
    return 1 + (OVERSHOOT + 1) * t ** 3 + OVERSHOOT * t ** 2


@dataclass
class SliceView:
    scale: float = 0.0
    alpha: float = 0.0
    lift: float = 0.0  # hover: 0…1
    stretch: float = 0.0  # pull progress of the hovered slice: 0…1
    glow: float = 0.0
    flash: float = 0.0


@dataclass
class MenuView:
    visible: bool = False
    slices: list = field(default_factory=list)
    marker: tuple = (0.0, 0.0)
    arc: float = 0.0  # pull progress ring
    hover: int | None = None


class MenuAnim:
    def __init__(self):
        self.t_open = None
        self.labels = []

    def open(self, labels, now):
        n = len(labels)
        self.labels, self.t_open, self.t_close, self.fire_at, self.fired = list(labels), now, None, None, None
        self.last, self.hover, self.pull = now, None, 0.0
        self.lift, self.stretch, self.arc = [0.0] * n, [0.0] * n, 0.0
        self.marker, self.target = [0.0, 0.0], (0.0, 0.0)

    def update(self, x, y, hover, pull, now):
        if self.t_open is None:
            return
        self._advance(now)  # integrate up to now with the old targets first
        self.target, self.hover, self.pull = (x, y), hover, pull

    def fire(self, index, now):
        if self.t_open is None:
            return
        self._advance(now)
        self.fired, self.fire_at = index, now
        if self.t_close is None:
            self.t_close = now + FLASH  # collapse once the flash has played

    def close(self, now):
        if self.t_open is not None and self.t_close is None:
            self.t_close = now

    def _advance(self, now):
        k = 1 - math.exp(-max(now - self.last, 0.0) / FOLLOW)
        self.last = max(now, self.last)
        for i in range(len(self.labels)):
            on = self.hover == i
            self.lift[i] += ((1.0 if on else 0.0) - self.lift[i]) * k
            self.stretch[i] += ((self.pull if on else 0.0) - self.stretch[i]) * k
        self.arc += ((self.pull if self.hover is not None else 0.0) - self.arc) * k
        self.marker = [m + (t - m) * k for m, t in zip(self.marker, self.target)]

    def step(self, now) -> MenuView:
        if self.t_open is None:
            return MenuView()
        self._advance(now)
        n = len(self.labels)
        slices = []
        for i in range(n):
            p = (now - self.t_open - i * STAGGER) / OPEN
            gone = 1.0
            if self.t_close is not None:
                gone = 1 - ease_out_cubic((now - self.t_close - (n - 1 - i) * CLOSE_STAGGER) / CLOSE)
            flash = max(0.0, 1 - (now - self.fire_at) / FLASH) if self.fired == i else 0.0
            slices.append(SliceView(ease_out_back(p) * gone, _clamp(p * 2) * gone, self.lift[i], self.stretch[i],
                                    self.lift[i], flash))
        shown = self.t_close is None or now < self.t_close + CLOSE + CLOSE_STAGGER * (n - 1)
        return MenuView(shown, slices, (self.marker[0], self.marker[1]), self.arc, self.hover)
