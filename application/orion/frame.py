"""Orion's own hand-tracking data model.

Everything downstream (gestures, UI, recordings, tests) uses these plain
dataclasses, never the LeapC cffi structs. Units: millimetres and seconds.
Leap coordinates: +x right, +y up (away from the device), +z toward the user.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

FINGERS = ("thumb", "index", "middle", "ring", "pinky")


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class Finger:
    name: str
    extended: bool
    joints: np.ndarray  # (5, 3): metacarpal base → fingertip

    @property
    def tip(self) -> np.ndarray:
        return self.joints[-1]

    @property
    def direction(self) -> np.ndarray:
        """Unit vector of the distal bone."""
        d = self.joints[-1] - self.joints[-2]
        return d / (np.linalg.norm(d) or 1.0)


@dataclass(slots=True)
class Hand:
    id: int
    side: str  # "left" | "right"
    confidence: float
    pinch: float  # 0..1
    grab: float  # 0..1
    palm: np.ndarray  # (3,)
    stable: np.ndarray  # (3,) jitter-filtered palm position
    velocity: np.ndarray  # (3,) mm/s
    normal: np.ndarray  # (3,) unit, out of the palm
    direction: np.ndarray  # (3,) unit, palm → fingers
    fingers: tuple[Finger, ...]

    def __getitem__(self, name: str) -> Finger:
        return self.fingers[FINGERS.index(name)]

    @property
    def extended(self) -> frozenset[str]:
        return frozenset(f.name for f in self.fingers if f.extended)


@dataclass(slots=True)
class Frame:
    t: float  # seconds (monotonic, device clock)
    fps: float = 0.0
    hands: tuple[Hand, ...] = ()
    source: str = "leap"
    leap: Frame | None = None  # the hybrid source's untouched Leap frame (its `hands` carry another tracker's fingers)

    def hand(self, side: str) -> Hand | None:
        return next((h for h in self.hands if h.side == side), None)


@dataclass(slots=True)
class IRImage:
    width: int
    height: int  # both cameras stacked vertically → height = 2 × camera height
    pixels: bytes = field(repr=False)


# ── LeapC conversion ──────────────────────────────────────────────────────────

def _v(vec) -> np.ndarray:
    return np.array((vec.x, vec.y, vec.z), dtype=np.float32)


def from_leap(event) -> Frame:
    hands = []
    for h in event.hands:
        fingers = tuple(
            Finger(name, bool(d.is_extended),
                   np.array([_v(d.bones[0].prev_joint)] + [_v(b.next_joint) for b in d.bones]))
            for name, d in zip(FINGERS, h.digits))
        hands.append(Hand(
            id=h.id, side="left" if "Left" in str(h.type) else "right",
            confidence=h.confidence, pinch=h.pinch_strength, grab=h.grab_strength,
            palm=_v(h.palm.position), stable=_v(h.palm.stabilized_position),
            velocity=_v(h.palm.velocity), normal=_v(h.palm.normal),
            direction=_v(h.palm.direction), fingers=fingers))
    return Frame(t=event.timestamp / 1e6, fps=event.framerate, hands=tuple(hands))


# ── Serialisation (recordings) ────────────────────────────────────────────────

def to_dict(f: Frame) -> dict:
    return {"t": f.t, "fps": f.fps, "hands": [{
        "id": h.id, "side": h.side, "confidence": h.confidence, "pinch": h.pinch,
        "grab": h.grab, "palm": h.palm.tolist(), "stable": h.stable.tolist(),
        "velocity": h.velocity.tolist(), "normal": h.normal.tolist(),
        "direction": h.direction.tolist(),
        "fingers": [[fi.extended, fi.joints.tolist()] for fi in h.fingers],
    } for h in f.hands]}


def from_dict(d: dict, source: str = "replay") -> Frame:
    a = lambda x: np.asarray(x, dtype=np.float32)  # noqa: E731
    hands = tuple(Hand(
        id=h["id"], side=h["side"], confidence=h["confidence"], pinch=h["pinch"],
        grab=h["grab"], palm=a(h["palm"]), stable=a(h["stable"]),
        velocity=a(h["velocity"]), normal=a(h["normal"]), direction=a(h["direction"]),
        fingers=tuple(Finger(n, e, a(j)) for n, (e, j) in zip(FINGERS, h["fingers"])),
    ) for h in d["hands"])
    return Frame(t=d["t"], fps=d["fps"], hands=hands, source=source)


# ── Binary wire format (UI stream) ────────────────────────────────────────────
# Skeleton msg: b"S" + f32[t, fps, n] + n × f32[side, conf, pinch, grab, extended-bitmask, palm·3, normal·3, joints·75]
# IR msg:       b"I" + u16[width, height] + raw 8-bit pixels

def pack_skeleton(f: Frame) -> bytes:
    parts = [b"S", struct.pack("<3f", f.t, f.fps, len(f.hands))]
    for h in f.hands:
        mask = sum(1 << i for i, fi in enumerate(h.fingers) if fi.extended)
        head = np.array((h.side == "right", h.confidence, h.pinch, h.grab, mask), np.float32)
        joints = np.stack([fi.joints for fi in h.fingers])
        parts.append(np.concatenate((head, h.palm, h.normal, joints.ravel())).astype("<f4").tobytes())
    return b"".join(parts)


def pack_ir(img: IRImage) -> bytes:
    return b"I" + struct.pack("<2H", img.width, img.height) + img.pixels
