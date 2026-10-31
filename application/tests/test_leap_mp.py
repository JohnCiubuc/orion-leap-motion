"""Leap (MediaPipe) source: rectification, stereo geometry, crops, fusion and the source worker, on synthetic data."""

import numpy as np
import pytest

from orion.leap_mp import LEAP_Z_SIGN, HandFinder, Pinhole, Rectifier, View, agreement, backproject, crop_around, search_windows, to_leap_axes, triangulate
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


# ── Crops and the per-camera hand finder ──────────────────────────────────────

def test_search_windows_cover_the_frame():
    assert search_windows(640, 240) == [(0, 0, 240), (200, 0, 240), (400, 0, 240)]


def test_crop_around_stays_inside_the_frame():
    x0, y0, s = crop_around((630, 10), 200, 640, 240)
    assert (s, x0 + s <= 640, y0 >= 0, y0 + s <= 240) == (200, True, True, True)
    assert crop_around((320, 120), 10, 640, 240)[2] == 96  # never smaller than MediaPipe can use
    assert crop_around((320, 120), 900, 640, 240)[2] == 240  # nor taller than the frame


def hand_at_centre(score=0.9):
    return (np.full((21, 2), 0.5), np.zeros((21, 3)), "right", score)


def scripted(answers):
    """A backend that answers from a list and records (crop's first pixel, crop side) per call."""
    calls = []

    def backend(crop):
        calls.append((float(crop[0, 0]), crop.shape[0]))
        return answers[len(calls) - 1]
    return backend, calls


def test_finder_searches_then_tracks_then_gives_up():
    gray = np.tile(np.arange(640, dtype=np.float32), (240, 1))  # pixel value = its column, so a crop's first pixel is its x0
    backend, calls = scripted([[], [], [hand_at_centre()], [hand_at_centre()], [], [], [], []])
    finder = HandFinder(backend)
    views = [finder.find(gray) for _ in range(8)]
    assert [c[0] for c in calls[:3]] == [0, 200, 400] and calls[0][1] == 240  # one search window per frame
    assert views[0] is None and views[1] is None
    assert views[2].px.mean(axis=0) == pytest.approx((520, 120))  # crop coordinates mapped back to the frame
    assert calls[3] == (472.0, 96)  # tracking: a small window centred on the hand
    assert calls[7][0] == 0  # three misses in a row: back to searching from the first window


def test_finder_ignores_low_scores():
    backend, _ = scripted([[hand_at_centre(score=0.3)]])
    assert HandFinder(backend).find(np.zeros((240, 640), np.uint8)) is None


def test_mediapipe_backend_finds_nothing_in_a_blank_crop():
    pytest.importorskip("mediapipe")
    from orion.leap_mp import mediapipe_backend
    from orion.webcam import MODEL_FILE
    if not MODEL_FILE.exists():
        pytest.skip("hand model not downloaded yet")
    assert mediapipe_backend()(np.zeros((240, 240), np.uint8)) == []
