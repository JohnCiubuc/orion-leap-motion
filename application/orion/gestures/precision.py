"""Desktop pointer cursor: coarse (cursor = hand) or precision (scaled relative steps), with a glide between."""

from collections import deque

import numpy as np


class PrecisionLock:
    """One per hand. step() takes the filtered palm `p` (mm) and returns the cursor in the same space."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.precise = False
        self.c = None  # cursor
        self.off = None  # coarse: cursor − p, decayed on its own so it reaches exactly 0 (c − p would stall at an ulp)
        self.t = None
        self.still = 0.0  # how long the hand has been slow and clear of the edges
        self.hold_until = -np.inf
        self.tapping = False
        self.hist = deque()  # (t, cursor), for the tap rewind

    def _enter(self, p):
        self.precise, self.anchor, self.lp, self.lp_prev, self.still = True, p.copy(), p.copy(), p.copy(), 0.0

    def step(self, t, p, speed, tap, lo, hi):
        cfg = self.cfg
        if self.c is None:
            self.c, self.off, self.lp, self.t = p.copy(), np.zeros_like(p), p.copy(), t
        dt = min(max(t - self.t, 1e-3), 0.1)  # duplicate or late timestamps
        self.t = t
        room = min((p - lo).min(), (hi - p).min())
        self.lp_prev = self.lp
        d = p - self.lp
        n = float(np.linalg.norm(d))
        if n > cfg["rest"]:  # rest latch: ignore tremor, then trail the hand by `rest`
            self.lp = p - d * (cfg["rest"] / n)

        if tap and not self.tapping:  # the palm dipped with the finger: undo it, then hold still
            old = [c for tt, c in self.hist if tt <= t - 0.15]
            self.c = (old[-1] if old else self.hist[0][1] if self.hist else self.c).copy()
            if not self.precise:
                self._enter(p)
        if tap:  # tap is a level signal: hold until tap_hold after the finger stops
            self.hold_until = t + cfg["tap_hold"]
        self.tapping = tap

        if self.precise:
            if speed > cfg["exit_speed"] or room <= cfg["edge"]:
                self.precise, self.off = False, self.c - p  # cursor stays; the glide takes it to the hand
            elif t >= self.hold_until:
                r = float(np.linalg.norm(p - self.anchor))
                gain = cfg["precision"] + (1 - cfg["precision"]) * min(r / cfg["radius"], 1) ** 2
                self.c = self.c + gain * (self.lp - self.lp_prev)
        else:
            self.still = self.still + dt if speed < cfg["enter_speed"] and room > cfg["edge"] else 0.0
            if self.still >= cfg["dwell"]:
                self._enter(p)
            else:
                self.off = self.off * np.exp(-3 * dt / cfg["glide"])
                self.c = p + self.off
        self.c = np.clip(self.c, lo, hi)

        self.hist.append((t, self.c))
        while t - self.hist[0][0] > 0.25:
            self.hist.popleft()
        return self.c
