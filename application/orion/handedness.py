"""Steady left/right labels.

The tracker guesses a new hand's side from its first, often partial frames and can call a
left hand "right" before correcting itself. Each hand id starts as the preferred side (or the
side not already in view) and only takes the tracker's label once it has said so confidently
for CONFIRM seconds in a row, half that if the hand came in from that side. After that the side
is fixed for as long as the id stays tracked.
"""

from __future__ import annotations

import dataclasses

from .frame import Frame

OTHER = {"left": "right", "right": "left"}
CONFIRM = 0.4  # s
MIN_CONFIDENCE = 0.3  # shortcut: unverified against the Gemini service's real confidence values, tune if a lone right hand never settles
EDGE = 60  # mm from centre that counts as entering from a side


class Handedness:
    def __init__(self, config):
        self.cfg = config
        self.tracks = {}  # hand id → [side, entry x, (claim, since) | None, settled]

    def __call__(self, frame: Frame) -> Frame:
        self.tracks = {k: v for k, v in self.tracks.items() if any(h.id == k for h in frame.hands)}
        for h in sorted(frame.hands, key=lambda h: h.palm[0]):  # left to right, so a new pair splits by position
            taken = {tr[0] for k, tr in self.tracks.items() if k != h.id}
            if h.id not in self.tracks:
                pref = self.cfg.general["preferred_hand"]
                if taken:
                    side = OTHER[next(iter(taken))]
                elif len(frame.hands) > 1:
                    side = "left"
                else:
                    side = pref if pref in OTHER else h.side  # "none" → trust the tracker's first guess
                self.tracks[h.id] = [side, float(h.palm[0]), None, bool(taken)]
            tr = self.tracks[h.id]
            if tr[3]:
                continue
            if h.confidence < MIN_CONFIDENCE or h.side in taken:  # unsure, or would make two hands the same side
                tr[2] = None
                continue
            if tr[2] is None or tr[2][0] != h.side:
                tr[2] = (h.side, frame.t)
            came_from = "left" if tr[1] < -EDGE else "right" if tr[1] > EDGE else None
            if frame.t - tr[2][1] >= CONFIRM * (0.5 if came_from == h.side else 1):
                tr[0], tr[3] = h.side, True
        if all(self.tracks[h.id][0] == h.side for h in frame.hands):
            return frame
        return dataclasses.replace(frame, hands=tuple(dataclasses.replace(h, side=self.tracks[h.id][0]) for h in frame.hands))
