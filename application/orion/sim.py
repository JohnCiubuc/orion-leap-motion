"""Synthetic hands — for the demo source (UI work without a device) and tests."""

from __future__ import annotations

import math

import numpy as np

from .frame import FINGERS, Finger, Frame, Hand

BONES = {"thumb": (0, 46, 32, 24), "index": (68, 40, 24, 18), "middle": (64, 45, 28, 19),
         "ring": (58, 42, 27, 18), "pinky": (54, 33, 19, 16)}
OFFSET = {"thumb": -0.4, "index": -0.25, "middle": 0.0, "ring": 0.22, "pinky": 0.42}  # × palm width


def _unit(v) -> np.ndarray:
    v = np.asarray(v, np.float32)
    return v / (np.linalg.norm(v) or 1.0)


def make_hand(side="right", palm=(0, 200, 0), extended=FINGERS, normal=(0, -1, 0),
              direction=(0, 0, -1), pinch=0.0, grab=None, velocity=(0, 0, 0),
              thumb=None, hid=None) -> Hand:
    """Build a plausible hand. `thumb` overrides the extended thumb's pointing direction."""
    palm, n, d = np.asarray(palm, np.float32), _unit(normal), _unit(direction)
    lat = _unit(np.cross(d, n) if side == "right" else np.cross(n, d))  # toward the thumb
    fingers = []
    for name in FINGERS:
        ext = name in extended
        lens = BONES[name]
        if name == "thumb":
            base = palm - lat * 25 + d * 10
            aim = _unit(thumb) if thumb is not None else _unit(lat * 0.8 + d * 0.6)
            dirs = [aim] * 3 if ext else [_unit(lat * 0.3 + d * 0.5 + n * 0.5), _unit(d * 0.5 - lat * 0.6), -lat]
        else:
            base = palm - lat * OFFSET[name] * 85 - d * 40
            dirs = [d] * 3 if ext else [_unit(d * 0.7 + n * 0.7), _unit(n - d * 0.6), -d]
        pts = [base, base + d * lens[0]]
        for seg, v in zip(lens[1:], dirs):
            pts.append(pts[-1] + v * seg)
        fingers.append(Finger(name, ext, np.array(pts, np.float32)))
    g = (5 - len(extended)) / 5 if grab is None else grab
    return Hand(hid if hid is not None else (1 if side == "right" else 2), side, 0.9, pinch, g,
                palm, palm.copy(), np.asarray(velocity, np.float32), n, d, tuple(fingers))


# ── Demo choreography: cycles through poses and motions ───────────────────────

SCENES = [  # (seconds, label)
    (3, "open"), (2.5, "thumbs_up"), (2.5, "ok"), (4, "circle"), (3, "swipe"), (4, "zoom"), (4, "pinch_joy"),
]


def demo_frame(t: float) -> Frame:
    period = sum(s for s, _ in SCENES)
    k, acc = t % period, 0.0
    for dur, label in SCENES:
        if k < acc + dur:
            p = (k - acc) / dur
            break
        acc += dur
    bob = math.sin(t * 1.3) * 12
    if label == "thumbs_up":
        hands = [make_hand(palm=(40, 210 + bob, 0), extended={"thumb"}, normal=(-1, 0, 0), thumb=(0, 1, 0))]
    elif label == "ok":
        hands = [make_hand(palm=(30, 220 + bob, 0), extended={"middle", "ring", "pinky"}, pinch=0.95)]
    elif label == "circle":
        a = p * 2 * math.pi * 1.5
        hands = [make_hand(palm=(math.cos(a) * 70, 230 + math.sin(a) * 70, -10), extended={"index"})]
    elif label == "swipe":
        x = -120 + 240 * min(1.0, p * 1.6)
        hands = [make_hand(palm=(x, 200, 0), velocity=(900 if p < 0.6 else 0, 0, 0))]
    elif label == "zoom":
        s = 60 + 50 * math.sin(p * math.pi)
        hands = [make_hand("left", (-s, 210, 0), set(FINGERS) - {"index"}, pinch=0.9),
                 make_hand("right", (s, 210, 0), set(FINGERS) - {"index"}, pinch=0.9)]
    elif label == "pinch_joy":  # pinch, then lift slowly (scrolls up, faster and faster)
        hands = [make_hand(palm=(20, 190 + 90 * min(1.0, max(0.0, p - 0.1) * 1.4), 0), extended={"middle", "ring", "pinky"},
                           pinch=0.95 if p > 0.08 else 0.1)]  # release first, so the anchor is set here
    else:
        hands = [make_hand(palm=(math.sin(t) * 50, 200 + bob, math.cos(t * 0.7) * 30))]
    return Frame(t=t, fps=110.0, hands=tuple(hands), source="demo")


def demo_ir(t: float, w=640, h=240) -> bytes:
    """Two stacked fake IR frames: noisy dark background with a bright moving blob."""
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = w / 2 + math.sin(t) * 150, h / 2 + math.cos(t * 1.3) * 40
    blob = np.exp(-(((xx - cx) / 70) ** 2 + ((yy - cy) / 55) ** 2)) * 220
    img = np.clip(blob + np.random.randint(0, 25, (h, w)), 0, 255).astype(np.uint8)
    return np.vstack((img, np.roll(img, -18, axis=1))).tobytes()
