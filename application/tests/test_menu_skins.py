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
    a.open(["1", "2", "3", "4"], t, [False, True, False, False])
    steps = [("bloom", 0.5), ("hover", 0.2), ("pulling", 0.2)]
    a.update(0.0, 0.5, 1, 0.5, 0.3)
    for label, dur in steps:
        t += dur
        frame(label, a, t)
    a.update(0, 1, 1, 1, t)
    a.enter(["a", "b", "c"], t, 270, "2", [False, True, False])
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


def test_aurora_draws_every_phase():
    skin = get_skin("aurora")
    seen = {}

    def frame(label, anim, t):
        surf, cr = _surface()
        skin.draw(cr, anim.step(t), SIZE, SIZE)
        seen[label] = _ink(surf)

    _tour(skin, frame)
    assert seen["bloom"] and seen["submenu"] and seen["two-deep"] and seen["back-hover"] and seen["fire"]
    assert not seen["closed"]


def test_render_contact_sheet():
    out = os.environ.get("ORION_RENDER_DIR")
    if not out:
        pytest.skip("set ORION_RENDER_DIR to write PNGs")
    skin = get_skin("aurora")
    Path(out).mkdir(parents=True, exist_ok=True)

    def frame(label, anim, t):
        surf, cr = _surface()
        cr.set_source_rgb(0.04, 0.05, 0.1)  # a dark desktop behind the translucent pie
        cr.paint()
        skin.draw(cr, anim.step(t), SIZE, SIZE)
        surf.write_to_png(str(Path(out) / f"{label.replace('+', '_')}.png"))

    _tour(skin, frame)
