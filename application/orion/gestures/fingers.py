"""Fingertip motion relative to the palm, shared by the air mouse and the desktop pointer."""

from collections import deque

import numpy as np


class FingerMotion:
    """Flags a tap: a fingertip moved `trigger` mm against the palm within `window` s while the palm was resting.
    One instance per hand side."""

    def __init__(self, window=0.12, hand_max=250.0):
        self.window, self.hand_max = window, hand_max  # window: per-frame speed is mostly noise, so judge over time
        self.hist = deque()  # (t, fingertips rel. palm, palm speed)

    def reset(self):
        self.hist.clear()

    def update(self, t, tips_rel_palm, speed, trigger, still):
        self.hist.append((t, tips_rel_palm, speed))
        while t - self.hist[0][0] > self.window:
            self.hist.popleft()
        if speed > self.hand_max:  # a deliberate sweep, not a tap
            return False
        _, then, then_speed = self.hist[0]
        moved = float(np.max(np.linalg.norm(tips_rel_palm - then, axis=1)))
        return moved >= trigger and then_speed < still
