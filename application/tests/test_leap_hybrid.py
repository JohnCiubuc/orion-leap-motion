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


# ── The source ────────────────────────────────────────────────────────────────

import time  # noqa: E402
from types import SimpleNamespace as NS  # noqa: E402

from orion.leap_hybrid import LeapHybridSource  # noqa: E402
from test_leap_mp import CFG as MP_CFG, PAIR, FakeFinder, FakeRectifier, scene, views  # noqa: E402


def leap_hand(hid, side, x=0.0):
    """A Leap tracking-event hand with every finger reported extended."""
    v = lambda a, b, c: NS(x=a, y=b, z=c)  # noqa: E731
    bone = NS(prev_joint=v(x, 200, 0), next_joint=v(x, 210, 0))
    palm = NS(position=v(x, 200, 0), stabilized_position=v(x, 200, 0), velocity=v(0, 0, 0), normal=v(0, -1, 0), direction=v(0, 0, -1))
    return NS(id=hid, type=f"HandType.{side.title()}", confidence=0.9, pinch_strength=0.0, grab_strength=0.0, palm=palm,
              digits=[NS(is_extended=True, bones=[bone] * 4)] * 5)


def leap_event(*hands):
    return NS(timestamp=2_000_000, framerate=110.0, hands=list(hands))


def make_hybrid(finders=None):
    frames = []
    finders = finders or [FakeFinder(), FakeFinder()]
    src = LeapHybridSource(frames.append, lambda img: None, cfg={**MP_CFG, "min_score": 0.5}, hybrid=CFG,
                           rectifier_factory=lambda conn: FakeRectifier(), finder_factory=iter(finders).__next__)
    return src, frames, finders


def test_hybrid_emits_one_merged_frame_per_leap_event():
    src, frames, _ = make_hybrid()
    bent_index = dataclasses.replace(make_hand("left", extended={"middle", "ring", "pinky", "thumb"}))
    src._emit(time.monotonic(), (bent_index,))  # what the MediaPipe worker publishes
    src._tracking(leap_event(leap_hand(7, "left")))
    frame = frames[0]
    assert frame.source == "leap_hybrid" and frame.t == 2.0 and frame.leap.hands[0].extended >= {"index"}
    assert "index" not in frame.hands[0].extended and frame.hands[0].id == 7  # MediaPipe's flags on the Leap's hand
    assert src.status["fingers"] == "mediapipe"


def test_hybrid_without_mediapipe_is_the_leap():
    src, frames, _ = make_hybrid()
    src._tracking(leap_event(leap_hand(7, "left")))
    assert all(a is b for a, b in zip(frames[0].hands, frames[0].leap.hands)) and src.status["fingers"] == "leap"


def test_hybrid_merges_only_the_matching_hand():
    src, frames, _ = make_hybrid()
    src._emit(time.monotonic(), (make_hand("left"),))
    src._tracking(leap_event(leap_hand(7, "left"), leap_hand(8, "right", x=100)))
    assert frames[0].hands[0] is not frames[0].leap.hands[0] and frames[0].hands[1] is frames[0].leap.hands[1]


def test_hybrid_survives_a_merge_error(monkeypatch):
    src, frames, _ = make_hybrid()
    src._emit(time.monotonic(), (make_hand("left"),))
    monkeypatch.setattr(Merger, "__call__", lambda self, *a: 1 / 0)
    src._tracking(leap_event(leap_hand(7, "left")))
    assert all(a is b for a, b in zip(frames[0].hands, frames[0].leap.hands)) and src.status["fingers"] == "leap"


def test_hybrid_worker_publishes_instead_of_emitting_frames():
    src, frames, (left, right) = make_hybrid()
    assert src._setup()
    left.view, right.view = views(scene())
    src._process(PAIR, 0.0)
    assert frames == [] and src._latest[1] is not None


# ── Config and engine ─────────────────────────────────────────────────────────

def test_leap_hybrid_defaults_load(tmp_path):
    from orion.config import Config
    path = tmp_path / "config.toml"
    path.write_text("[leap_hybrid]\nmax_age = 0.2\n")
    assert Config(path)["leap_hybrid"] == {"max_age": 0.2, "thumb_out": 45}


def test_engine_starts_the_leap_hybrid_source(tmp_path, monkeypatch):
    from orion.actions import hyprland
    from orion.config import Config
    from orion.engine import Engine
    from orion.sources import Source
    monkeypatch.setattr(Source, "start", lambda self: None)  # no device threads in a unit test
    monkeypatch.setattr(hyprland, "watch_active_window", lambda fn: None)
    path = tmp_path / "config.toml"
    path.write_text('[general]\nsource = "leap_hybrid"\n')
    engine = Engine(Config(path), dry_run=True)
    engine.start()
    assert isinstance(engine.source, LeapHybridSource)
    assert engine.source.cfg["cameras"] == "left" and engine.source.merger.cfg["thumb_out"] == 45


def test_merge_ignores_a_mediapipe_hand_facing_the_other_way():
    # A flipped palm normal would turn the rotation into a 180° flip and mirror the fingers through the palm.
    leap = make_hand()
    mp = dataclasses.replace(skewed(leap), normal=-skewed(leap).normal)
    assert Merger(CFG)(leap, mp, 0.0) is leap
