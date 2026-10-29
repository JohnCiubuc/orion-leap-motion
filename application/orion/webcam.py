"""Webcam frame source: MediaPipe hand landmarks → Orion's Hand model (Leap axes, millimetres).

`landmarks_to_hand` is pure geometry; `import orion.webcam` needs neither OpenCV nor MediaPipe.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

import numpy as np

from .frame import FINGERS, Finger, Hand

PALM_LM = (0, 5, 9, 13, 17)  # wrist + the four knuckles: the palm's centre is their mean
NOMINAL_DISTANCE = 400.0  # mm from the camera that maps to leap z = 0
PALM_HEIGHT = 200.0  # mm added to y so the hand sits where the Leap would see it
DEPTH_RANGE = (100.0, 2000.0)  # mm; keeps a tiny or huge apparent hand size from producing absurd positions
DEBOUNCE = 2  # frames a finger must hold a new state before it flips
HOLD = 0.08  # s a missed hand is repeated, so one lost detection doesn't read as the hand leaving
MIN_CUTOFF, BETA, D_CUTOFF, DEPTH_CUTOFF = 1.5, 0.02, 1.0, 0.4  # shortcut: One-Euro settings guessed from synthetic jitter, retune on a real hand
MATCH_DISTANCE = 0.25  # normalised image distance within which a detection continues a track
EXTEND_ON, EXTEND_OFF = 0.80, 0.65  # shortcut: finger straightness cut-offs picked from synthetic hands, retune on a real hand


@dataclass
class Cam:
    width: int = 640
    height: int = 480
    fov_deg: float = 70  # horizontal
    hand_mm: float = 95  # wrist → middle-knuckle


@dataclass
class Detection:
    image: np.ndarray  # (21, 3) normalised x, y (0..1, y down)
    world: np.ndarray  # (21, 3) metres, hand-centred, y down, z away from the camera
    label: str  # "left" | "right" (the user's real hand: frames are mirrored before detection)
    score: float


def _extended(straightness: float, was: bool) -> bool:
    """Between the two cut-offs a finger keeps its previous state, so it doesn't flicker."""
    if straightness >= EXTEND_ON:
        return True
    return was and straightness >= EXTEND_OFF


def _straightness(pts: np.ndarray) -> float:
    """Chord over path length of a finger's four landmarks: 1 when straight, lower as it curls."""
    path = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
    return float(np.linalg.norm(pts[-1] - pts[0])) / path if path > 1e-6 else 0.0


def _focal(cam: Cam) -> float:
    return (cam.width / 2) / math.tan(math.radians(cam.fov_deg) / 2)


def apparent_depth(det: Detection, cam: Cam) -> float:
    """Distance from the camera in mm, from how large the hand looks."""
    px = det.image[:, :2] * (cam.width, cam.height)
    size = max(float(np.linalg.norm(px[9] - px[0])), 1.0)
    return min(max(_focal(cam) * cam.hand_mm / size, DEPTH_RANGE[0]), DEPTH_RANGE[1])


def landmarks_to_hand(det: Detection, cam: Cam, prev_extended: frozenset[str] = frozenset(), hid: int = 0,
                      depth: float | None = None) -> Hand:
    """`depth` overrides the distance estimate (the tracker passes a smoothed one)."""
    f = _focal(cam)
    px = det.image[:, :2] * (cam.width, cam.height)
    z = apparent_depth(det, cam) if depth is None else depth
    c = px[list(PALM_LM)].mean(axis=0)
    palm = np.array(((c[0] - cam.width / 2) * z / f,
                     -(c[1] - cam.height / 2) * z / f + PALM_HEIGHT,
                     z - NOMINAL_DISTANCE), np.float32)
    w = det.world * (1000, -1000, 1000)  # hand shape in real mm, y up
    w = w - w[list(PALM_LM)].mean(axis=0) + palm
    fingers = []
    for k, name in enumerate(FINGERS):
        pts = w[4 * k + 1:4 * k + 5]
        joints = np.vstack((w[0], pts)).astype(np.float32)
        fingers.append(Finger(name, _extended(_straightness(pts), name in prev_extended), joints))
    return Hand(hid, det.label, det.score, 0.0, 0.0, palm, palm.copy(), np.zeros(3, np.float32),
                np.array((0, -1, 0), np.float32), np.array((0, 0, -1), np.float32), tuple(fingers))


def _alpha(cutoff, dt):
    return 1 / (1 + 1 / (2 * math.pi * cutoff * dt))


class OneEuro:
    """Low-pass filter that smooths hard while the signal is still and lightly while it moves.
    `dx` is the smoothed rate of change, in units per second."""

    def __init__(self, min_cutoff=MIN_CUTOFF, beta=BETA):
        self.min_cutoff, self.beta = min_cutoff, beta
        self.t = self.x = self.raw = self.dx = None

    def __call__(self, t: float, x: np.ndarray) -> np.ndarray:
        if self.x is None:
            self.t, self.raw, self.dx = t, x, np.zeros(x.shape)
            self.x = x.astype(np.float64)
            return self.x
        dt = max(t - self.t, 1e-3)
        self.dx = self.dx + _alpha(D_CUTOFF, dt) * ((x - self.raw) / dt - self.dx)
        self.x = self.x + _alpha(self.min_cutoff + self.beta * np.abs(self.dx), dt) * (x - self.x)
        self.t, self.raw = t, x
        return self.x


class _Track:
    def __init__(self, hid):
        self.id, self.filter, self.depth, self.extended, self.flip = hid, OneEuro(), OneEuro(DEPTH_CUTOFF, 0.0), frozenset(), dict.fromkeys(FINGERS, 0)
        self.hand, self.seen, self.at = None, 0.0, np.zeros(2)


class HandTracker:
    """Turns each frame's detections into steady `Hand`s: stable ids, debounced fingers, smoothed positions,
    velocity, and a short hold over missed detections. Call `update` once per captured frame."""

    def __init__(self, cam: Cam):
        self.cam, self.tracks, self.next_id = cam, [], 1

    def update(self, t: float, dets: list[Detection]) -> tuple[Hand, ...]:
        free, hands = list(self.tracks), []
        for det in dets:
            at = det.image[list(PALM_LM), :2].mean(axis=0)
            near = min(free, key=lambda tr: np.linalg.norm(tr.at - at), default=None)
            if near is None or np.linalg.norm(near.at - at) > MATCH_DISTANCE:
                near = _Track(self.next_id)
                self.next_id += 1
                self.tracks.append(near)
            else:
                free.remove(near)
            near.at, near.seen = at, t
            depth = float(near.depth(t, np.array(apparent_depth(det, self.cam))))  # distance is the noisiest estimate: smooth it hardest
            near.hand = self._smooth(t, near, landmarks_to_hand(det, self.cam, near.extended, near.id, depth))
            hands.append(near.hand)
        for tr in free:  # not seen this frame
            if t - tr.seen <= HOLD:
                hands.append(tr.hand)
            else:
                self.tracks.remove(tr)
        return tuple(hands)

    def _smooth(self, t, tr, raw: Hand) -> Hand:
        for f in raw.fingers:  # a finger flips only after DEBOUNCE frames in the new state
            tr.flip[f.name] = tr.flip[f.name] + 1 if f.extended != (f.name in tr.extended) else 0
            if tr.flip[f.name] >= DEBOUNCE:
                tr.extended, tr.flip[f.name] = tr.extended ^ {f.name}, 0
        v = tr.filter(t, np.concatenate((raw.palm, np.stack([f.joints for f in raw.fingers]).ravel())))
        palm = v[:3].astype(np.float32)
        fingers = tuple(Finger(f.name, f.name in tr.extended, v[3 + 15 * k:18 + 15 * k].reshape(5, 3).astype(np.float32))
                        for k, f in enumerate(raw.fingers))
        return dataclasses.replace(raw, palm=palm, stable=palm.copy(), velocity=tr.filter.dx[:3].astype(np.float32),
                                   fingers=fingers)
