"""Leap hybrid source: the Leap is the body, MediaPipe the fingers. Synthetic hands, no device."""

import dataclasses

import numpy as np
import pytest

from orion.frame import Finger
from orion.leap_hybrid import Merger, thumb_lateral
from orion.sim import make_hand

CFG = {"max_age": 0.12, "thumb_out": 45}


def rotation(axis, degrees):
    """Rodrigues' rotation matrix."""
    k, a = np.asarray(axis, float) / np.linalg.norm(axis), np.radians(degrees)
    K = np.array(((0, -k[2], k[1]), (k[2], 0, -k[0]), (-k[1], k[0], 0)))
    return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K


def skewed(hand, degrees=20, shift=(50, 0, 0)):
    """The same hand as another tracker would report it: tilted about a slanted axis and offset, as MediaPipe's is."""
    R, move = rotation((1, 0, 1), degrees), np.asarray(shift, np.float32)
    fingers = tuple(Finger(f.name, f.extended, (hand.palm + move + (f.joints - hand.palm) @ R.T).astype(np.float32))
                    for f in hand.fingers)
    return dataclasses.replace(hand, palm=hand.palm + move, stable=hand.stable + move, fingers=fingers,
                               normal=(R @ hand.normal).astype(np.float32), direction=(R @ hand.direction).astype(np.float32))


def with_thumb_lateral(hand, mm):
    """`hand` with its thumb tip `mm` toward the thumb side of the palm (negative: toward the pinky), across the image."""
    axis = hand["index"].joints[1] - hand["pinky"].joints[1]
    axis = np.array((axis[0], 0, axis[2])) / np.hypot(axis[0], axis[2])
    hand["thumb"].joints[-1] = hand.palm + (axis * mm).astype(np.float32)
    return hand


def test_merge_keeps_the_leap_body_and_undoes_the_skew():
    leap = make_hand(velocity=(5, 0, 0), extended={"index", "middle", "ring", "pinky", "thumb"})
    mp = skewed(leap)
    mp.fingers[1].extended = False  # MediaPipe sees the index bent
    mp = dataclasses.replace(mp, pinch=0.7, grab=0.2)
    out = Merger(CFG)(leap, mp, 0.01)
    for field in ("palm", "stable", "velocity", "normal", "direction"):
        assert np.array_equal(getattr(out, field), getattr(leap, field)), field
    assert (out.side, out.id, out.confidence) == (leap.side, leap.id, leap.confidence)
    for got, want in zip(out.fingers, leap.fingers):
        assert np.allclose(got.joints, want.joints, atol=1e-2), got.name  # MediaPipe's shape, in the Leap's frame
    assert {"index"}.isdisjoint(out.extended) and {"middle", "ring", "pinky"} <= out.extended
    assert (out.pinch, out.grab) == (0.7, 0.2)


def test_merge_falls_back_to_the_leap_hand():
    leap, merge = make_hand("right"), Merger(CFG)
    mp = skewed(leap)
    assert merge(leap, None, 0.0) is leap
    assert merge(leap, mp, 0.2) is leap  # older than max_age
    assert merge(leap, dataclasses.replace(mp, side="left"), 0.0) is leap  # another hand


def test_merge_survives_a_degenerate_mediapipe_hand():
    leap = make_hand()
    mp = dataclasses.replace(skewed(leap), direction=np.zeros(3, np.float32), normal=np.zeros(3, np.float32))
    out = Merger(CFG)(leap, mp, 0.0)
    assert all(np.isfinite(f.joints).all() for f in out.fingers)


def test_thumb_rule_has_hysteresis():
    merge, flags = Merger(CFG), []
    for mm in (60, 44, 38, 44, 49):
        leap = make_hand()
        flags.append("thumb" in merge(leap, with_thumb_lateral(make_hand(), mm), 0.0).extended)
    assert flags == [True, True, False, False, True]


def test_thumb_lateral_is_signed():
    assert thumb_lateral(with_thumb_lateral(make_hand(), 40)) == pytest.approx(40, abs=1e-3)
    assert thumb_lateral(with_thumb_lateral(make_hand(), -25)) == pytest.approx(-25, abs=1e-3)
