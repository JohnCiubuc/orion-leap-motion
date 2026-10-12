"""Input emulation through a virtual uinput mouse + keyboard (works on any Wayland compositor).

Needs write access to /dev/uinput — see application/udev/71-orion-uinput.rules.
"""

from __future__ import annotations

import threading

from . import action

_dev = None
_lock = threading.Lock()
ALIAS = {"ctrl": "LEFTCTRL", "shift": "LEFTSHIFT", "alt": "LEFTALT", "super": "LEFTMETA",
         "meta": "LEFTMETA", "win": "LEFTMETA", "enter": "ENTER", "return": "ENTER", "esc": "ESC",
         "del": "DELETE", "pgup": "PAGEUP", "pgdn": "PAGEDOWN", "=": "EQUAL",
         "-": "MINUS", "plus": "EQUAL", "space": "SPACE", "play": "PLAYPAUSE"}
BUTTONS = {"left": "BTN_LEFT", "right": "BTN_RIGHT", "middle": "BTN_MIDDLE"}
_frac = [0.0, 0.0]  # sub-pixel remainder for smooth pointer motion


def device():
    """Lazily create one combined virtual device (keys + relative pointer + wheel)."""
    global _dev
    with _lock:
        if _dev is None:
            from evdev import UInput, ecodes as e
            keys = [v for k, v in vars(e).items() if k.startswith("KEY_") and isinstance(v, int) and v < 0x2ff]
            caps = {e.EV_KEY: sorted(set(keys) | {getattr(e, b) for b in BUTTONS.values()}),
                    e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL]}
            _dev = UInput(caps, name="Orion Renewal virtual input")
        return _dev


def keycode(name: str) -> int:
    from evdev import ecodes as e
    n = name.strip().lower()
    return getattr(e, "KEY_" + ALIAS.get(n, n.upper()))


def tap_keys(combo: str):
    """Press "ctrl+shift+t" style combos: hold modifiers in order, release in reverse."""
    from evdev import ecodes as e
    codes, ui = [keycode(k) for k in combo.split("+") if k], device()
    for c in codes:
        ui.write(e.EV_KEY, c, 1)
    for c in reversed(codes):
        ui.write(e.EV_KEY, c, 0)
    ui.syn()


def _button(name: str, down: bool):
    from evdev import ecodes as e
    ui = device()
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
    ui = device()
    ui.write(e.EV_REL, e.REL_HWHEEL if horizontal else e.REL_WHEEL, int(amount))
    ui.syn()


@action("input.pointer", continuous=True, gain=4.0, accel=0.15)
def pointer(ev, gain, accel):
    """Move the mouse from a (dx, dy) mm value (the `pointer` gesture). px = mm × gain × (1 + accel·|mm|)."""
    from evdev import ecodes as e
    if ev.phase != "update" or ev.value is None:
        return
    dx, dy = ev.value[0], -ev.value[1]  # Leap +y is up, screen +y is down
    k = gain * (1 + accel * (dx * dx + dy * dy) ** 0.5)
    _frac[0] += dx * k
    _frac[1] += dy * k
    mx, my = int(_frac[0]), int(_frac[1])
    _frac[0] -= mx
    _frac[1] -= my
    if mx or my:
        ui = device()
        ui.write(e.EV_REL, e.REL_X, mx)
        ui.write(e.EV_REL, e.REL_Y, my)
        ui.syn()


@action("input.type", text="")
def type_text(ev, text):
    """Type plain ASCII text."""
    for ch in text:
        k = {" ": "space", "\n": "enter", ".": "dot", ",": "comma", "/": "slash"}.get(ch, ch)
        tap_keys(("shift+" if ch.isupper() else "") + k)
