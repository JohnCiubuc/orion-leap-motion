"""Leap (MediaPipe) source: rectification, stereo geometry, crops, fusion and the source worker, on synthetic data."""

import numpy as np
import pytest

from orion.leap_mp import LEAP_Z_SIGN, Pinhole, Rectifier, View, agreement, backproject, to_leap_axes, triangulate
from orion.webcam import PALM_LM


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


# ── Stereo geometry ───────────────────────────────────────────────────────────

PIN, BASELINE = Pinhole(), 40.0


def scene(z=200.0, flat=False, seed=1):
    """21 camera-frame points (mm; x right, y down, z forward) standing in for a hand."""
    rng = np.random.default_rng(seed)
    pts = np.column_stack((rng.uniform(-50, 50, 21), rng.uniform(-30, 30, 21), np.full(21, z) + (0 if flat else rng.uniform(-5, 5, 21))))
    return pts


def project_pair(pts, pin=PIN, baseline=BASELINE):
    """Rectified pixels of `pts` in the left and right camera (the right one sits `baseline` mm to the right)."""
    left = np.column_stack((pin.cx + pin.f * pts[:, 0] / pts[:, 2], pin.cy + pin.f * pts[:, 1] / pts[:, 2]))
    right = np.column_stack((pin.cx + pin.f * (pts[:, 0] - baseline) / pts[:, 2], left[:, 1]))
    return left, right


def test_triangulate_round_trip():
    pts = scene()
    assert np.abs(triangulate(*project_pair(pts), PIN, BASELINE) - pts).max() < 0.5


def test_backproject_recovers_a_flat_hand():
    pts = scene(flat=True)
    view = View(project_pair(pts)[0], (pts - pts[list(PALM_LM)].mean(axis=0)) / 1000, "right", 0.9)
    got = backproject(view, PIN, hand_mm=float(np.linalg.norm(pts[9] - pts[0])))
    assert np.abs(got - pts).max() < 3


def test_to_leap_axes():
    got = to_leap_axes(np.array([[10.0, 5.0, 200.0]]), 40.0)
    assert got[0] == pytest.approx([-10, 200, 5 * LEAP_Z_SIGN])


def test_agreement():
    left, right = project_pair(scene())
    assert agreement(left, right, PIN, BASELINE, 4.0)
    assert not agreement(left, right + (0, 10), PIN, BASELINE, 4.0)  # rows disagree
    assert not agreement(right, left, PIN, BASELINE, 4.0)  # swapped: negative disparity
    assert not agreement(*project_pair(scene(z=700)), PIN, BASELINE, 4.0)  # too far to be a hand over the device
