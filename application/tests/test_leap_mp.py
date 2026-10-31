"""Leap (MediaPipe) source: rectification, stereo geometry, crops, fusion and the source worker, on synthetic data."""

import numpy as np
import pytest

from orion.leap_mp import LEAP_Z_SIGN, Fusion, HandFinder, LeapMediaPipeSource, Pinhole, Rectifier, View, agreement, backproject, crop_around, preview, search_windows, to_leap_axes, triangulate
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


# ── Fusion ────────────────────────────────────────────────────────────────────

CFG = {"agree_px": 4.0, "hold": 0.08, "hand_mm": 95}


def views(pts):
    """What the two finders would report for camera-frame points `pts`."""
    world = (pts - pts[list(PALM_LM)].mean(axis=0)) / 1000
    left, right = project_pair(pts)
    return View(left, world, "right", 0.9), View(right, world, "right", 0.8)


def expected_palm(pts):
    return to_leap_axes(pts, BASELINE)[list(PALM_LM)].mean(axis=0)


def test_fusion_agree_gives_a_metric_palm():
    pts = scene()
    (hand,), status = Fusion(CFG).update(0.0, *views(pts))
    assert status == "agree" and hand.palm == pytest.approx(expected_palm(pts), abs=2)


def test_fusion_one_camera_still_gives_a_hand():
    pts = scene(flat=True)
    left, right = views(pts)
    cfg = {**CFG, "hand_mm": float(np.linalg.norm(pts[9] - pts[0]))}  # hand_mm is the user's real wrist-to-knuckle length
    for lv, rv, want in ((None, right, "right only"), (left, None, "left only")):
        (hand,), status = Fusion(cfg).update(0.0, lv, rv)
        assert status == want
        assert hand.palm == pytest.approx(expected_palm(pts), abs=15)  # a view alone is only as good as its size estimate; a right-only view must still be shifted into the left camera's frame


def test_fusion_disagree_holds_then_drops_then_recovers():
    pts = scene()
    fusion = Fusion(CFG)
    (good,), _ = fusion.update(0.0, *views(pts))
    left, right = views(pts)
    right.px = right.px + (0, 10)  # the two cameras no longer see the same hand
    held, status = fusion.update(0.05, left, right)
    assert status == "disagree" and held == (good,)
    assert fusion.update(0.2, left, right) == ((), "disagree")
    assert fusion.update(0.3, None, None) == ((), "none")
    (again,), status = fusion.update(0.4, *views(pts))
    assert status == "agree" and again.id == 1


# ── The source ────────────────────────────────────────────────────────────────

class FakeRectifier:
    def rectify(self, camera, gray):
        return gray


class FakeFinder:
    def __init__(self, view=None):
        self.view, self.boom = view, False

    def find(self, gray):
        if self.boom:
            raise RuntimeError("detector blew up")
        return self.view


def make_source(finders=None):
    frames, images = [], []
    finders = finders or [FakeFinder(), FakeFinder()]
    src = LeapMediaPipeSource(frames.append, images.append, cfg={**CFG, "min_score": 0.5},
                              rectifier_factory=lambda conn: FakeRectifier(), finder_factory=iter(finders).__next__)
    return src, frames, images, finders


PAIR = (np.zeros((240, 640), np.uint8), np.zeros((240, 640), np.uint8))


def test_process_emits_a_frame_per_pair_even_without_a_hand():
    src, frames, _, (left, right) = make_source()
    left.view, right.view = views(scene())
    src._process(PAIR, 0.0)
    assert len(frames[0].hands) == 1 and frames[0].source == "leap_mp" and src.status["agreement"] == "agree"
    left.view = right.view = None
    src._process(PAIR, 0.5)
    assert frames[1].hands == () and src.status["agreement"] == "none"


def test_process_survives_a_detector_exception():
    src, frames, _, (left, right) = make_source()
    left.boom = True
    src._process(PAIR, 0.0)  # must not raise
    assert len(frames) == 1 and frames[0].hands == ()
    left.boom = False
    left.view, right.view = views(scene())
    src._process(PAIR, 0.1)
    assert len(frames[1].hands) == 1


def test_offer_keeps_only_the_newest_pair():
    src = make_source()[0]
    older, newer = (PAIR[0].copy(), PAIR[1].copy()), (PAIR[0].copy(), PAIR[1].copy())
    src._offer(older)
    src._offer(newer)
    assert src._slot is newer and src._dropped == 1


def test_missing_dependencies_set_a_readable_error():
    frames, calls = [], []

    def no_mediapipe():
        calls.append(1)
        raise ImportError("No module named 'mediapipe'")
    src = LeapMediaPipeSource(frames.append, lambda img: None, cfg=CFG, rectifier_factory=lambda conn: FakeRectifier(),
                              finder_factory=no_mediapipe)
    src._process(PAIR, 0.0)
    src._process(PAIR, 0.1)
    assert "webcam" in src.status["error"] and len(frames) == 2 and len(calls) == 1  # empty frames, and no retry of a missing library


def test_preview_draws_dots_without_touching_the_inputs():
    left, right = PAIR[0].copy(), PAIR[1].copy()
    view = View(np.full((21, 2), (100.0, 50.0)), np.zeros((21, 3)), "right", 0.9)
    img = preview(left, right, view, None)
    stacked = np.frombuffer(img.pixels, np.uint8).reshape(480, 640)
    assert (img.width, img.height) == (640, 480) and stacked[50, 100] == 255 and stacked[240 + 50, 100] == 0
    assert not left.any() and not right.any()


# ── Config and engine ─────────────────────────────────────────────────────────

def test_leap_mp_defaults_load(tmp_path):
    from orion.config import Config
    path = tmp_path / "config.toml"
    path.write_text("[leap_mp]\nagree_px = 6.0\n")
    cfg = Config(path)
    assert cfg["leap_mp"] == {"agree_px": 6.0, "hold": 0.08, "hand_mm": 95, "min_score": 0.5}


def test_engine_starts_the_leap_mp_source(tmp_path, monkeypatch):
    from orion.actions import hyprland
    from orion.config import Config
    from orion.engine import Engine
    from orion.sources import Source
    monkeypatch.setattr(Source, "start", lambda self: None)  # no device threads in a unit test
    monkeypatch.setattr(hyprland, "watch_active_window", lambda fn: None)
    path = tmp_path / "config.toml"
    path.write_text('[general]\nsource = "leap_mp"\n')
    engine = Engine(Config(path), dry_run=True)
    engine.start()
    assert isinstance(engine.source, LeapMediaPipeSource) and engine.source.cfg["agree_px"] == 4.0


def test_stop_waits_for_the_worker():
    src = make_source()[0]
    src._on_open(None)
    worker = src._worker
    assert worker.is_alive()
    src.stop()
    assert not worker.is_alive()  # a detection must not still be running when the app (or the interpreter) goes away
