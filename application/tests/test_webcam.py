"""Webcam source: landmark conversion and hand tracking, on synthetic hands projected through a pinhole camera."""

import math

import numpy as np
import pytest

from orion.frame import FINGERS
from orion.sim import make_hand
from orion.webcam import Cam, Detection, _extended, landmarks_to_hand

CAM = Cam(hand_mm=64)  # make_hand's wrist → middle-knuckle is 64 mm
PALM_LM = (0, 5, 9, 13, 17)
FOUR = {"index", "middle", "ring", "pinky"}


def facing(extended=FINGERS, palm=(0, 200, 0), **kw):
    """A hand held up with the palm toward the camera (fingers up, normal toward -z)."""
    return make_hand(palm=palm, extended=extended, direction=(0, 1, 0), normal=(0, 0, -1), **kw)


def landmarks(hand):
    """MediaPipe layout: 0 wrist, then 4 per finger (thumb, index, middle, ring, pinky)."""
    pts = [hand["middle"].joints[0]]
    for f in hand.fingers:
        pts.extend(f.joints[1:])
    return np.array(pts, np.float64)


def palm_of(hand):
    return landmarks(hand)[list(PALM_LM)].mean(axis=0)


def project(hand, cam=CAM, distance=400.0):
    """Inverse of landmarks_to_hand: leap-space hand → what MediaPipe would report for it."""
    lm = landmarks(hand)
    f = (cam.width / 2) / math.tan(math.radians(cam.fov_deg) / 2)
    depth = distance + lm[:, 2]
    u = cam.width / 2 + f * lm[:, 0] / depth
    v = cam.height / 2 - f * (lm[:, 1] - 200) / depth
    image = np.stack((u / cam.width, v / cam.height, np.zeros(21)), axis=1)
    world = (lm - lm[list(PALM_LM)].mean(axis=0)) * (1, -1, 1) / 1000
    return Detection(image, world, hand.side, 0.9)


def test_axes():
    a = landmarks_to_hand(project(facing(extended={"index", "middle"})), CAM)
    b = landmarks_to_hand(project(facing(extended={"index", "middle"}, palm=(30, 230, 0))), CAM)
    d = (b["index"].tip - a["index"].tip)[:2]
    assert d == pytest.approx([30, 30], abs=2)  # right and up are positive


@pytest.mark.parametrize("ext", [{"index", "middle"}, set(), set(FINGERS)])
def test_round_trip_poses(ext):
    h = facing(extended=ext)
    out = landmarks_to_hand(project(h), CAM)
    assert out.extended & FOUR == h.extended & FOUR
    assert out.palm == pytest.approx(palm_of(h), abs=3)


def test_depth_from_size():
    near = landmarks_to_hand(project(facing(), distance=300), CAM)
    far = landmarks_to_hand(project(facing(), distance=500), CAM)
    assert far.palm[2] - near.palm[2] == pytest.approx(200, abs=5)


def test_degenerate_size_is_finite():
    det = Detection(np.full((21, 3), 0.5), np.zeros((21, 3)), "right", 0.9)
    hand = landmarks_to_hand(det, CAM)
    assert np.isfinite(hand.palm).all() and all(np.isfinite(f.joints).all() for f in hand.fingers)


def test_extended_hysteresis():
    assert _extended(0.72, True) and not _extended(0.72, False)
    assert _extended(0.9, False) and not _extended(0.6, True)


# ── HandTracker ───────────────────────────────────────────────────────────────

import dataclasses  # noqa: E402

from orion.webcam import HandTracker  # noqa: E402

DT = 1 / 30


def noisy(det, rng, world_mm=1.0, px=1.0):
    return dataclasses.replace(
        det, image=det.image + rng.normal(0, px / 640, det.image.shape) * (1, 640 / 480, 0),
        world=det.world + rng.normal(0, world_mm / 1000, det.world.shape))


def test_ids_survive_label_flicker():
    tr, det = HandTracker(CAM), project(facing(extended={"index", "middle"}))
    ids = {tr.update(i * DT, [dataclasses.replace(det, label="left" if i % 2 else "right")])[0].id for i in range(30)}
    assert len(ids) == 1


def test_finger_debounce():
    tr = HandTracker(CAM)
    closed, opened = project(facing(extended={"index", "middle"})), project(facing(extended={"index", "middle", "ring"}))
    for i in range(5):
        tr.update(i * DT, [closed])
    assert "ring" not in tr.update(5 * DT, [opened])[0].extended  # one frame is not enough
    assert "ring" in tr.update(6 * DT, [opened])[0].extended  # two consecutive are


def test_one_frame_dropout_repeats_hand():
    tr, det = HandTracker(CAM), project(facing())
    first = tr.update(0, [det])[0]
    assert tr.update(DT, [])[0].id == first.id and tr.update(2 * DT, [])[0].id == first.id
    assert tr.update(0.2, []) == ()


def test_jitter_is_quiet():
    tr, rng, det = HandTracker(CAM), np.random.default_rng(1), project(facing(extended={"index", "middle"}))
    rel, speed = [], []
    for i in range(90):
        h = tr.update(i * DT, [noisy(det, rng)])[0]
        if i >= 30:
            rel.append(np.linalg.norm(h["index"].tip - h.palm))
            speed.append(np.linalg.norm(h.velocity))
    assert np.std(rel) < 1.0 and max(speed) < 20


def test_velocity_tracks_motion():
    tr = HandTracker(CAM)
    for i in range(31):
        h = tr.update(i * DT, [project(facing(palm=(100 * i * DT, 200, 0)))])[0]
    assert h.velocity[0] == pytest.approx(100, rel=0.15)


# ── OrionDo on webcam frames ──────────────────────────────────────────────────

from orion.frame import Frame  # noqa: E402
from orion.gestures import REGISTRY, load_builtins  # noqa: E402

load_builtins()


class Rig:
    """Webcam frames (30 fps) into an OrionDo gesture; `show(hand_or_None, seconds)` returns the events."""

    def __init__(self, rng=None):
        self.g = REGISTRY["oriondo"]({"items": [{"label": str(i), "action": "input.keys", "args": {"combo": str(i)}}
                                                 for i in range(4)]})
        self.tr, self.t, self.rng = HandTracker(CAM), 0.0, rng

    def show(self, hand, seconds):
        out = []
        for _ in range(round(seconds * 30)):
            dets = [project(hand)] if hand else []
            if dets and self.rng is not None:
                dets = [noisy(dets[0], self.rng)]
            out += list(self.g.update(Frame(t=self.t, hands=self.tr.update(self.t, dets), source="webcam")))
            self.t += DT
        return out


def peace(y=200):
    return facing(extended={"index", "middle"}, palm=(0, y, 0))


def key(evs):
    return [(e.phase, e.value) for e in evs if e.phase != "update"]


def test_oriondo_opens_on_peace_via_webcam():
    assert [e.phase for e in Rig().show(peace(), 0.6) if e.phase != "update"] == ["begin"]


def test_oriondo_hovers_and_fires():
    r = Rig()
    r.show(peace(), 0.6)
    evs = r.show(peace(220), 0.5)  # 20 mm up: past the deadzone, short of the pull
    assert key(evs) == [] and [e.value["hover"] for e in evs if e.phase == "update"][-1] == 0
    evs = r.show(peace(250), 0.5)
    fire = [v for p, v in key(evs) if p == "fire"]
    assert len(fire) == 1 and fire[0]["index"] == 0


def test_oriondo_no_tap_close_from_jitter():
    r = Rig(np.random.default_rng(3))
    r.show(peace(), 0.6)
    assert key(r.show(peace(), 3.0)) == []


def test_oriondo_survives_a_short_dropout():
    r = Rig()
    r.show(peace(), 0.6)
    r.show(peace(220), 0.5)
    r.show(None, 2 * DT)  # two missed detections
    assert [p for p, _ in key(r.show(peace(250), 0.5))] == ["fire", "end"]  # measured from the original centre


def test_oriondo_closes_when_hand_leaves():
    r = Rig()
    r.show(peace(), 0.6)
    assert key(r.show(None, 1.7)) == [("end", "lost")]


# ── WebcamSource ──────────────────────────────────────────────────────────────

import threading  # noqa: E402
import time  # noqa: E402

from orion.config import DEFAULT_FILE  # noqa: E402
from orion.webcam import WebcamSource, ensure_model, find_cameras  # noqa: E402
import tomllib  # noqa: E402

WEBCAM_CFG = tomllib.loads(DEFAULT_FILE.read_text())["webcam"]


class FakeCapture:
    def __init__(self, good=10**9):
        self.good, self.released = good, False  # reads that succeed before the camera stalls

    def read(self):
        time.sleep(0.005)
        self.good -= 1
        return self.good >= 0, np.zeros((480, 640, 3), np.uint8)

    def release(self):
        self.released = True


def run_source(detect=None, capture=None, cameras=None, cfg=None, seconds=0.3, **kw):
    frames, images = [], []
    src = WebcamSource(frames.append, images.append, cfg=cfg or WEBCAM_CFG,
                       capture_factory=lambda path, cfg: capture or FakeCapture(),
                       detector_factory=(lambda: detect) if detect else None,
                       cameras=[{"path": "/dev/video2", "name": "Cam"}] if cameras is None else cameras, **kw)
    src.ir = True
    t = threading.Thread(target=src.run, daemon=True)
    t.start()
    time.sleep(seconds)
    src.stop()
    t.join(2)
    return src, frames, images


def test_find_cameras_lists_capture_nodes_only(tmp_path):
    for n, (name, idx) in {"video3": ("Cam", 1), "video10": ("Other", 0), "video2": ("Cam", 0)}.items():
        d = tmp_path / n
        d.mkdir()
        (d / "name").write_text(name + "\n")
        (d / "index").write_text(f"{idx}\n")
    assert find_cameras(tmp_path) == [{"path": "/dev/video2", "name": "Cam"}, {"path": "/dev/video10", "name": "Other"}]


def test_source_emits_empty_frames_without_hands():
    src, frames, _ = run_source(detect=lambda rgb, t: [])
    assert len(frames) > 5 and all(f.hands == () and f.source == "webcam" for f in frames)
    assert src.status["connected"] and src.status["device"] == "Cam" and src.status["error"] == ""


def test_source_emits_hands_and_preview():
    det = project(facing(extended={"index", "middle"}))
    src, frames, images = run_source(detect=lambda rgb, t: [det])
    with_hand = [f for f in frames if f.hands]
    assert with_hand and len(with_hand[-1].hands) == 1 and "index" in with_hand[-1].hands[0].extended
    # the UI's IR view shows a stereo pair stacked vertically: the mono preview is sent twice
    assert images and images[0].width == 320 and images[0].height == 480
    assert len(images[0].pixels) == images[0].width * images[0].height


def test_source_reports_missing_camera():
    src, frames, _ = run_source(detect=lambda rgb, t: [], cameras=[])
    assert "No webcam" in src.status["error"] and not src.status["connected"] and frames == []


def test_source_reports_missing_mediapipe():
    def boom():
        raise ImportError("No module named 'mediapipe'")

    frames = []
    src = WebcamSource(frames.append, lambda i: None, cfg=WEBCAM_CFG, capture_factory=lambda p, c: FakeCapture(),
                       detector_factory=boom, cameras=[{"path": "/dev/video2", "name": "Cam"}])
    src.run()  # returns instead of raising
    assert 'pip install -e ".[webcam]"' in src.status["error"] and frames == []


def test_source_keeps_emitting_when_the_camera_stalls():
    src, frames, _ = run_source(detect=lambda rgb, t: [], capture=FakeCapture(good=3), seconds=0.5)
    assert len(frames) >= 5 and all(f.hands == () for f in frames) and not src.status["connected"]


def test_chosen_device_is_used(monkeypatch):
    opened = []
    frames = []
    src = WebcamSource(frames.append, lambda i: None, cfg={**WEBCAM_CFG, "device": "/dev/video7"},
                       capture_factory=lambda p, c: opened.append(p) or FakeCapture(), detector_factory=lambda: (lambda r, t: []),
                       cameras=[{"path": "/dev/video2", "name": "Cam"}])
    threading.Timer(0.1, src.stop).start()
    src.run()
    assert opened == ["/dev/video7"]


def test_ensure_model_downloads_once_and_leaves_no_partial_file(tmp_path):
    src = tmp_path / "src.task"
    src.write_bytes(b"model")
    target = tmp_path / "cache" / "m.task"
    assert ensure_model(target, src.as_uri()).read_bytes() == b"model"
    src.unlink()
    assert ensure_model(target, src.as_uri()) == target  # cached: the missing source is never touched
    bad = tmp_path / "cache" / "n.task"
    with pytest.raises(RuntimeError):
        ensure_model(bad, (tmp_path / "missing").as_uri())
    assert not bad.exists() and not list((tmp_path / "cache").glob("*.tmp"))


# ── Milestone 2: the other Hand fields and poses ─────────────────────────────

def pinched(hand):
    hand.fingers[0].joints[-1] = hand["index"].tip.copy()  # thumb tip on the index tip
    return hand


def convert(hand):
    return landmarks_to_hand(project(hand), CAM)


def test_pinch_and_grab():
    assert convert(pinched(facing(extended={"middle", "ring", "pinky"}))).pinch > 0.85
    assert convert(facing()).pinch < 0.3
    assert convert(facing(extended=set())).grab > 0.9 and convert(facing()).grab < 0.2


@pytest.mark.parametrize("side", ["right", "left"])
def test_normal_and_direction(side):
    h = convert(facing(side=side))
    assert h.normal == pytest.approx((0, 0, -1), abs=0.1) and h.direction == pytest.approx((0, 1, 0), abs=0.1)


WEBCAM_POSES = {
    "thumbs_up": lambda: facing(extended={"thumb"}, thumb=(0, 1, 0)),
    "thumbs_down": lambda: facing(extended={"thumb"}, thumb=(0, -1, 0)),
    "ok": lambda: pinched(facing(extended={"middle", "ring", "pinky"})),
    "fist": lambda: facing(extended=set()),
    "open_palm": lambda: facing(),
    "peace": lambda: facing(extended={"index", "middle"}),
    "pinch": lambda: pinched(facing(extended={"middle", "ring", "pinky"})),
    "engage": lambda: facing(),
}


@pytest.mark.parametrize("name", WEBCAM_POSES)
def test_pose_detected_from_webcam_frames(name):
    tr, g, seen = HandTracker(CAM), REGISTRY[name](), []
    for i in range(45):
        t = i * DT
        seen += [(e.name, e.phase) for e in g.update(Frame(t=t, hands=tr.update(t, [project(WEBCAM_POSES[name]())]), source="webcam"))]
    assert (name, "begin") in seen


# ── Review fixes ──────────────────────────────────────────────────────────────

def test_tilted_hand_off_centre_keeps_its_position():
    """Pitching the hand toward the camera shortens wrist→knuckle in the image; depth must not read it as distance."""
    h = make_hand(palm=(150, 250, 0), extended={"index", "middle"}, direction=(0, 0.866, -0.5),
                  normal=(0, -0.5, -0.866))  # 30° toward the camera
    assert convert(h).palm[:2] == pytest.approx(palm_of(h)[:2], abs=6)  # measured over a 30° tilt: 14 mm off before the fix


def test_source_survives_a_detector_error_and_closes_up():
    det = project(facing(extended={"index", "middle"}))
    calls = []

    def detect(rgb, t_ms):
        calls.append(t_ms)
        if len(calls) == 3:
            raise RuntimeError("mediapipe hiccup")
        return [det]

    src, frames, _ = run_source(detect=detect, seconds=0.4)
    assert len(frames) > 10 and src.status["error"] == ""  # kept going after the error
    assert frames[-1].hands == ()  # and ended with an empty frame so an open menu can close


def test_detector_timestamps_strictly_increase(monkeypatch):
    import types
    monkeypatch.setattr("orion.webcam.time", types.SimpleNamespace(monotonic=lambda: 1.0))
    stamps = []
    run_source(detect=lambda rgb, t: stamps.append(t) or [], seconds=0.15)
    assert len(stamps) > 3 and all(b > a for a, b in zip(stamps, stamps[1:]))


# ── Real-hand findings: swapped hands, upright hand ──────────────────────────

def test_labels_are_swapped_because_the_image_is_mirrored():
    det = project(facing(side="right", extended={"index", "middle"}))  # MediaPipe called this hand "right"
    _, frames, _ = run_source(detect=lambda rgb, t: [det])
    assert {h.side for f in frames for h in f.hands} == {"left"}
    _, frames, _ = run_source(detect=lambda rgb, t: [det], cfg={**WEBCAM_CFG, "mirror": False})
    assert {h.side for f in frames for h in f.hands} == {"right"}


UPRIGHT = Cam(hand_mm=64, tilt_deg=90)


def test_upright_hand_becomes_a_flat_hand_but_keeps_its_position():
    h = facing(extended={"index", "middle"}, palm=(40, 230, 0))
    flat, upright = landmarks_to_hand(project(h), UPRIGHT), convert(h)
    assert flat.normal == pytest.approx((0, -1, 0), abs=0.1) and flat.direction == pytest.approx((0, 0, -1), abs=0.1)
    assert flat.palm == pytest.approx(upright.palm, abs=0.01)  # moving the hand up still moves it up
    assert flat["middle"].tip[2] < flat.palm[2] - 80  # fingers now point away from the user
    assert flat.extended == upright.extended


def test_oriondo_steers_with_an_upright_hand():
    r = Rig()
    r.tr = HandTracker(UPRIGHT)
    r.show(peace(), 0.6)
    evs = r.show(peace(220), 0.5)
    assert [e.value["hover"] for e in evs if e.phase == "update"][-1] == 0
    assert [p for p, _ in key(r.show(peace(250), 0.5))] == ["fire", "end"]
