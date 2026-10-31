"""Leap (MediaPipe) source: rectification, stereo geometry, crops, fusion and the source worker, on synthetic data."""

import numpy as np
import pytest

from orion.leap_mp import Pinhole, Rectifier


# ── Rectifier ─────────────────────────────────────────────────────────────────

def barrel(camera, ray, f=40.0, k=0.15):
    """A fake lens: barrel distortion about (80, 30), and the right camera sits 3 px lower."""
    x, y = ray[0] / ray[2], ray[1] / ray[2]
    r2 = x * x + y * y
    return 80 + f * x * (1 + k * r2), 30 + f * y * (1 + k * r2) + (3 if camera == "right" else 0)


def blob(at, shape=(60, 160), sigma=1.2):
    yy, xx = np.mgrid[:shape[0], :shape[1]]
    return np.exp(-((xx - at[0]) ** 2 + (yy - at[1]) ** 2) / (2 * sigma ** 2)).astype(np.float32)


def centroid(img):
    yy, xx = np.mgrid[:img.shape[0], :img.shape[1]]
    return float((img * xx).sum() / img.sum()), float((img * yy).sum() / img.sum())


def test_rectifier_undoes_distortion_and_camera_offset():
    pytest.importorskip("cv2")
    pin = Pinhole(f=40, w=160, h=60)
    rect = Rectifier(barrel, pin)
    for camera in ("left", "right"):
        raw = blob(barrel(camera, (0.5, -0.3, 1)))
        x, y = centroid(rect.rectify(camera, raw))
        assert (x, y) == pytest.approx((pin.cx + pin.f * 0.5, pin.cy + pin.f * -0.3), abs=0.5)
