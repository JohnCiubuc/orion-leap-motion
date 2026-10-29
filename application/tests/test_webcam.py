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
