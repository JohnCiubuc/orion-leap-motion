"""Leap (MediaPipe) source: rectification, stereo geometry, crops, fusion and the source worker, on synthetic data."""

import numpy as np
import pytest

from orion.leap_mp import Fusion, planar_pinch, HandFinder, LeapMediaPipeSource, Pinhole, Rectifier, View, agreement, backproject, crop_around, preview, search_windows, to_leap_axes, triangulate
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
    """Rectified pixels of `pts` (camera-frame mm of the first camera) in the first camera and in the second, which sits
    `baseline` mm further along image x. On the Leap the first is the right camera: image x runs toward Leap -x."""
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


def test_triangulate_survives_a_bad_landmark():
    pts = scene()
    left, right = project_pair(pts)
    right[3, 0] = left[3, 0] - 0.001  # one landmark the cameras barely disagree on in x: a depth of millions of mm
    assert agreement(left, right, PIN, BASELINE, 4.0)
    got = triangulate(left, right, PIN, BASELINE)
    good = np.delete(np.arange(21), 3)
    assert np.isfinite(got).all() and np.abs(got[good] - pts[good]).max() < 0.5
    assert abs(got[3, 2] - np.median(pts[good, 2])) < 1  # the bad one sits at the hand's depth, along its own ray


def test_to_leap_axes():
    # image x runs toward Leap -x, y (down in the image) toward the user, z is the height above the device
    point = np.array([[10.0, 5.0, 200.0]])
    assert to_leap_axes(point, cam_x=20.0)[0] == pytest.approx([10, 200, 5])  # camera at the Leap's +x side
    assert to_leap_axes(point, cam_x=-20.0)[0] == pytest.approx([-30, 200, 5])


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
    backend = mediapipe_backend("cpu")
    try:
        assert backend(np.zeros((240, 240), np.uint8)) == []
    finally:
        backend.close()


# ── Fusion ────────────────────────────────────────────────────────────────────

CFG = {"agree_px": 4.0, "hold": 0.08, "hand_mm": 95, "cameras": "both", "delegate": "cpu"}


def views(pts):
    """What the two finders would report for camera-frame points `pts`."""
    world = (pts - pts[list(PALM_LM)].mean(axis=0)) / 1000
    first, second = project_pair(pts)  # the Leap's right camera, then its left
    return View(second, world, "right", 0.9), View(first, world, "right", 0.8)


def expected_palm(pts):
    return to_leap_axes(pts, BASELINE / 2)[list(PALM_LM)].mean(axis=0)  # `pts` are in the right camera's frame, at Leap x = +20


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
        self.view, self.boom, self.calls = view, False, 0

    def find(self, gray):
        self.calls += 1
        if self.boom:
            raise RuntimeError("detector blew up")
        return self.view


def make_source(finders=None, cameras="both"):
    frames, images = [], []
    finders = finders or [FakeFinder(), FakeFinder()]
    src = LeapMediaPipeSource(frames.append, images.append, cfg={**CFG, "min_score": 0.5, "cameras": cameras},
                              rectifier_factory=lambda conn: FakeRectifier(), finder_factory=iter(finders).__next__)
    assert src._setup()  # a ready source; the real one does this off the frame path
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
    src._setup_thread.join(2)
    src._process(PAIR, 0.1)
    assert "webcam" in src.status["error"] and len(frames) == 2 and len(calls) == 1  # empty frames, and no retry of a missing library


def test_failed_setup_is_not_retried_every_frame():
    frames, calls = [], []

    def broken(conn):
        calls.append(1)
        raise RuntimeError("calibration not ready")
    src = LeapMediaPipeSource(frames.append, lambda img: None, cfg=CFG, rectifier_factory=broken,
                              finder_factory=lambda: FakeFinder())
    src._process(PAIR, 0.0)
    src._setup_thread.join(2)
    for i in range(5):
        src._process(PAIR, 0.1 * i)
    assert len(calls) == 1 and len(frames) == 6 and "calibration" in src.status["error"]


def test_slow_setup_does_not_stop_the_frames():
    import threading
    started, release = threading.Event(), threading.Event()

    def slow(conn):
        started.set()
        release.wait(5)
        return FakeRectifier()
    frames = []
    src = LeapMediaPipeSource(frames.append, lambda img: None, cfg=CFG, rectifier_factory=slow, finder_factory=lambda: FakeFinder())
    src._process(PAIR, 0.0)  # returns while setup is still blocked: the watchdog needs frames
    assert started.wait(2) and len(frames) == 1 and frames[0].hands == ()
    release.set()
    src._setup_thread.join(2)
    assert src._fusion is not None


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
    assert cfg["leap_mp"] == {"agree_px": 6.0, "hold": 0.08, "hand_mm": 95, "min_score": 0.5, "cameras": "left", "delegate": "gpu"}


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


def test_left_only_mode_never_touches_the_right_camera():
    class Counting(FakeRectifier):
        def __init__(self):
            self.cameras = []

        def rectify(self, camera, gray):
            self.cameras.append(camera)
            return gray
    rect, frames, finders = Counting(), [], [FakeFinder(), FakeFinder()]
    src = LeapMediaPipeSource(frames.append, lambda img: None, cfg={**CFG, "min_score": 0.5, "cameras": "left"},
                              rectifier_factory=lambda conn: rect, finder_factory=iter(finders).__next__)
    assert src._setup()
    finders[0].view, finders[1].view = views(scene(flat=True))
    src._process(PAIR, 0.0)
    assert len(frames[0].hands) == 1 and src.status["agreement"] == "left only"
    assert rect.cameras == ["left"] and finders[0].calls == 1 and finders[1].calls == 0  # the right image is never rectified or searched


# ── MediaPipe delegate: GPU first, CPU if the GPU cannot be used ──────────────

def _model_or_skip():
    pytest.importorskip("mediapipe")
    from orion.webcam import MODEL_FILE
    if not MODEL_FILE.exists():
        pytest.skip("hand model not downloaded yet")


def _on_gpu(options):
    from mediapipe.tasks import python as tasks
    return options.base_options.delegate == tasks.BaseOptions.Delegate.GPU


def test_backend_falls_back_to_cpu_when_the_gpu_cannot_start(monkeypatch):
    _model_or_skip()
    from mediapipe.tasks.python import vision
    from orion.leap_mp import mediapipe_backend
    real = vision.HandLandmarker.create_from_options

    def refuse_gpu(options):
        if _on_gpu(options):
            raise RuntimeError("no GL context")
        return real(options)
    monkeypatch.setattr(vision.HandLandmarker, "create_from_options", refuse_gpu)
    backend = mediapipe_backend("gpu")
    try:
        assert backend.delegate == "cpu" and backend(np.zeros((240, 240), np.uint8)) == []
    finally:
        backend.close()


def test_backend_falls_back_to_cpu_when_the_gpu_fails_on_a_frame(monkeypatch):
    _model_or_skip()
    from mediapipe.tasks.python import vision
    from orion.leap_mp import mediapipe_backend
    real = vision.HandLandmarker.create_from_options

    class Broken:
        def detect(self, image):
            raise RuntimeError("GL context lost")
    monkeypatch.setattr(vision.HandLandmarker, "create_from_options", lambda o: Broken() if _on_gpu(o) else real(o))
    backend = mediapipe_backend("gpu")
    try:
        assert backend.delegate == "gpu"
        assert backend(np.zeros((240, 240), np.uint8)) == [] and backend.delegate == "cpu"  # retried on the CPU, and stays there
    finally:
        backend.close()


def test_stop_closes_the_backends():
    class Backend:
        closed = 0

        def close(self):
            self.closed += 1
    backends = [Backend(), Backend()]
    finders = [FakeFinder(), FakeFinder()]
    for finder, backend in zip(finders, backends):
        finder.backend = backend
    src = make_source(finders)[0]
    src.stop()
    assert [b.closed for b in backends] == [1, 1]  # a GPU landmarker holds GL resources until closed


def test_planar_pinch_ignores_depth():
    w = np.zeros((21, 3))
    w[4], w[8] = (10, 50, 5), (10, -40, 5)  # thumb and index tips on top of each other in the image, 90 mm apart in depth (y)
    assert planar_pinch(w) == 1.0
    w[8] = (10 + 60, -40, 5)  # now 60 mm apart in the image
    assert planar_pinch(w) == 0.0


def test_planar_pinch_is_not_a_fist_or_a_thumbs_up():
    w = np.zeros((21, 3))
    w[4], w[8] = (10, 0, 5), (10, 0, 6)  # tips together in the image
    assert planar_pinch(w, grab=0.14) == 1.0  # an OK sign: the other fingers are open
    assert planar_pinch(w, grab=0.7) == 0.0  # a thumbs up or a fist: the thumb just rests against the curled index


def test_fusion_pinch_follows_the_image_not_the_depth(monkeypatch):
    monkeypatch.setattr("orion.leap_mp.PINCH_MAX_GRAB", 2.0)  # the random scatter of points is not an open hand; the grab gate has its own test
    pts = scene(flat=True)
    left, _ = views(pts)
    left.world = left.world.copy()
    left.world[8] = left.world[4] + (0, 0, 0.05)  # index tip 50 mm behind the thumb tip, same place in the image
    (hand,), _ = Fusion({**CFG, "hand_mm": float(np.linalg.norm(pts[9] - pts[0]))}).update(0.0, left, None)
    assert hand.pinch > 0.9


def test_fusion_hand_side_survives_a_few_flipped_labels():
    pts = scene(flat=True)
    cfg = {**CFG, "hand_mm": float(np.linalg.norm(pts[9] - pts[0]))}
    fusion, sides = Fusion(cfg), []

    def feed(t, label):
        left, _ = views(pts)
        left.label = label
        sides.append(fusion.update(t, left, None)[0][0].side)
    for i in range(20):
        feed(i * 0.01, "left")
    for i in range(3):  # MediaPipe briefly guesses the other hand
        feed(0.2 + i * 0.01, "right")
    assert set(sides) == {"left"}
    for i in range(20):  # but a real change of hand does get through
        feed(0.3 + i * 0.01, "right")
    assert sides[-1] == "right"
