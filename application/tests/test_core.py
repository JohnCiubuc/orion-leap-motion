"""Gesture recognition, routing and config round-trips — all on synthetic hands, no device needed."""

import math
import os
import tempfile

import numpy as np
import pytest

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()  # never touch the real config

from orion.actions import ACTIONS, Action, load_builtins as load_actions  # noqa: E402
from orion.config import Config  # noqa: E402
from orion.frame import Frame, from_dict, pack_skeleton, to_dict  # noqa: E402
from orion.gestures import REGISTRY, GestureEvent, load_builtins  # noqa: E402
from orion.gestures.paths import PathGesture, _resample  # noqa: E402
from orion.router import Router  # noqa: E402
from orion.sim import make_hand  # noqa: E402

load_builtins()
load_actions()


def run(gesture, frames):
    return [(e.name, e.phase) for f in frames for e in gesture.update(f)]


def hold(hand, seconds=1.2, fps=100):
    return [Frame(t=i / fps, hands=(hand,)) for i in range(int(seconds * fps))]


# ── Poses ─────────────────────────────────────────────────────────────────────

POSES = {
    "thumbs_up": make_hand(extended={"thumb"}, normal=(-1, 0, 0), thumb=(0, 1, 0)),
    "thumbs_down": make_hand(extended={"thumb"}, normal=(-1, 0, 0), thumb=(0, -1, 0)),
    "ok": make_hand(extended={"middle", "ring", "pinky"}, pinch=0.95),
    "fist": make_hand(extended=set()),
    "open_palm": make_hand(),
    "peace": make_hand(extended={"index", "middle"}),
}


@pytest.mark.parametrize("name", POSES)
def test_pose_detected(name):
    assert (name, "begin") in run(REGISTRY[name](), hold(POSES[name]))


def test_pose_not_confused():
    assert run(REGISTRY["thumbs_up"](), hold(POSES["thumbs_down"])) == []
    assert run(REGISTRY["fist"](), hold(POSES["open_palm"])) == []


def test_pose_hold_and_end():
    g = REGISTRY["thumbs_up"]({"hold": 0.5})
    assert run(g, hold(POSES["thumbs_up"], 0.3)) == []  # not held long enough
    frames = hold(POSES["thumbs_up"], 1.0) + [Frame(t=1.5 + i / 100, hands=()) for i in range(30)]
    assert run(REGISTRY["thumbs_up"](), frames) == [("thumbs_up", "begin"), ("thumbs_up", "end")]


# ── Motions ───────────────────────────────────────────────────────────────────

def test_swipes():
    for (dx, dy), want in {(12, 0): "right", (-12, 0): "left", (0, 12): "up", (0, -12): "down"}.items():
        frames = [Frame(t=i / 100, hands=(make_hand(palm=(i * dx, 200 + i * dy, 0)),)) for i in range(25)]
        assert run(REGISTRY["swipe"](), frames) == [(f"swipe.{want}", "fire")]


def test_slow_move_is_not_a_swipe():
    frames = [Frame(t=i / 100, hands=(make_hand(palm=(i * 1.0, 200, 0)),)) for i in range(100)]
    assert run(REGISTRY["swipe"](), frames) == []


def test_palm_flip():
    frames = [Frame(t=i / 100, hands=(make_hand(normal=(0, -1 + 2 * min(i, 40) / 40, 0.01)),)) for i in range(60)]
    assert run(REGISTRY["palm_flip"](), frames) == [("palm_flip.up", "fire")]


def test_tap():
    frames = []
    for i in range(30):
        h = make_hand(extended={"index"})
        h.fingers[1].joints[-1][1] -= 20 * math.sin(min(i, 10) / 10 * math.pi)
        frames.append(Frame(t=i / 100, hands=(h,)))
    assert run(REGISTRY["tap"](), frames) == [("tap", "fire")]


# ── Paths ($P) ────────────────────────────────────────────────────────────────

def poly(*c):
    return _resample(np.array(c, float), 90) * 120


SHAPES = {
    "circle": [(math.cos(a) * 60, math.sin(a) * 60) for a in np.linspace(0.5, 0.5 + 2 * math.pi, 90)],
    "square": poly((1, 1), (0, 1), (0, 0), (1, 0), (1, 1)),
    "triangle": poly((0.5, .87), (0, 0), (1, 0), (0.5, .87)),
    "z": poly((0, 1), (1, 1), (0, 0), (1, 0)),
}


def draw(pts):
    frames = [Frame(t=i / 100, hands=(make_hand(palm=(x, 200 + y, 0), extended={"index"}),)) for i, (x, y) in enumerate(pts)]
    return frames + [Frame(t=len(pts) / 100, hands=(make_hand(),))]  # open hand ends the stroke


@pytest.mark.parametrize("shape", SHAPES)
def test_shapes_recognised_with_noise(shape):
    noisy = np.array(SHAPES[shape]) + np.random.default_rng(0).normal(0, 2, (90, 2))
    assert run(PathGesture(), draw(noisy)) == [(f"path.{shape}", "fire")]


def test_scribble_rejected():
    assert run(PathGesture(), draw(np.cumsum(np.random.default_rng(1).normal(0, 15, (90, 2)), 0))) == []


# ── Continuous ────────────────────────────────────────────────────────────────

def test_zoom_ratio():
    pair = lambda s: (make_hand("left", (-s, 200, 0), pinch=.9), make_hand("right", (s, 200, 0), pinch=.9))  # noqa
    g = REGISTRY["zoom"]()
    evs = [e for i, s in enumerate((50, 75, 100)) for e in g.update(Frame(t=i, hands=pair(s)))]
    assert [e.phase for e in evs] == ["begin", "update", "update"]
    pinch_gap = lambda s: np.linalg.norm(np.subtract(*[(h["thumb"].tip + h["index"].tip) / 2 for h in pair(s)]))  # noqa
    assert evs[-1].value == pytest.approx(pinch_gap(100) / pinch_gap(50))


# ── Router ────────────────────────────────────────────────────────────────────

@pytest.fixture
def router():
    calls = []
    ACTIONS["t.once"] = Action("t.once", lambda ev: None, {})
    ACTIONS["t.stream"] = Action("t.stream", lambda ev: None, {}, continuous=True)
    cfg = Config()
    cfg.data.update(profiles={"zen": {"match": "^zen"}}, modes={"m": {"exclusive": True}}, bindings=[
        {"gesture": "swipe.left", "action": "t.once"},
        {"gesture": "swipe.left", "action": "t.stream", "profile": "zen"},
        {"gesture": "zoom", "action": "t.stream"},
        {"gesture": "fist", "action": "t.once", "mode": "m"},
    ])
    r = Router(cfg, lambda act, ev, args: calls.append((act.name, ev.phase)))
    r.calls = calls
    return r


def ev(name, phase="fire", t=1.0):
    return GestureEvent(name, phase, None, "right", t)


def test_profile_overrides_default(router):
    router.route(ev("swipe.left"))
    router.window = "zen"
    router.route(ev("swipe.left"))
    assert router.calls == [("t.once", "fire"), ("t.stream", "fire")]


def test_continuous_phases_and_exclusive_mode(router):
    for p in ("begin", "update", "end"):
        router.route(ev("zoom", p))
    router.modes.add("m")
    router.route(ev("swipe.left"))  # silenced by the exclusive mode
    router.route(ev("fist", "begin"))
    assert router.calls == [("t.stream", "begin"), ("t.stream", "update"), ("t.stream", "end"), ("t.once", "begin")]


def test_engage_gate(router):
    router.engage_required = True
    router.route(ev("swipe.left", t=1))  # blocked
    router.route(ev("engage", "begin", t=2))
    router.route(ev("swipe.left", t=3))  # armed → passes, consumes
    router.route(ev("swipe.left", t=3.5))  # blocked again
    assert router.calls == [("t.once", "fire")]


# ── Data round-trips ──────────────────────────────────────────────────────────

def test_frame_roundtrip_and_pack():
    f = Frame(t=1.5, fps=110, hands=(make_hand(), make_hand("left")))
    g = from_dict(to_dict(f))
    assert np.allclose(g.hands[0].fingers[2].joints, f.hands[0].fingers[2].joints)
    assert len(pack_skeleton(f)) == 1 + 12 + 2 * 86 * 4


def test_config_save_keeps_comments():
    cfg = Config()
    cfg.data["general"]["ir_fps"] = 15
    cfg.save()
    text = cfg.path.read_text()
    assert "ir_fps = 15" in text and "# Orion Renewal configuration" in text


def test_from_leap_with_fake_structs():
    from types import SimpleNamespace as NS
    from orion.frame import from_leap
    v = lambda x, y, z: NS(x=x, y=y, z=z)  # noqa: E731
    bone = NS(prev_joint=v(0, 0, 0), next_joint=v(0, 10, 0))
    digit = NS(is_extended=True, bones=[bone] * 4)
    palm = NS(position=v(1, 2, 3), stabilized_position=v(1, 2, 3), velocity=v(0, 0, 0),
              normal=v(0, -1, 0), direction=v(0, 0, -1))
    hand = NS(id=7, type="HandType.Left", confidence=.8, pinch_strength=.1, grab_strength=.2, palm=palm, digits=[digit] * 5)
    f = from_leap(NS(timestamp=2_000_000, framerate=110.0, hands=[hand]))
    assert f.t == 2.0 and f.hands[0].side == "left" and f.hands[0].extended == frozenset(
        ("thumb", "index", "middle", "ring", "pinky")) and f.hands[0]["index"].joints.shape == (5, 3)


# ── Controller recovery ───────────────────────────────────────────────────────

def test_find_leap_on_usb(tmp_path):
    from orion.device import find_devices
    for name, vid, pid, bus, dev in (("1-2", "f182", "0003", 1, 7), ("1-3", "046d", "c52b", 1, 8), ("1-2:1.0", "", "", 0, 0)):
        d = tmp_path / name
        d.mkdir()
        if vid:
            for k, v in dict(idVendor=vid, idProduct=pid, busnum=bus, devnum=dev).items():
                (d / k).write_text(f"{v}\n")
    assert [str(p) for p in find_devices(tmp_path)] == ["/dev/bus/usb/001/007"]


def test_watchdog_restarts_sleeping_controller(monkeypatch):
    import time
    from orion.engine import Engine
    from orion.sources import LeapSource
    e = Engine(Config())
    e.source = LeapSource(lambda f: None, lambda i: None)
    e.source.status["connected"] = True
    calls = []
    monkeypatch.setattr(e, "restart_device", lambda **kw: calls.append(kw))
    e.last_frame = e.last_restart = time.monotonic() - 100  # silent for 100 s
    e.watchdog()
    assert len(calls) == 1
    e.cfg.general["auto_wake"] = 0  # off
    e.watchdog()
    assert len(calls) == 1


# ── Joystick + pointer ────────────────────────────────────────────────────────

def joy_frames(dy, seconds=1.0, pinch=0.95):
    """Pinch at y=200, then hold `dy` mm above/below for `seconds`, then release."""
    fr = [Frame(t=0.0, hands=(make_hand(palm=(0, 200, 0), pinch=pinch),))]
    fr += [Frame(t=0.01 + i / 100, hands=(make_hand(palm=(0, 200 + dy, 0), pinch=pinch),)) for i in range(int(seconds * 100))]
    return fr + [Frame(t=seconds + 0.1, hands=(make_hand(palm=(0, 200 + dy, 0), pinch=0.1),))]


def test_joystick_ratchets_by_distance_not_time():
    fires = lambda fr: [n for n, ph in run(REGISTRY["pinch_joy"]({"axis": "vertical", "step": 20}), fr) if ph == "fire"]  # noqa
    assert fires(joy_frames(10)) == []  # less than one step
    assert fires(joy_frames(30, seconds=3)) == ["pinch_joy.up"]  # held still far away: fires once, no repeats
    assert fires(joy_frames(-45)) == ["pinch_joy.down"]  # one jump = one event, then measured from there
    sweep = [Frame(t=i / 100, hands=(make_hand(palm=(0, 200 + i, 0), pinch=.95),)) for i in range(71)]
    assert fires(sweep) == ["pinch_joy.up"] * 3  # 70 mm in 20 mm steps
    back = sweep + [Frame(t=1 + i / 100, hands=(make_hand(palm=(0, 270 - i, 0), pinch=.95),)) for i in range(61)]
    assert fires(back)[3:] == ["pinch_joy.down"] * 2  # from the last step point (260): 240, 220
    phases = [ph for _, ph in run(REGISTRY["pinch_joy"](), joy_frames(30))]
    assert phases[0] == "begin" and phases[-1] == "end"


def test_grab_joystick_ignores_thumbs_up():
    thumbs = make_hand(extended={"thumb"}, normal=(-1, 0, 0), thumb=(0, 1, 0), grab=0.95)
    assert run(REGISTRY["grab_joy"](), hold(thumbs)) == []


def test_engage_covers_a_whole_joystick_hold(router):
    ACTIONS["t.once"] = Action("t.once", lambda ev: None, {})
    router.bindings.append({"gesture": "pinch_joy.up", "action": "t.once"})
    router.engage_required = True
    router.route(ev("engage", "begin", t=1))
    router.route(ev("pinch_joy", "begin", t=1.5))
    for t in (1.6, 1.8, 2.0):
        router.route(ev("pinch_joy.up", t=t))
    router.route(ev("pinch_joy", "end", t=2.1))
    router.route(ev("pinch_joy.up", t=2.2))  # new hold, no engage → blocked
    assert len(router.calls) == 3


@pytest.mark.parametrize("track", ["palm", "knuckles", "index", "middle", "pinch"])
def test_pointer_tracks_chosen_point(track):
    g = REGISTRY["pointer"]({"track": track, "smoothing": 0})
    evs = [e for i in range(3) for e in g.update(Frame(t=i, hands=(make_hand(palm=(i * 10, 200, 0)),)))]
    assert evs[-1].value[0] == pytest.approx(10)  # moved 10 mm right per frame


def test_two_hand_pinch_is_not_a_joystick():
    pair = lambda s: (make_hand("left", (-s, 200, 0), pinch=.95), make_hand("right", (s, 200, 0), pinch=.95))  # noqa
    frames = [Frame(t=i / 100, hands=pair(50 + i)) for i in range(80)]
    assert [n for n, ph in run(REGISTRY["pinch_joy"](), frames) if ph == "fire"] == []


def test_moving_pinch_is_not_ok():
    moving = make_hand(extended={"middle", "ring", "pinky"}, pinch=0.95, velocity=(0, 150, 0))
    assert run(REGISTRY["ok"](), hold(moving, 1.5)) == []
