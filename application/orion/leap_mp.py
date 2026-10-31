"""Leap (MediaPipe) source: MediaPipe Hands on both undistorted Leap IR images, each view checking the other.

The geometry, crop and fusion code is pure numpy; `cv2` and `mediapipe` are imported inside the functions that need them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .webcam import PALM_LM, Cam, Detection, apparent_depth

LEAP_Z_SIGN = 1  # shortcut: image-down → toward the user is a guess, confirmed against Leap's own tracking in the live bring-up
SWAP_CAMERAS = False  # shortcut: assumes stereo_left is the physical left camera, confirmed in the live bring-up
LABEL_FLIP = False  # shortcut: assumes MediaPipe's hand label is right for this view, confirmed in the live bring-up
DEPTH_MM = (60.0, 600.0)  # a hand over the device: nearer or further is a mismatch, not a hand
MIN_AGREEING = 18  # of 21 landmarks need a positive disparity


@dataclass(frozen=True)
class Pinhole:
    """The ideal camera both IR images are rectified to (the Leap's own lens is ~130° wide and distorted)."""
    f: float = 143.0
    w: int = 640
    h: int = 240

    @property
    def cx(self) -> float:
        return self.w / 2

    @property
    def cy(self) -> float:
        return self.h / 2


class Rectifier:
    """Undistorts raw IR images onto a shared pinhole. `project(camera, ray)` gives the raw pixel a ray lands on."""

    def __init__(self, project: Callable[[str, tuple[float, float, float]], tuple[float, float]],
                 pinhole: Pinhole = Pinhole()):
        self.pinhole, self.maps = pinhole, {}
        for camera in ("left", "right"):
            xs = np.empty((pinhole.h, pinhole.w), np.float32)
            ys = np.empty_like(xs)
            for v in range(pinhole.h):
                for u in range(pinhole.w):
                    xs[v, u], ys[v, u] = project(camera, ((u - pinhole.cx) / pinhole.f, (v - pinhole.cy) / pinhole.f, 1.0))
            self.maps[camera] = (xs, ys)

    def rectify(self, camera: str, gray: np.ndarray) -> np.ndarray:
        import cv2
        return cv2.remap(gray, *self.maps[camera], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


@dataclass
class View:
    """One camera's hand: rectified pixels, MediaPipe's hand-centred world shape, and its label and score."""
    px: np.ndarray  # (21, 2)
    world: np.ndarray  # (21, 3) metres, x right, y down, z forward
    label: str
    score: float


def triangulate(left_px: np.ndarray, right_px: np.ndarray, pinhole: Pinhole, baseline: float) -> np.ndarray:
    """(21, 3) mm in the left camera's frame (x right, y down, z forward) from the same landmarks in both rectified images."""
    d = np.maximum(left_px[:, 0] - right_px[:, 0], 1e-6)
    z = pinhole.f * baseline / d
    return np.column_stack(((left_px[:, 0] - pinhole.cx) * z / pinhole.f,
                            ((left_px[:, 1] + right_px[:, 1]) / 2 - pinhole.cy) * z / pinhole.f, z))


def backproject(view: View, pinhole: Pinhole, hand_mm: float) -> np.ndarray:
    """(21, 3) mm in the camera's frame from one view: palm depth from how big the palm looks, shape from MediaPipe."""
    cam = Cam(pinhole.w, pinhole.h, math.degrees(2 * math.atan(pinhole.w / 2 / pinhole.f)), hand_mm)
    norm = view.px / (pinhole.w, pinhole.h)
    z = apparent_depth(Detection(np.column_stack((norm, np.zeros(21))), view.world, view.label, view.score), cam)
    c = view.px[list(PALM_LM)].mean(axis=0)
    palm = np.array(((c[0] - pinhole.cx) * z / pinhole.f, (c[1] - pinhole.cy) * z / pinhole.f, z))
    w = view.world * 1000
    w = w * (hand_mm / (float(np.linalg.norm(w[9] - w[0])) or 1.0))
    return palm + w - w[list(PALM_LM)].mean(axis=0)


def to_leap_axes(points: np.ndarray, baseline: float) -> np.ndarray:
    """Left-camera frame → Leap axes (origin between the cameras, y away from the device, z toward the user)."""
    return np.column_stack((points[:, 0] - baseline / 2, points[:, 2], LEAP_Z_SIGN * points[:, 1]))


def agreement(left_px: np.ndarray, right_px: np.ndarray, pinhole: Pinhole, baseline: float, agree_px: float) -> bool:
    """Whether two rectified views can be the same hand: same rows, a positive disparity, a plausible depth."""
    if float(np.median(np.abs(left_px[:, 1] - right_px[:, 1]))) >= agree_px:
        return False
    d = left_px[:, 0] - right_px[:, 0]
    if int((d > 0).sum()) < MIN_AGREEING:
        return False
    return DEPTH_MM[0] <= float(np.median(pinhole.f * baseline / d[d > 0])) <= DEPTH_MM[1]


# ── Finding a hand in one camera ──────────────────────────────────────────────

CROP_SCALE = 1.6  # tracking window = this × the hand's bounding-box side (about 2.5× the palm)
CROP_MIN = 96  # px; MediaPipe's palm detector needs the hand at a usable size
LOST_AFTER = 3  # consecutive misses before searching the whole frame again
CROP_INPUT = 256  # px; what MediaPipe is given


def search_windows(w: int, h: int) -> list[tuple[int, int, int]]:
    """Square `(x0, y0, side)` windows that together cover a wide, short frame: tried one per frame while no hand is tracked."""
    side = min(w, h)
    return [(round(x), 0, side) for x in np.linspace(0, w - side, 3)]


def crop_around(center: tuple[float, float], side: float, w: int, h: int) -> tuple[int, int, int]:
    """Square window of about `side` px centred on `center`, kept inside the frame."""
    s = round(min(max(side, CROP_MIN), min(w, h)))
    return (int(min(max(round(center[0] - s / 2), 0), w - s)), int(min(max(round(center[1] - s / 2), 0), h - s)), s)


class HandFinder:
    """One camera's hand: searches the frame window by window, then follows the hand with a tight crop.

    `backend(crop)` returns `[(landmarks (21, 2) in 0..1 of the crop, world (21, 3), label, score)]`."""

    def __init__(self, backend, pinhole: Pinhole = Pinhole(), min_score: float = 0.5):
        self.backend, self.pinhole, self.min_score = backend, pinhole, min_score
        self.center = self.side = None
        self.misses = self.searched = 0

    def find(self, gray: np.ndarray) -> View | None:
        h, w = gray.shape[:2]
        if self.center is None:
            x0, y0, s = search_windows(w, h)[self.searched % 3]
            self.searched += 1
        else:
            x0, y0, s = crop_around(self.center, CROP_SCALE * self.side, w, h)
        found = [r for r in self.backend(gray[y0:y0 + s, x0:x0 + s]) if r[3] >= self.min_score]
        if not found:
            self.misses += 1
            if self.center is not None and self.misses >= LOST_AFTER:
                self.center, self.searched = None, 0
            return None
        norm, world, label, score = max(found, key=lambda r: r[3])
        px = np.column_stack((x0 + norm[:, 0] * s, y0 + norm[:, 1] * s))
        self.center, self.side, self.misses = px[list(PALM_LM)].mean(axis=0), float(np.ptp(px, axis=0).max()), 0
        return View(px, world, label, score)


def mediapipe_backend():
    """The real backend for `HandFinder`: one single-image MediaPipe hand landmarker, crops upscaled to 256 px."""
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as tasks
    from mediapipe.tasks.python import vision

    from .webcam import ensure_model
    landmarker = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=tasks.BaseOptions(model_asset_path=str(ensure_model())),
        running_mode=vision.RunningMode.IMAGE, num_hands=1))

    def backend(crop):
        rgb = cv2.cvtColor(cv2.resize(crop, (CROP_INPUT, CROP_INPUT)), cv2.COLOR_GRAY2RGB)
        r = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        return [(np.array([(p.x, p.y) for p in img]), np.array([(p.x, p.y, p.z) for p in world]),
                 cats[0].category_name.lower(), cats[0].score)
                for img, world, cats in zip(r.hand_landmarks, r.hand_world_landmarks, r.handedness)]
    return backend
