"""Menu skins: registry, and drawing through plain cairo off-screen (no GTK, no compositor)."""

import os
from pathlib import Path

import pytest

from orion.menu_anim import MenuAnim
from orion.menu_skins import DEFAULT, get_skin, names

SKIN_DIR = Path(__file__).parent.parent / "orion" / "menu_skins"
SIZE = 560


def test_registry_falls_back_to_the_default_skin():
    assert DEFAULT == "aurora" and "aurora" in names()
    assert get_skin("nope") is get_skin("aurora") and get_skin("") is get_skin("aurora") and get_skin(None) is get_skin("aurora")


def test_skin_modules_import_nothing_from_orion():
    for f in SKIN_DIR.glob("*.py"):
        text = f.read_text()
        assert "import orion" not in text and "from orion" not in text and "menu_anim" not in text, f.name


def _surface():
    cairo = pytest.importorskip("cairo")
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, SIZE, SIZE)
    return surf, cairo.Context(surf)


def _ink(surf):
    surf.flush()
    return any(surf.get_data())


def _tour(skin, frame):
    """Drive a real MenuAnim through open → hover → enter → deeper → back → fire → close, calling frame(label, anim, t)."""
    a = MenuAnim(**skin.MOTION)
    t = 0.0
    a.open(["1", "2", "3", "4"], t, [False, True, False, False], [1, 1, 1, 0.5])  # unequal widths, like a user menu
    steps = [("bloom", 0.5), ("hover", 0.2), ("pulling", 0.2)]
    a.update(0.0, 0.5, 1, 0.5, 0.3)
    for label, dur in steps:
        t += dur
        frame(label, a, t)
    a.update(0, 1, 1, 1, t)
    a.enter(["a", "b", "c"], t, 270, "2", [False, True, False], [1, 0.5, 2])
    for label, dur in (("enter+0.03", 0.03), ("enter+0.09", 0.06), ("enter+0.2", 0.11), ("submenu", 0.6)):
        t += dur
        frame(label, a, t)
    a.update(0, 0.5, -1, 0.5, t)
    t += 0.3
    frame("back-hover", a, t)
    a.update(0, 0.6, 1, 1, t)
    a.enter(["x", "y"], t, 90, "b")
    t += 0.7
    frame("two-deep", a, t)
    a.back(["a", "b", "c"], t, 270, 90)
    t += 0.1
    frame("back+0.1", a, t)
    t += 0.6
    a.update(0, 0.5, 0, 1, t)
    a.fire(0, t)
    frame("fire", a, t + 0.05)
    frame("collapsing", a, t + 0.3)
    t += 1.0
    frame("closed", a, t)


@pytest.mark.parametrize("name", names())
def test_tune_rotates_the_palette_and_flips_the_text(name):
    import colorsys
    skin = get_skin(name)
    hue = lambda c: colorsys.rgb_to_hls(*c)[0] * 360  # noqa: E731
    try:
        skin.tune(None, False)
        base, label = skin.ACCENT, skin.LABEL
        skin.tune(skin.HUE + 100, True)
        assert skin.LABEL == tuple(1 - x for x in type(skin).LABEL) and skin.LABEL_HOT == tuple(1 - x for x in type(skin).LABEL_HOT)
        if colorsys.rgb_to_hls(*base)[2] > 0.05:  # a grey accent has no hue to move
            assert (hue(skin.ACCENT) - hue(base)) % 360 == pytest.approx(100, abs=1)
        skin.tune(None, False)
        assert skin.ACCENT == pytest.approx(base) and skin.LABEL == label  # not cumulative
    finally:
        skin.tune(None, False)


@pytest.mark.parametrize("name", names())
def test_skin_draws_every_phase(name):
    skin = get_skin(name)
    skin.tune(300, True)
    seen = {}

    def frame(label, anim, t):
        surf, cr = _surface()
        skin.draw(cr, anim.step(t), SIZE, SIZE)
        seen[label] = _ink(surf)

    try:
        _tour(skin, frame)
    finally:
        skin.tune(None, False)
    assert seen["bloom"] and seen["submenu"] and seen["two-deep"] and seen["back-hover"] and seen["fire"]
    assert not seen["closed"]


@pytest.mark.parametrize("name", names())
def test_render_contact_sheet(name):
    out = os.environ.get("ORION_RENDER_DIR")
    if not out:
        pytest.skip("set ORION_RENDER_DIR to write PNGs")
    skin = get_skin(name)
    out = Path(out) / name
    out.mkdir(parents=True, exist_ok=True)

    def frame(label, anim, t):
        surf, cr = _surface()
        cr.set_source_rgb(0.04, 0.05, 0.1)  # a dark desktop behind the translucent pie
        cr.paint()
        skin.draw(cr, anim.step(t), SIZE, SIZE)
        surf.write_to_png(str(out / f"{label.replace('+', '_')}.png"))

    _tour(skin, frame)


# ── MenuController (the overlay window's GTK-free half) ──────────────────────

from orion import menu_skins  # noqa: E402
from orion.menu_ctl import MenuController  # noqa: E402


def _ctl(**kw):
    return MenuController(MenuAnim, get_skin, **kw)


def _open(ctl, skin=None, now=0.0):
    ctl.handle({"op": "open", "labels": ["1", "2", "3", "4"], "subs": [False, True, False, False], "skin": skin}, now)


def test_controller_unknown_skin_uses_the_default():
    ctl = _ctl()
    _open(ctl, "nope")
    assert ctl.skin is get_skin("aurora")


def test_controller_routes_enter_and_back_to_the_animation():
    ctl = _ctl()
    _open(ctl)
    ctl.handle({"op": "update", "x": 0, "y": 0.9, "hover": 1, "pull": 1.0}, 0.5)
    ctl.handle({"op": "enter", "labels": ["a", "b"], "subs": [False, False], "back": 270, "depth": 1, "parent": "2"}, 0.6)
    assert ctl.view(0.61).pan != (0, 0) and [s.label for s in ctl.view(0.61).slices] == ["a", "b"]
    ctl.handle({"op": "back", "labels": ["1", "2", "3", "4"], "subs": [False] * 4, "back": None, "depth": 0, "away": 270}, 1.0)
    assert [s.label for s in ctl.view(1.01).slices] == ["1", "2", "3", "4"]


def test_controller_reduced_motion_reaches_the_animation():
    ctl = _ctl(reduced_motion=True)
    _open(ctl)
    ctl.handle({"op": "enter", "labels": ["a", "b"], "subs": [False, False], "back": 270, "depth": 1, "parent": "2"}, 0.6)
    assert ctl.view(0.62).pan == (0, 0)


def test_controller_ignores_ops_before_open():
    ctl = _ctl()
    ctl.handle({"op": "update", "x": 0, "y": 0, "hover": None, "pull": 0}, 0.0)
    assert ctl.view(0.0) is None


def test_a_skin_that_raises_is_dropped_for_the_default():
    @menu_skins.skin("boom")
    class Boom:
        MOTION = {}

        def draw(self, cr, v, w, h):
            raise RuntimeError("bad skin")

    try:
        ctl = _ctl()
        _open(ctl, "boom")
        assert ctl.draw(None, ctl.view(0.5), SIZE, SIZE) is False  # reported, not raised
        _open(ctl, "boom", 1.0)
        assert ctl.skin is get_skin("aurora") and not ctl.broken
    finally:
        menu_skins._SKINS.pop("boom", None)


def test_a_default_skin_that_raises_breaks_the_menu_for_good(monkeypatch):
    ctl = _ctl()
    _open(ctl)
    monkeypatch.setattr(type(get_skin("aurora")), "draw", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    assert ctl.draw(None, ctl.view(0.5), SIZE, SIZE) is False and ctl.broken
    _open(ctl, None, 2.0)
    assert ctl.view(2.1) is None  # nothing is drawn, nothing to leave on screen


# ── Editor preview ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", names())
def test_preview_png_for_every_skin(name):
    pytest.importorskip("cairo")
    from orion.menu_preview import png
    out = png(name, ["a", "b", "c"], [1, 0.5, 2], hue=300, invert=True)
    assert out[:8] == b"\x89PNG\r\n\x1a\n" and len(out) > 2000
