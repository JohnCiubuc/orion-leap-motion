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
TAU = 2 * math.pi
LEAVE = 0.22  # the level being left collapses over about this long
PULSE = 0.35  # s for the enter/back ring to play
GHOST_ALPHA = {1: 0.6, 2: 0.3}  # by distance from the current level; deeper ancestors are not shown
GHOST_FOLLOW = 0.1  # s: ghosts fade toward their target
DAMPING_RATIO = 0.68  # shortcut: slight overshoot on travel; retune by eye on the real overlay


def _clamp(t):
    return min(max(t, 0.0), 1.0)


def ease_out_cubic(t):
    return 1 - (1 - _clamp(t)) ** 3


def ease_out_back(t):
    if t <= 0 or t >= 1:
        return _clamp(t)  # exact endpoints: no float residue before the bloom or after it
    t -= 1
    return 1 + (OVERSHOOT + 1) * t ** 3 + OVERSHOOT * t ** 2


class Spring:
    """Underdamped spring toward `target`: overshoots a little and settles, and stays smooth if the target moves mid-flight."""

    def __init__(self, value=0.0, omega=22.0, ratio=DAMPING_RATIO):
        self.x, self.v, self.target, self.k, self.c = value, 0.0, value, omega * omega, 2 * ratio * omega

    def snap(self, value):
        self.x = self.target = value
        self.v = 0.0

    def step(self, dt):
        while dt > 1e-9:
            h = min(dt, 0.004)  # small steps keep the integration stable at any frame rate
            self.v += (self.k * (self.target - self.x) - self.c * self.v) * h
            self.x += self.v * h
            dt -= h


def vec(deg):
    """Unit step toward `deg` (clockwise from the top) in view units: x right, y down."""
    a = math.radians(deg)
    return math.sin(a), -math.cos(a)


def slice_angles(n, back):
    """Radians clockwise from the top. A submenu keeps the slot at `back` free and fills the rest clockwise from it."""
    if back is None:
        return [i * TAU / n for i in range(n)]
    return [(back + (i + 1) * TAU / (n + 1)) % TAU for i in range(n)]


@dataclass
class SliceView:
    scale: float = 0.0
    alpha: float = 0.0
    lift: float = 0.0  # hover: 0…1
    stretch: float = 0.0  # pull progress of the hovered slice: 0…1
    glow: float = 0.0
    flash: float = 0.0
    angle: float = 0.0  # radians clockwise from the top
    label: str = ""
    sub: bool = False  # opens a submenu


@dataclass
class BackView:
    """The slot facing the parent, which a pull turns into a step back. Drawn as the ghost parent, not as a slice."""
    angle: float
    lift: float = 0.0
    glow: float = 0.0
    stretch: float = 0.0


@dataclass
class GhostView:
    x: float  # travel units from the current centre
    y: float
    alpha: float
    label: str
    lift: float = 0.0


@dataclass
class Layer:
    """A level that is being left."""
    center: tuple  # travel units from the window centre
    slices: list
    slots: int
    leave: float  # 0…1
    picked: int | None  # the item that was pulled to get here (None when stepping back)
    back: float | None = None


@dataclass
class Level:
    labels: list
    subs: list
    back: float | None  # radians, None at the root
    parent: str  # label of the item that opened it
    t0: float  # when its slices start to bloom


@dataclass
class MenuView:
    visible: bool = False
    slices: list = field(default_factory=list)
    marker: tuple = (0.0, 0.0)
    arc: float = 0.0  # pull progress ring
    hover: int | None = None  # -1: the back gap
    slots: int = 0
    back: BackView | None = None
    ghosts: list = field(default_factory=list)
    pan: tuple = (0.0, 0.0)  # where the current centre sits relative to the window centre, travel units
    pulse: float = 1.0  # enter/back ring: 0 at the start, 1 when done
    leaving: list = field(default_factory=list)


class MenuAnim:
    """`travel_time` is about how long the pie takes to travel to a submenu; `reduced_motion` makes every transition instant."""

    def __init__(self, reduced_motion=False, travel_time=0.18):
        self.t_open = None
        self.reduced, self.omega = reduced_motion, 4.0 / travel_time
        self.levels, self.labels = [], []

    def open(self, labels, now, subs=None):
        self.levels = [self._level(labels, subs, None, "", now)]
        self.t_open, self.t_close, self.fire_at, self.fired = now, None, None, None
        self.last, self.hover, self.pull = now, None, 0.0
        self.arc, self.back_lift, self.back_stretch = 0.0, 0.0, 0.0
        self.marker, self.target = [0.0, 0.0], (0.0, 0.0)
        self.pan = [Spring(omega=self.omega), Spring(omega=self.omega)]
        self.leaving, self.ghost_alpha, self.pulse_t = [], {}, None
        self._reset_level()

    def _level(self, labels, subs, back, parent, now):
        subs = list(subs) if subs is not None else [False] * len(labels)
        return Level(list(labels), subs, None if back is None else math.radians(back), parent, now - 1 if self.reduced else now)

    def _reset_level(self):
        n = len(self.levels[-1].labels)
        self.labels = self.levels[-1].labels
        self.lift, self.stretch, self.hover = [0.0] * n, [0.0] * n, None

    def update(self, x, y, hover, pull, now):
        if self.t_open is None:
            return
        self._advance(now)  # integrate up to now with the old targets first
        self.target, self.hover, self.pull = (x, y), hover, pull

    def enter(self, labels, now, back, parent, subs=None):
        """Descend into a submenu whose slot facing the parent is at `back` degrees."""
        if not self._live():
            return
        picked, toward = self.hover if self.hover is not None and self.hover >= 0 else None, (back + 180) % 360
        self._travel(now, toward, picked)
        self.levels.append(self._level(labels, subs, back, parent, now))
        self.ghost_alpha.setdefault(len(self.levels) - 1, 0.0)
        self._reset_level()

    def back(self, labels, now, back, away, subs=None):
        """Step back up to the parent level (`back` is its own back angle, None at the root); `away` is the pull direction."""
        if not self._live() or len(self.levels) < 2:
            return
        self._travel(now, away, None)
        self.ghost_alpha.pop(len(self.levels) - 1, None)
        self.levels.pop()
        top = self.levels[-1]
        self.levels[-1] = Level(list(labels), list(subs) if subs is not None else top.subs, top.back, top.parent,
                                now - 1 if self.reduced else now)
        self._reset_level()

    def _live(self):
        return self.t_open is not None and self.t_close is None

    def _travel(self, now, toward, picked):
        """The pie moves one step toward `toward` degrees; the level being left collapses behind it."""
        self._advance(now)
        old = self.levels[-1]
        ux, uy = vec(toward)
        self.pulse_t = now
        self.marker, self.target, self.arc, self.back_lift, self.back_stretch = [0.0, 0.0], (0.0, 0.0), 0.0, 0.0, 0.0
        if self.reduced:
            self.leaving = []
            for sp in self.pan:
                sp.snap(0.0)
            return
        self.leaving.append({"level": old, "picked": picked, "u": (ux, uy), "t": now})
        for sp, d in zip(self.pan, (ux, uy)):  # the scene stays put: the new centre is one step from wherever the old one is now
            sp.x, sp.target = sp.x + d, 0.0

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
        dt = max(now - self.last, 0.0)
        k = 1 - math.exp(-dt / FOLLOW)
        self.last = max(now, self.last)
        for i in range(len(self.lift)):
            on = self.hover == i
            self.lift[i] += ((1.0 if on else 0.0) - self.lift[i]) * k
            self.stretch[i] += ((self.pull if on else 0.0) - self.stretch[i]) * k
        gap = self.hover == -1
        self.back_lift += ((1.0 if gap else 0.0) - self.back_lift) * k
        self.back_stretch += ((self.pull if gap else 0.0) - self.back_stretch) * k
        self.arc += ((self.pull if self.hover is not None else 0.0) - self.arc) * k
        self.marker = [m + (t - m) * k for m, t in zip(self.marker, self.target)]
        for sp in self.pan:
            sp.step(dt)
        depth = len(self.levels) - 1
        g = 1 - math.exp(-dt / GHOST_FOLLOW)
        for key in self.ghost_alpha:
            self.ghost_alpha[key] += (GHOST_ALPHA.get(depth - key + 1, 0.0) - self.ghost_alpha[key]) * g

    def step(self, now) -> MenuView:
        if self.t_open is None:
            return MenuView()
        self._advance(now)
        cur = self.levels[-1]
        n = len(cur.labels)
        gone_at = lambda i: 1.0 if self.t_close is None else 1 - ease_out_cubic((now - self.t_close - (n - 1 - i) * CLOSE_STAGGER) / CLOSE)  # noqa: E731
        slices = []
        for i, ang in enumerate(slice_angles(n, cur.back)):
            p = (now - cur.t0 - i * STAGGER) / OPEN
            gone = gone_at(i)
            flash = max(0.0, 1 - (now - self.fire_at) / FLASH) if self.fired == i else 0.0
            slices.append(SliceView(ease_out_back(p) * gone, _clamp(p * 2) * gone, self.lift[i], self.stretch[i],
                                    self.lift[i], flash, ang, cur.labels[i], cur.subs[i]))
        shown = self.t_close is None or now < self.t_close + CLOSE + CLOSE_STAGGER * (n - 1)
        pan = (self.pan[0].x, self.pan[1].x)
        back = None if cur.back is None else BackView(cur.back, self.back_lift, self.back_lift, self.back_stretch)
        return MenuView(shown, slices, (self.marker[0], self.marker[1]), self.arc, self.hover,
                        n + (cur.back is not None), back, self._ghosts(cur), pan, self._pulse(now), self._leaving(now, pan))

    def _pulse(self, now):
        return 1.0 if self.pulse_t is None else _clamp((now - self.pulse_t) / PULSE)

    def _ghosts(self, cur):
        ghosts, x, y, depth = [], 0.0, 0.0, len(self.levels) - 1
        for k in range(depth, 0, -1):  # level k was opened from an ancestor hub that sits one step toward its back angle
            lvl = self.levels[k]
            dx, dy = vec(math.degrees(lvl.back))
            x, y = x + dx, y + dy
            alpha = self.ghost_alpha.get(k, 0.0)
            if alpha > 0.005:
                ghosts.append(GhostView(x, y, alpha, lvl.parent, self.back_lift if k == depth else 0.0))
        return ghosts

    def _leaving(self, now, pan):
        out, keep = [], []
        for rec in self.leaving:
            t = now - rec["t"]
            leave = _clamp(t / LEAVE)
            if t >= LEAVE + CLOSE_STAGGER * 12:
                continue
            keep.append(rec)
            lvl, n = rec["level"], len(rec["level"].labels)
            slices = []
            for i, ang in enumerate(slice_angles(n, lvl.back)):
                gone = 1 - ease_out_cubic((t - (n - 1 - i) * CLOSE_STAGGER) / CLOSE)
                picked = rec["picked"] == i
                slices.append(SliceView(1.0 if picked else gone, (1 - ease_out_cubic(t / LEAVE)) if picked else gone,
                                        0.0, 0.0, 0.0, 0.0, ang, lvl.labels[i], lvl.subs[i]))
            ux, uy = rec["u"]
            out.append(Layer((pan[0] - ux, pan[1] - uy), slices, n + (lvl.back is not None), leave, rec["picked"], lvl.back))
        self.leaving = keep  # old layers drop out once their collapse has played
        return out
