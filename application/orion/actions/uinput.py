"""Input emulation through virtual uinput devices (works on any Wayland compositor).

Needs write access to /dev/uinput — see application/udev/71-orion-uinput.rules.
"""

from __future__ import annotations

import math
import threading

from . import action

_kbd = _mouse = _abs = None
_lock = threading.Lock()
ALIAS = {"ctrl": "LEFTCTRL", "shift": "LEFTSHIFT", "alt": "LEFTALT", "super": "LEFTMETA",
         "meta": "LEFTMETA", "win": "LEFTMETA", "enter": "ENTER", "return": "ENTER", "esc": "ESC",
         "del": "DELETE", "pgup": "PAGEUP", "pgdn": "PAGEDOWN", "=": "EQUAL",
         "-": "MINUS", "plus": "EQUAL", "space": "SPACE", "play": "PLAYPAUSE"}
BUTTONS = {"left": "BTN_LEFT", "right": "BTN_RIGHT", "middle": "BTN_MIDDLE"}
_frac = [0.0, 0.0]  # sub-pixel remainder for smooth pointer motion
ABS_MAX = 32767  # desktop pointer resolution: the compositor scales 0…ABS_MAX onto the desktop
status = "not started"  # shown in Settings → Input emulation


# ── Virtual devices: a plain keyboard, a plain mouse, an absolute pointer ────
# Separate devices: a single node mixing a full keyboard with pointer axes can be
# classified as a keyboard only, and then libinput/Hyprland ignore its motion.
# The absolute pointer (ABS_X/Y + buttons, like a VM tablet) is classed as a mouse with
# absolute motion; Hyprland maps its range onto the whole layout, every monitor.

def _create():
    global _kbd, _mouse, _abs, status
    from evdev import AbsInfo, UInput, ecodes as e
    keys = sorted({v for k, v in vars(e).items() if k.startswith("KEY_") and isinstance(v, int) and v < 0x100})
    _kbd = UInput({e.EV_KEY: keys}, name="Orion Renewal keyboard")
    _mouse = UInput({e.EV_KEY: [getattr(e, b) for b in BUTTONS.values()],
                     e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL]}, name="Orion Renewal mouse")
    axis = AbsInfo(value=ABS_MAX // 2, min=0, max=ABS_MAX, fuzz=0, flat=0, resolution=0)
    _abs = UInput({e.EV_KEY: [getattr(e, b) for b in BUTTONS.values()],
                   e.EV_ABS: [(e.ABS_X, axis), (e.ABS_Y, axis)]}, name="Orion Renewal desktop pointer")
    status = "ready"


def warmup() -> str:
    """Create the devices at startup: the compositor needs a moment to pick up a new device,
    and a missing permission should show up in Settings, not on the first gesture."""
    global status
    with _lock:
        if _mouse is None:
            try:
                _create()
            except Exception as ex:  # evdev reports both cases as UInputError; tell them apart by message
                msg = str(ex).lower()
                status = ("/dev/uinput missing: sudo modprobe uinput" if "not exist" in msg or "no such" in msg
                          else "no permission for /dev/uinput: run application/setup.sh (udev rule), then log out and in"
                          if "writ" in msg or "permission" in msg else f"failed: {ex}")
    return status


def keyboard():
    if _kbd is None and warmup() != "ready":
        raise RuntimeError(status)
    return _kbd


def mouse():
    if _mouse is None and warmup() != "ready":
        raise RuntimeError(status)
    return _mouse


def absolute():
    if _abs is None and warmup() != "ready":
        raise RuntimeError(status)
    return _abs


def keycode(name: str) -> int:
    from evdev import ecodes as e
    n = name.strip().lower()
    return getattr(e, "KEY_" + ALIAS.get(n, n.upper()))


def tap_keys(combo: str):
    """Press "ctrl+shift+t" style combos: hold modifiers in order, release in reverse."""
    from evdev import ecodes as e
    codes, ui = [keycode(k) for k in combo.split("+") if k], keyboard()
    for c in codes:
        ui.write(e.EV_KEY, c, 1)
    for c in reversed(codes):
        ui.write(e.EV_KEY, c, 0)
    ui.syn()


def _button(name: str, down: bool):
    from evdev import ecodes as e
    ui = mouse()
    ui.write(e.EV_KEY, getattr(e, BUTTONS[name]), int(down))
    ui.syn()


# ── Actions ───────────────────────────────────────────────────────────────────

@action("input.keys", combo="ctrl+c")
def keys(ev, combo):
    """Press a key combination, e.g. ctrl+shift+t, super+1, F5."""
    tap_keys(combo)


@action("input.click", button="left", choices={"button": list(BUTTONS)})
def click(ev, button):
    """Click a mouse button."""
    _button(button, True)
    _button(button, False)


@action("input.button", continuous=True, button="left", choices={"button": list(BUTTONS)})
def button(ev, button):
    """Hold a mouse button for the gesture's duration (press on begin, release on end) — drag & drop."""
    if ev.phase in ("begin", "end"):
        _button(button, ev.phase == "begin")


@action("input.scroll", amount=3, horizontal=False)
def scroll(ev, amount, horizontal):
    """Scroll the wheel by `amount` notches (negative = down/left)."""
    from evdev import ecodes as e
    ui = mouse()
    ui.write(e.EV_REL, e.REL_HWHEEL if horizontal else e.REL_WHEEL, int(amount))
    ui.syn()


def pointer_gain(speed, gain, accel, still):
    """px per mm at hand `speed` (mm/frame): ~0 below `still` (cubic fade-in keeps a resting hand
    dead still), `gain` through the middle, then exponential in speed (capped at e³ ≈ 20×)."""
    return gain * math.exp(min(accel * speed, 3.0)) * speed * speed / (speed * speed + still * still)


@action("input.pointer", continuous=True, gain=4.0, accel=0.15, still=0.1)
def pointer(ev, gain, accel, still):
    """Move the mouse from a (dx, dy) mm value (the `pointer` gesture). Three zones by hand speed:
    below `still` mm/frame the cursor barely moves, then px = mm × gain, then it ramps up
    exponentially (×e^(accel·speed)) for fast sweeps."""
    from evdev import ecodes as e
    if ev.phase != "update" or ev.value is None:
        return
    dx, dy = ev.value[0], -ev.value[1]  # Leap +y is up, screen +y is down
    k = pointer_gain(math.hypot(dx, dy), gain, accel, still)
    _frac[0] += dx * k
    _frac[1] += dy * k
    mx, my = int(_frac[0]), int(_frac[1])
    _frac[0] -= mx
    _frac[1] -= my
    if mx or my:
        ui = mouse()
        ui.write(e.EV_REL, e.REL_X, mx)
        ui.write(e.EV_REL, e.REL_Y, my)
        ui.syn()


@action("input.desktop", continuous=True, display="")
def desktop(ev, display):
    """Put the cursor where the hand is: a (u, v) 0…1 value (the `desktop_pointer` gesture) spans the
    whole desktop, or only `display` (a Hyprland monitor name such as DP-3), so the cursor reaches the
    screen edges before the hand leaves the controller's view."""
    from evdev import ecodes as e
    if ev.phase not in ("begin", "update") or ev.value is None:
        return
    if ev.phase == "begin" or _area[0] != display:  # monitors only change between holds
        _area[:] = [display, _display_area(display) if display else (0.0, 0.0, 1.0, 1.0)]
    x, y, w, h = _area[1]
    ui = absolute()
    ui.write(e.EV_ABS, e.ABS_X, round((x + float(ev.value[0]) * w) * ABS_MAX))
    ui.write(e.EV_ABS, e.ABS_Y, round((y + float(ev.value[1]) * h) * ABS_MAX))
    ui.syn()


_area = [None, (0.0, 0.0, 1.0, 1.0)]  # (display, its box as a fraction of the layout)


def _display_area(name: str) -> tuple:
    """`name`'s box as a fraction of the bounding box of all monitors (what Hyprland maps the device onto)."""
    import json
    from .hyprland import hyprctl
    boxes = {}
    for m in json.loads(hyprctl("j/monitors")):
        w, h = m["width"] / m["scale"], m["height"] / m["scale"]
        boxes[m["name"]] = (m["x"], m["y"], *((h, w) if m.get("transform", 0) % 2 else (w, h)))
    if name not in boxes:
        raise RuntimeError(f"no display {name!r} (have {', '.join(boxes)})")
    x0, y0 = min(b[0] for b in boxes.values()), min(b[1] for b in boxes.values())
    W = max(b[0] + b[2] for b in boxes.values()) - x0
    H = max(b[1] + b[3] for b in boxes.values()) - y0
    x, y, w, h = boxes[name]
    return (x - x0) / W, (y - y0) / H, w / W, h / H


@action("input.center", display="")
def center(ev, display):
    """Jump the cursor to the middle of a display: `display` (a Hyprland monitor name such as DP-3),
    or the focused one when blank. Handy as a mode's on_enter."""
    import json
    from evdev import ecodes as e
    from .hyprland import hyprctl
    if not display:
        display = next((m["name"] for m in json.loads(hyprctl("j/monitors")) if m.get("focused")), "")
        if not display:
            raise RuntimeError("no focused display")
    x, y, w, h = _display_area(display)
    ui = absolute()
    tx, ty = round((x + w / 2) * ABS_MAX), round((y + h / 2) * ABS_MAX)
    # The kernel drops an ABS event equal to the device's last value, and the cursor may have moved
    # (relative pointer) since we last centered, so step off the target first.
    ui.write(e.EV_ABS, e.ABS_X, tx - 1)
    ui.write(e.EV_ABS, e.ABS_Y, ty - 1)
    ui.syn()
    ui.write(e.EV_ABS, e.ABS_X, tx)
    ui.write(e.EV_ABS, e.ABS_Y, ty)
    ui.syn()


@action("input.type", text="")
def type_text(ev, text):
    """Type plain ASCII text."""
    for ch in text:
        k = {" ": "space", "\n": "enter", ".": "dot", ",": "comma", "/": "slash"}.get(ch, ch)
        tap_keys(("shift+" if ch.isupper() else "") + k)


@action("input.test_pointer", size=60)
def test_pointer(ev, size):
    """Trace a small square with the cursor: checks mouse emulation without any tracking involved."""
    import time
    from evdev import ecodes as e
    ui = mouse()
    for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
        for _ in range(20):
            ui.write(e.EV_REL, e.REL_X, dx * size // 20)
            ui.write(e.EV_REL, e.REL_Y, dy * size // 20)
            ui.syn()
            time.sleep(0.01)
