"""Webcam frame source: MediaPipe hand landmarks → Orion's Hand model (Leap axes, millimetres).

`landmarks_to_hand` is pure geometry; `import orion.webcam` needs neither OpenCV nor MediaPipe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .frame import FINGERS, Finger, Hand

PALM_LM = (0, 5, 9, 13, 17)  # wrist + the four knuckles: the palm's centre is their mean
NOMINAL_DISTANCE = 400.0  # mm from the camera that maps to leap z = 0
PALM_HEIGHT = 200.0  # mm added to y so the hand sits where the Leap would see it
DEPTH_RANGE = (100.0, 2000.0)  # mm; keeps a tiny or huge apparent hand size from producing absurd positions
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


def landmarks_to_hand(det: Detection, cam: Cam, prev_extended: frozenset[str] = frozenset(), hid: int = 0) -> Hand:
    f = (cam.width / 2) / math.tan(math.radians(cam.fov_deg) / 2)
    px = det.image[:, :2] * (cam.width, cam.height)
    size = max(float(np.linalg.norm(px[9] - px[0])), 1.0)
    z = min(max(f * cam.hand_mm / size, DEPTH_RANGE[0]), DEPTH_RANGE[1])  # apparent size → distance
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
