"""Leap (MediaPipe) source: MediaPipe Hands on both undistorted Leap IR images, each view checking the other.

The geometry, crop and fusion code is pure numpy; `cv2` and `mediapipe` are imported inside the functions that need them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


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
