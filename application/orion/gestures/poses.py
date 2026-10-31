"""Static hand poses. Each is a predicate over a single Hand."""

from . import pose
from .fingers import pinch_strength, thumb_touch

FOUR = {"index", "middle", "ring", "pinky"}


@pose("thumbs_down", hold=0.3, min_down=(0.6, 0.2, 1.0))
def thumbs_down(h, p):
    """Fist with the thumb pointing down."""
    return h.extended == {"thumb"} and h["thumb"].direction[1] < -p["min_down"]


@pose("ok", hold=0.8, pinch=(0.75, 0.3, 1.0), still=(60, 10, 300))
def ok(h, p):
    """Thumb and index touching, other three fingers extended, hand held still (so pinch-scrolling isn't OK)."""
    return (pinch_strength(h) > p["pinch"] and {"middle", "ring", "pinky"} <= h.extended
            and float((h.velocity ** 2).sum()) ** 0.5 < p["still"])


@pose("fist", hold=0.3, grab=(0.9, 0.5, 1.0))
def fist(h, p):
    """All fingers closed."""
    return h.grab > p["grab"] and not (h.extended & FOUR)


@pose("open_palm", hold=0.3, grab=(0.2, 0.0, 0.6))
def open_palm(h, p):
    """All five fingers spread."""
    return len(h.extended) == 5 and h.grab < p["grab"]


@pose("peace", hold=0.3)
def peace(h, p):
    """Index and middle extended (V sign)."""
    return h.extended & FOUR == {"index", "middle"}


@pose("pinch", hold=0.0, strength=(0.85, 0.3, 1.0))
def pinch(h, p):
    """Thumb–index pinch (instant). Pairs with input.button for click-and-drag."""
    return pinch_strength(h) > p["strength"]


@pose("engage", hold=0.5, facing=(0.6, 0.2, 1.0))
def engage(h, p):
    """Open palm facing the screen ("stop" sign). Arms the next gesture when engage is required."""
    return len(h.extended) >= 4 and h.normal[2] < -p["facing"]


def _touch(finger):
    def check(h, p):
        return thumb_touch(h) == finger and float((h.velocity ** 2).sum()) ** 0.5 < p["still"]
    check.__doc__ = f"Thumb tip touching the {finger} fingertip, hand held still. Not a fist or a peace sign."
    return check


for _f in ("middle", "ring", "pinky"):
    pose(f"touch_{_f}", hold=0.25, still=(60, 10, 300))(_touch(_f))
