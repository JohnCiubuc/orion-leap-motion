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
