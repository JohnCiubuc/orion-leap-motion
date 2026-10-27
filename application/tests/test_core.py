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
from orion.gestures.fingers import FingerMotion  # noqa: E402
from orion.gestures.paths import PathGesture, _resample  # noqa: E402
from orion.gestures.precision import PrecisionLock  # noqa: E402
from orion.router import Router  # noqa: E402
from orion.sim import make_hand  # noqa: E402
from orion.frame import FINGERS  # noqa: E402

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


def test_palm_flip_vertical():
    flat, edge = make_hand(normal=(0, -1, 0)), make_hand(normal=(1, 0, 0))
    turn = [Frame(t=i / 100, hands=(flat if i < 20 else edge,)) for i in range(200)]
    assert run(REGISTRY["palm_flip"](), turn) == [("palm_flip.vertical", "fire")]  # once, not every cooldown
    assert run(REGISTRY["palm_flip"]({"hold": 0.5}), turn[:65]) == []  # 0.45 s held: too short
    assert run(REGISTRY["palm_flip"](), hold(edge, 2.0)) == []  # arrives already edge-on: no turn


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


@pytest.mark.parametrize("track", ["palm", "palm_stable", "knuckles", "index", "middle", "pinch"])
def test_pointer_tracks_chosen_point(track):
    g = REGISTRY["pointer"]({"track": track, "steady": 5.0})
    evs = [e for i in range(3) for e in g.update(Frame(t=i, hands=(make_hand(palm=(i * 10, 200, 0)),)))]
    assert evs[-1].value[0] == pytest.approx(10, rel=0.05)  # moved 10 mm right per frame


def test_pointer_moves_even_when_service_leaves_stabilized_position_empty():
    frames = []
    for i in range(30):
        h = make_hand(palm=(i * 2.0, 200, 0))
        h.stable[:] = 0  # what some service versions send
        frames.append(Frame(t=i / 100, hands=(h,)))
    for track in ("palm", "palm_stable"):
        g = REGISTRY["pointer"]({"track": track})
        moved = sum(e.value[0] for f in frames for e in g.update(f) if e.phase == "update")
        assert moved > 20, track


def test_pointer_filter_calms_jitter():
    rng = np.random.default_rng(2)
    g = REGISTRY["pointer"]()
    steps = [e.value for i in range(200)
             for e in g.update(Frame(t=i / 110, hands=(make_hand(palm=(*rng.normal(0, 1.0, 2), 0) + np.array([0, 200, 0])),)))
             if e.phase == "update"]
    assert np.abs(steps).mean() < 0.3  # raw jitter steps average ~1.1 mm


def desktop_at(x, y, **params):
    g = REGISTRY["desktop_pointer"]({"steady": 5.0, "view_width": 400, "view_top": 450, **params})  # the original geometry
    evs = [e for i in range(5) for e in g.update(Frame(t=i / 100, hands=(make_hand(palm=(x, y, 0)),)))]
    return evs[-1].value


def test_desktop_pointer_maps_inner_view_to_whole_desktop():
    assert desktop_at(0, (382.5 + 150) / 2) == pytest.approx((0.5, 0.5), abs=0.03)  # leaves a small gap by design
    assert desktop_at(-170, 382.5) == pytest.approx((0.0, 0.0), abs=0.01)  # 85 % of the view: top-left corner
    assert desktop_at(170, 150) == pytest.approx((1.0, 1.0), abs=0.01)  # bottom edge 150 mm above the device
    assert desktop_at(-195, 440) == pytest.approx((0.0, 0.0))  # past the margin: pinned to the corner
    assert desktop_at(0, 60)[1] == 1.0  # near the device: stays on the bottom edge


def test_desktop_pointer_margins_are_configurable():
    assert desktop_at(-100, 200, coverage=0.5, view_width=400)[0] == pytest.approx(0.0, abs=0.03)  # leaves a small gap by design
    assert desktop_at(0, 100, bottom=100)[1] == pytest.approx(1.0, abs=0.03)  # leaves a small gap by design


def test_desktop_pointer_stops_on_a_fist():
    g = REGISTRY["desktop_pointer"]()
    evs = [e for i in range(5) for e in g.update(Frame(t=i / 100, hands=(make_hand(extended=set()),)))]
    assert evs == []

def _dp(**params):  # default geometry, raw filter so the hand position passes through
    return REGISTRY["desktop_pointer"]({"steady": 5.0, "responsive": 0.2, **params})


def _dp_run(g, pts, t0=0.0, ext=FINGERS):  # pts: (x, y) or None (no hand); returns (u, v) per frame with a hand
    out = []
    for i, pt in enumerate(pts):
        hands = () if pt is None else (make_hand(palm=(*pt, 0), extended=ext(i) if callable(ext) else ext),)
        out += [e.value for e in g.update(Frame(t=t0 + i / 115, hands=hands)) if e.value is not None]
    return np.array(out)


def _dp_map(x, y, g):  # the plain view → desktop mapping
    p = g.p
    half, top = p["coverage"] * p["view_width"] / 2, max(p["coverage"] * p["view_top"], p["bottom"] + 1)
    return np.array([(x + half) / (2 * half), (top - y) / (top - p["bottom"])])


def test_desktop_pointer_walk_to_each_limit_hits_the_screen_edge():
    rest = [(0, 220)] * 30
    walk = lambda dx, dy: rest + [(dx * 0.19 * i, 220 + dy * 0.19 * i) for i in range(1, 900)]  # noqa: E731  22 mm/s
    assert _dp_run(_dp(), walk(-1, 0))[-1, 0] == 0.0
    assert _dp_run(_dp(), walk(1, 0))[-1, 0] == 1.0
    assert _dp_run(_dp(), walk(0, 1))[-1, 1] == 0.0


def test_desktop_pointer_precise_set_tracks_the_mode():
    g = _dp()
    _dp_run(g, [(-60, 220)] * 35)  # 0.3 s still
    assert "right" in g.precise
    _dp_run(g, [(-60 + 4 * i, 220) for i in range(1, 30)], 1)  # 460 mm/s sweep
    assert g.precise == set()


def test_desktop_pointer_tap_from_rest_keeps_the_cursor():
    g = _dp()
    before = _dp_run(g, [(0, 220)] * 58)[-1]  # 0.5 s rest
    dip = [(0, 220 - 5 * min(i, 8) / 8) for i in range(1, 70)]  # palm dips 5 mm while the index curls
    after = _dp_run(g, dip, 58 / 115, ext=set(FINGERS) - {"index"})  # no time gap: FingerMotion needs the rest frames
    assert np.abs(after - before).max() < 1 / g.p["view_width"]


def test_desktop_pointer_resets_when_the_hand_returns():
    g = _dp()
    _dp_run(g, [(0, 220)] * 30 + [(0.19 * i, 220) for i in range(1, 100)])  # precision, cursor lags the hand
    _dp_run(g, [None] * 115, 1)  # hand gone for 1 s
    assert g.precise == set()
    assert _dp_run(g, [(60, 260)], 2)[0] == pytest.approx(_dp_map(60, 260, g))


def test_desktop_pointer_ignores_removed_settings():
    g = REGISTRY["desktop_pointer"]({"fine": 0.5, "reach": 10, "fine_speed": 5, "tap_damp": 1})
    assert len(_dp_run(g, [(0.5 * i, 220) for i in range(50)])) == 50


def test_desktop_pointer_degenerate_geometry_stays_in_range():
    g = _dp(view_top=151, bottom=150, coverage=0.5)
    out = _dp_run(g, [(x, y) for x in (-300, -20, 0, 40, 300) for y in (0, 150, 150.5, 151, 500)] * 3)
    assert np.isfinite(out).all() and (out >= 0).all() and (out <= 1).all()



def test_freeze_cursor_holds_the_desktop_pointer_too(router):
    router.modes.add("m")
    router.bindings += [{"gesture": "desktop_pointer", "action": "t.stream", "mode": "m"},
                        {"gesture": "pinch_joy.up", "action": "t.once", "mode": "m", "freeze_pointer": True}]
    router.route(ev("desktop_pointer", "begin", 1.0))
    router.route(ev("pinch_joy", "begin", 1.01))
    before = len(router.calls)
    router.route(ev("desktop_pointer", "update", 1.02))
    assert len(router.calls) == before


def test_default_config_has_desktop_mouse_mode():
    cfg = Config()
    assert cfg["modes"]["desktop_mouse"]["exclusive"]
    acts = {b["gesture"]: b["action"] for b in cfg["bindings"] if b.get("mode") == "desktop_mouse"}
    assert acts["desktop_pointer"] == "input.desktop" and "input.desktop" in ACTIONS


def test_desktop_action_writes_absolute_position(monkeypatch):
    import evdev
    from evdev import ecodes as e
    from orion.actions import uinput
    made = {}

    class FakeUInput:
        def __init__(self, caps, name):
            self.caps, self.writes = caps, []
            made[name] = self

        def write(self, *a):
            self.writes.append(a)

        def syn(self):
            pass

    monkeypatch.setattr(evdev, "UInput", FakeUInput)
    monkeypatch.setattr(uinput, "_mouse", None)
    monkeypatch.setattr(uinput, "_abs", None)
    assert uinput.warmup() == "ready"
    dev = made["Orion Renewal desktop pointer"]
    assert {c for c, _ in dev.caps[e.EV_ABS]} == {e.ABS_X, e.ABS_Y} and e.BTN_LEFT in dev.caps[e.EV_KEY]
    ACTIONS["input.desktop"].fn(GestureEvent("desktop_pointer", "update", np.array([0.25, 1.0])), display="")
    assert dev.writes == [(e.EV_ABS, e.ABS_X, uinput.ABS_MAX // 4 + 1), (e.EV_ABS, e.ABS_Y, uinput.ABS_MAX)]


def test_desktop_action_can_target_one_display(monkeypatch):
    import json
    from orion.actions import hyprland, uinput
    mons = [{"name": "DP-3", "x": 0, "y": 0, "width": 3840, "height": 2160, "scale": 1.0},
            {"name": "HDMI-A-1", "x": 3840, "y": 0, "width": 1920, "height": 1080, "scale": 1.0}]
    monkeypatch.setattr(hyprland, "hyprctl", lambda req: json.dumps(mons))
    assert uinput._display_area("DP-3") == pytest.approx((0, 0, 3840 / 5760, 1))
    assert uinput._display_area("HDMI-A-1") == pytest.approx((3840 / 5760, 0, 1920 / 5760, 0.5))
    with pytest.raises(RuntimeError, match="DP-9"):
        uinput._display_area("DP-9")


def test_two_hand_pinch_is_not_a_joystick():
    pair = lambda s: (make_hand("left", (-s, 200, 0), pinch=.95), make_hand("right", (s, 200, 0), pinch=.95))  # noqa
    frames = [Frame(t=i / 100, hands=pair(50 + i)) for i in range(80)]
    assert [n for n, ph in run(REGISTRY["pinch_joy"](), frames) if ph == "fire"] == []


def test_moving_pinch_is_not_ok():
    moving = make_hand(extended={"middle", "ring", "pinky"}, pinch=0.95, velocity=(0, 150, 0))
    assert run(REGISTRY["ok"](), hold(moving, 1.5)) == []


# ── Overlay ───────────────────────────────────────────────────────────────────

def test_overlay_shows_only_meaningful_events():
    from types import SimpleNamespace as NS
    from orion.overlay import OverlayHost
    host = OverlayHost(NS(listeners=[], dry_run=False))
    sent = []
    host.proc, host.cfg, host.send = object(), {"enabled": True}, sent.append
    ev = lambda name, phase="fire", acts=("media",): {"name": name, "phase": phase, "actions": list(acts),  # noqa
                                                     "hand": "right", "profile": "default"}
    for e in (ev("pointer", "begin"), ev("pinch_joy", "begin"), ev("open_palm", "begin", ()),
              ev("swipe.left"), ev("pinch_joy.up"), ev("path.circle")):
        host.on_engine("event", e)
    host.on_engine("notice", {"text": "Air mouse on"})
    assert [m["title"] for m in sent] == ["Swipe left", "Pinch up", "Circle", "Air mouse on"]


# ── Freeze cursor ─────────────────────────────────────────────────────────────

def test_freeze_cursor_only_for_flagged_bindings(router):
    moves = lambda: [c for c in router.calls if c[0] == "t.stream" and c[1] == "update"]  # noqa
    router.bindings += [{"gesture": "pointer", "action": "t.stream", "mode": "m"},
                        {"gesture": "pinch_joy.up", "action": "t.once", "mode": "m", "freeze_pointer": True},
                        {"gesture": "pinch", "action": "t.stream", "mode": "m"}]  # drag: no freeze
    router.modes.add("m")
    router.route(ev("pointer", "begin", 1.0))
    router.route(ev("pointer", "update", 1.01))
    router.route(ev("pinch_joy", "begin", 1.02))  # scroll hold → frozen from the start
    router.route(ev("pointer", "update", 1.03))
    router.route(ev("pinch_joy.up", "fire", 1.2))
    router.route(ev("pointer", "update", 1.3))
    router.route(ev("pinch_joy", "end", 1.4))
    router.route(ev("pointer", "update", 1.5))  # moves again
    router.route(ev("pinch", "begin", 1.6))  # drag keeps moving
    router.route(ev("pointer", "update", 1.7))
    assert len(moves()) == 3


def test_saved_bindings_keep_inline_args():
    import tomllib
    cfg = Config()
    cfg.data["bindings"] = [{"gesture": "tap", "action": "shell", "args": {"cmd": "true"}, "freeze_pointer": True, "hand": None}]
    cfg.save()
    text = cfg.path.read_text()
    assert 'args = {cmd = "true"}' in text.replace("{ ", "{").replace(" }", "}") and "[bindings.args]" not in text
    assert tomllib.loads(text)["bindings"][0] == {"gesture": "tap", "action": "shell", "args": {"cmd": "true"}, "freeze_pointer": True}


# ── Hyprland dispatch: classic vs Lua config ─────────────────────────────────

@pytest.mark.parametrize("lua_mode", [False, True])
def test_hypr_dispatch_speaks_the_config_language(monkeypatch, lua_mode):
    from orion.actions import hyprland as hy
    sent = []

    def fake(req):
        sent.append(req)
        if req == "systeminfo":
            return "Hyprland 0.55\nconfigProvider: lua\n" if lua_mode else "Hyprland 0.49\n"
        return "ok"
    monkeypatch.setattr(hy, "hyprctl", fake)
    monkeypatch.setattr(hy, "_lua", None)
    hy.dispatch(None, "workspace e-1")
    want = 'dispatch hl.dsp.focus({ workspace = "e-1" })' if lua_mode else "dispatch workspace e-1"
    assert sent[-1] == want


def test_hypr_dispatch_retries_in_lua_when_rejected(monkeypatch):
    from orion.actions import hyprland as hy
    sent = []

    def fake(req):
        sent.append(req)
        if req == "systeminfo":
            return "Hyprland\n"  # looks classic…
        if "hl.dsp" in req:
            return "ok"
        return "error: [string \"return hl.dispatch(workspace e-1)\"]:1: ')' expected → Note: dispatch in lua is hl.dispatch(...)"
    monkeypatch.setattr(hy, "hyprctl", fake)
    monkeypatch.setattr(hy, "_lua", None)
    hy.dispatch(None, "workspace e-1")  # …but Hyprland rejects classic syntax: retried as Lua, no error
    assert sent[-1].startswith("dispatch hl.dsp.focus") and hy._lua is True


# ── Modes: hooks + exclusivity ───────────────────────────────────────────────

@pytest.fixture
def engine(monkeypatch):
    from orion.engine import Engine
    e = Engine(Config())
    e.cfg.data["modes"] = {
        "air": {"exclusive": True, "on_enter": [{"action": "t.hook", "args": {"tag": "air-on"}}],
                "on_exit": [{"action": "t.hook", "args": {"tag": "air-off"}}]},
        "present": {"on_enter": [{"action": "t.hook", "args": {"tag": "present-on"}}]},
        "draw": {},
    }
    e.router.configure(e.cfg)
    e.hooks = []
    ACTIONS["t.hook"] = Action("t.hook", lambda ev, tag: None, {"tag": ""})
    monkeypatch.setattr(e.executor, "submit", lambda act, ev, args: e.hooks.append(args["tag"]))
    return e


def test_mode_hooks_run_on_enter_and_exit(engine):
    engine.set_mode("air", True)
    engine.set_mode("air", False)
    assert engine.hooks == ["air-on", "air-off"]


def test_exclusive_mode_is_alone(engine):
    engine.set_mode("present", True)
    engine.set_mode("draw", True)
    engine.set_mode("air", True)  # exclusive: switches the others off
    assert engine.router.modes == {"air"}
    assert engine.set_mode("present", True) is False  # blocked while air is on
    assert engine.router.modes == {"air"}
    engine.set_mode("air", False)
    assert engine.set_mode("present", True) and engine.router.modes == {"present"}


def test_global_shortcut_dispatch(monkeypatch):
    from orion.actions import hyprland as hy
    sent = []
    monkeypatch.setattr(hy, "hyprctl", lambda req: sent.append(req) or ("configProvider: lua" if req == "systeminfo" else "ok"))
    monkeypatch.setattr(hy, "_lua", None)
    hy.global_shortcut(None, "kando:example-menu")
    assert sent[-1] == 'dispatch hl.dsp.global("kando:example-menu")'
    monkeypatch.setattr(hy, "_lua", False)
    hy.global_shortcut(None, "kando:example-menu")
    assert sent[-1] == "dispatch global kando:example-menu"


def test_mode_hooks_saved_as_toml():
    import tomllib
    cfg = Config()
    cfg.data["modes"]["air_mouse"]["on_enter"] = [{"action": "hypr.global", "args": {"shortcut": "kando:example-menu"}}]
    cfg.save()
    assert tomllib.loads(cfg.path.read_text())["modes"]["air_mouse"]["on_enter"][0]["args"]["shortcut"] == "kando:example-menu"


def test_mode_follows_its_app(engine, monkeypatch):
    import time as _t
    from orion.actions import hyprland as hy
    windows = {"kitty"}
    monkeypatch.setattr(hy, "window_classes", lambda: set(windows))
    engine.cfg.data["modes"]["draw"] = {"follow_app": "(?i)^krita$", "follow_grace": 5}
    engine.set_mode("draw", True)
    engine.watchdog()
    assert "draw" in engine.router.modes  # app still starting: within the grace period
    windows.add("krita")
    engine.watchdog()
    windows.discard("krita")  # app closed → mode off
    engine.watchdog()
    assert "draw" not in engine.router.modes
    engine.set_mode("draw", True)
    engine._follow["draw"]["since"] -= 10  # never appeared within 5 s → off
    engine.watchdog()
    assert "draw" not in engine.router.modes


def test_new_keys_land_inside_their_table_not_after_comments():
    cfg = Config()
    cfg.data["modes"]["air_mouse"]["follow_app"] = "(?i)^krita$"
    cfg.save()
    text = cfg.path.read_text()
    block = text[text.index("[modes.air_mouse]"):]
    assert block.index("follow_app") < block.index("# ── Default profile")
    import tomllib
    data = tomllib.loads(text)["modes"]["air_mouse"]
    assert data["follow_app"] == "(?i)^krita$" and all("follow_app" not in h for h in data.get("on_enter", []))


# ── Handedness ────────────────────────────────────────────────────────────────

def sides(frames, preferred="left"):
    from types import SimpleNamespace as NS
    from orion.handedness import Handedness
    hd = Handedness(NS(general={"preferred_hand": preferred}))
    return [tuple(h.side for h in hd(f).hands) for f in frames]


def lone(raw, seconds, x=0, t0=0.0, hid=5):
    return [Frame(t=t0 + i / 100, hands=(make_hand(raw, palm=(x, 200, 0), hid=hid),)) for i in range(int(seconds * 100))]


def test_left_hand_misread_as_right_on_entry_stays_left():
    out = sides(lone("right", 0.3) + lone("left", 1, t0=0.3))
    assert set(out) == {("left",)}


def test_lone_right_hand_settles_and_sticks():
    out = sides(lone("right", 1) + lone("left", 1, t0=1))
    assert out[0] == ("left",) and out[60] == ("right",) and out[-1] == ("right",)
    assert sides(lone("right", 0.3, x=120))[25] == ("right",)  # came in from the right: half the wait


def test_second_hand_takes_the_other_side():
    a = make_hand("left", palm=(-80, 200, 0), hid=1)
    frames = [Frame(t=i / 100, hands=(a, make_hand("left", palm=(80, 200, 0), hid=2))) for i in range(100)]
    assert set(sides(frames)) == {("left", "right")}


def test_pointer_curve_still_then_linear_then_exponential():
    from orion.actions.uinput import pointer_gain
    px = lambda s: s * pointer_gain(s, 4.0, 0.15, 0.1)  # noqa: E731  px per frame at speed s
    assert px(0.02) < 0.01                      # a resting hand's jitter is sub-pixel
    assert px(0.5) > 20 * px(0.02)
    assert pointer_gain(5, 4, 0.15, 0.1) > 1.5 * pointer_gain(1, 4, 0.15, 0.1)  # faster hand → higher gain
    assert pointer_gain(500, 4, 0.15, 0.1) < 4 * 21  # capped


def test_pointer_damps_palm_wobble_while_a_finger_moves():
    def moved(flex):  # a 6 mm palm dip over 8 frames, with or without the index curling at the same time
        g = REGISTRY["pointer"]({"steady": 5.0, "responsive": 0.2})
        ys, tot = [200] * 4 + [200 - 0.75 * i for i in range(1, 9)], 0.0
        for i, y in enumerate(ys):
            ext = set(FINGERS) - {"index"} if flex and i >= 4 else set(FINGERS)
            tot += sum(abs(e.value[1]) for e in g.update(Frame(t=i / 100, hands=(make_hand(palm=(0, y, 0), extended=ext),)))
                       if e.phase == "update")
        return tot
    assert moved(True) < 0.6 * moved(False)


def test_tap_damping_never_applies_to_a_moving_hand():
    def damped(ys, flex_at=None):  # did the cursor lag the hand at the end?
        g = REGISTRY["pointer"]({"steady": 5.0, "responsive": 0.2})
        out = 0.0
        for i, y in enumerate(ys):
            ext = set(FINGERS) - {"index"} if flex_at is not None and i >= flex_at else set(FINGERS)
            out += sum(e.value[1] for e in g.update(Frame(t=i / 115, hands=(make_hand(palm=(0, y, 0), extended=ext),)))
                       if e.phase == "update")
        return out
    sweep = [200 - 4 * i for i in range(60)]  # 460 mm/s: moving hand, finger flex must not damp it
    assert damped(sweep, flex_at=30) == pytest.approx(damped(sweep), rel=0.02)


def _tips(dy):  # five fingertips; the index drops by dy mm relative to the palm
    t = np.zeros((5, 3)); t[1, 1] = -dy; return t


def test_finger_motion_flags_a_tap_from_rest():
    f = FingerMotion()
    assert not any(f.update(i / 115, _tips(0), 5.0, 5, 60) for i in range(10))
    assert any(f.update((10 + i) / 115, _tips(i * 1.5), 10.0, 5, 60) for i in range(8))


def test_finger_motion_ignores_a_moving_palm():
    f = FingerMotion()
    assert not any(f.update(i / 115, _tips(i * 1.5), 200.0, 5, 60) for i in range(20))  # palm 200 mm/s ≥ still


def test_finger_motion_ignores_small_noise():
    f = FingerMotion(); rng = np.random.default_rng(0)
    assert not any(f.update(i / 115, _tips(rng.normal(0, 0.3)), 3.0, 5, 60) for i in range(200))


# ── Precision lock (desktop pointer cursor, mm in the view) ───────────────────

LOCK = {"precision": 0.2, "dwell": 0.10, "enter_speed": 40, "exit_speed": 150, "radius": 25, "edge": 20,
        "rest": 0.2, "glide": 0.12, "tap_hold": 0.30}
LO, HI = np.array([-125.5, 150.0]), np.array([125.5, 351.0])
STILL = 23  # frames: 0.2 s, past dwell, so the lock is in precision


def _lock_run(lock, xs, speeds, t0=0.0, dt=1 / 115, taps=None, ys=250.0):  # `run` is taken by the gesture helper
    n = len(xs)
    speeds, ys, taps = np.broadcast_to(speeds, n), np.broadcast_to(ys, n), taps or [False] * n
    return np.array([lock.step(t0 + i * dt, np.array([x, y], float), s, tp, LO, HI)
                     for i, (x, y, s, tp) in enumerate(zip(xs, ys, speeds, taps))])


def test_coarse_is_stateless():
    hold = [40.0] * 230  # 2 s: the glide has fully decayed
    a = _lock_run(PrecisionLock(LOCK), [0] * 5 + list(np.linspace(0, 40, 10)) + hold, 300)
    b = _lock_run(PrecisionLock(LOCK), [-80, 60, 100, 20] + list(np.linspace(20, 40, 5)) + hold, 300)
    assert a[-1, 0] == pytest.approx(40, abs=1e-9)
    assert b[-1] == pytest.approx(a[-1], abs=1e-9)


def test_precision_scales_slow_motion():
    lock = PrecisionLock(LOCK)
    c = _lock_run(lock, [0] * STILL + list(np.linspace(0, 10, 59)[1:]), [0] * STILL + [20] * 58)
    assert lock.precise
    assert c[-1, 0] - c[STILL - 1, 0] == pytest.approx(10 * LOCK["precision"], abs=0.5)


def test_gain_reaches_one_at_radius():
    lock = PrecisionLock(LOCK)
    step = 20 / 115
    c = _lock_run(lock, [0] * STILL + list(step * np.arange(1, 300)), [0] * STILL + [20] * 299)  # 52 mm of travel
    assert lock.precise
    assert c[-1, 0] - c[-2, 0] == pytest.approx(step, abs=1e-6)


def test_fast_move_glides_to_the_hand():
    lock = PrecisionLock(LOCK)
    c = _lock_run(lock, [0] * STILL + list(np.linspace(0, 10, 59)[1:]), [0] * STILL + [20] * 58)
    offset = abs(c[-1, 0] - 10)  # cursor lags the hand after the scaled move
    n = math.ceil((LOCK["glide"] + 0.05) * 115)
    g = _lock_run(lock, [10.0] * n, 300, t0=(STILL + 58) / 115)  # filter reports a fast move
    assert not lock.precise
    assert abs(g[-1, 0] - 10) < 0.05 * offset
    assert np.abs(np.diff(np.vstack([c[-1:], g]), axis=0)).max() <= offset  # no snap


def test_edge_walk_always_reaches_the_limit():
    lock = PrecisionLock(LOCK)
    _lock_run(lock, [0] * STILL, 0)
    assert lock.precise
    walk = list(np.minimum(20 / 115 * np.arange(1, 800), HI[0]))  # walks onto the limit, then rests there
    c = _lock_run(lock, walk, 20, t0=STILL / 115)
    assert c[-1, 0] == HI[0]


def test_rest_latch_ignores_tremor():
    lock = PrecisionLock(LOCK)
    c0 = _lock_run(lock, [0] * STILL, 0)[-1]
    noise = np.random.default_rng(0).uniform(-0.1, 0.1, 100)
    c = _lock_run(lock, list(noise), 5, t0=STILL / 115)
    assert lock.precise
    assert np.abs(c - c0).max() < 1e-9


def test_tap_rewinds_and_holds():
    lock = PrecisionLock(LOCK)
    c_pre = _lock_run(lock, [0] * STILL, 0)[-1]
    dip = 250 - 0.625 * np.arange(1, 9)  # palm dips 5 mm over 8 frames
    hold = math.ceil(LOCK["tap_hold"] * 115)
    ys = list(dip) + [dip[-1]] * hold
    c = _lock_run(lock, [0] * len(ys), [70] * 8 + [0] * hold, t0=STILL / 115,
                  taps=[False] * 3 + [True] * 5 + [False] * hold, ys=ys)
    assert c[3] == pytest.approx(c_pre, abs=1e-6)  # rewound to before the dip
    held = c[3:3 + hold - 1]  # until tap_hold after the tap
    assert np.abs(held - c_pre).max() < 0.5
    assert lock.precise
    t0 = (STILL + len(ys)) / 115
    f = _lock_run(lock, list(20 / 115 * np.arange(1, 31)), 20, t0=t0, ys=dip[-1])  # follows again, scaled
    assert 0.15 < (f[-1, 0] - c[-1, 0]) / (20 / 115 * 30) < 0.35


def test_duplicate_timestamps_do_not_blow_up():
    lock = PrecisionLock(LOCK)
    p = np.array([0.0, 250.0])
    a = lock.step(1.0, p, 0.0, False, LO, HI)
    b = lock.step(1.0, p + 1, 500.0, False, LO, HI)
    assert np.all(np.isfinite(a)) and np.all(np.isfinite(b))


def test_tap_hold_lasts_until_tap_hold_after_the_finger_stops():
    lock = PrecisionLock(LOCK)
    c_pre = _lock_run(lock, [0] * STILL, 0)[-1]
    tap_n, hold_n = 52, math.ceil(LOCK["tap_hold"] * 115) - 1  # tap level True for 0.45 s, then held 0.3 s more
    n = tap_n + hold_n + 30
    xs = list(0.1 * np.arange(1, n + 1))  # palm drifts slowly the whole time
    c = _lock_run(lock, xs, 11.5, t0=STILL / 115, taps=[True] * tap_n + [False] * (n - tap_n))
    assert np.abs(c[:tap_n + hold_n] - c_pre).max() < 1e-6  # held through the long tap and tap_hold after it
    ratio = (c[-1, 0] - c[tap_n + hold_n - 1, 0]) / (0.1 * 30)
    assert lock.precise and 0.15 < ratio < 0.6  # then follows again, scaled
