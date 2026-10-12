"""Temporal gestures over a short window of hand history (see Track)."""

import numpy as np

from . import motion


@motion("swipe", window=0.25, cooldown=0.6, variants=("left", "right", "up", "down"),
        distance=(110, 40, 300), open_hand=(1, 0, 1))
def swipe(tr, p):
    """Fast open-hand palm movement along one axis."""
    if p["open_hand"] and len(tr.hands[-1].extended) < 4:
        return None
    d = tr.palm[-1] - tr.palm[0]
    dx, dy = d[0], d[1]
    if max(abs(dx), abs(dy)) < p["distance"]:
        return None
    if abs(dx) > 1.5 * abs(dy):
        return "right" if dx > 0 else "left"
    if abs(dy) > 1.5 * abs(dx):
        return "up" if dy > 0 else "down"
    return None


@motion("palm_flip", window=0.8, cooldown=0.8, variants=("up", "down"), threshold=(0.6, 0.3, 0.95))
def palm_flip(tr, p):
    """Palm turned over: "up" = now facing up, "down" = now facing down."""
    a, b, k = tr.normal[0][1], tr.normal[-1][1], p["threshold"]
    if a < -k and b > k:
        return "up"
    if a > k and b < -k:
        return "down"
    return None


@motion("tap", window=0.15, cooldown=0.35, depth=(12, 4, 40), still=(8, 2, 30))
def tap(tr, p):
    """Quick downward index-finger tap while the palm stays still."""
    if "index" not in tr.hands[0].extended:
        return None
    drop = tr.tip("index")[0][1] - tr.tip("index")[:, 1].min()
    palm_move = np.linalg.norm(tr.palm[-1] - tr.palm[0])
    return drop > p["depth"] and palm_move < p["still"]
