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
