"""Spatial gestures: shapes drawn in the air with the index finger.

Point with the index finger (others curled) to draw; relax to finish the
stroke. Strokes are matched with the $P point-cloud recogniser (ignores
drawing direction and start point) plus a "cornerness" term that separates
round shapes from angular ones. New shapes need no code — record a
template from the UI (stored in templates.json).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from . import Gesture, GestureEvent, SIDES, register

N = 32  # resample size


# ── $P recogniser ─────────────────────────────────────────────────────────────

def _resample(pts: np.ndarray, n=N) -> np.ndarray:
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate(([0], np.cumsum(seg)))
    at = np.linspace(0, cum[-1], n)
    return np.column_stack([np.interp(at, cum, pts[:, i]) for i in range(2)])


def _smooth(p: np.ndarray, k=5) -> np.ndarray:
    ker = np.ones(k) / k
    return np.column_stack([np.convolve(np.pad(p[:, i], k // 2, "edge"), ker, "valid") for i in range(2)])


def _cornerness(p: np.ndarray, n=20) -> float:
    """Share of total turning in the 4 sharpest bends: ~0.25 circle, ~0.8+ polygon."""
    d = np.diff(_resample(p, n), axis=0)
    turn = np.abs((np.diff(np.arctan2(d[:, 1], d[:, 0])) + np.pi) % (2 * np.pi) - np.pi)
    return float(np.sort(turn)[-4:].sum() / (turn.sum() or 1.0))


def normalize(pts) -> tuple[np.ndarray, float]:
    """Stroke → (centred unit-scale point cloud, cornerness)."""
    raw = _smooth(np.asarray(pts, np.float64))
    p = _resample(raw)
    p = (p - p.min(0)) / (np.ptp(p, 0).max() or 1.0)
    return p - p.mean(0), _cornerness(raw)


def _cloud(d: np.ndarray, start: int) -> float:
    n, used, total = len(d), np.zeros(len(d), bool), 0.0
    for k in range(n):
        i = (start + k) % n
        row = np.where(used, np.inf, d[i])
        j = int(row.argmin())
        used[j] = True
        total += (1 - k / n) * row[j]
    return total


def distance(a, b) -> float:
    (pa, ca), (pb, cb) = a, b
    d = np.linalg.norm(pa[:, None] - pb[None], axis=2)
    cloud = min(min(_cloud(d, s), _cloud(d.T, s)) for s in range(0, N, int(N ** 0.5)))
    return cloud + 2.0 * abs(ca - cb)


def _poly(*corners, n=90):
    return _resample(np.array(corners, float), n)


BUILTIN = {
    "circle": [np.column_stack((np.cos(a), np.sin(a))) for a in [np.linspace(0, 2 * math.pi, 90)]],
    "square": [_poly((0, 0), (1, 0), (1, 1), (0, 1), (0, 0))],
    "triangle": [_poly((0, 0), (1, 0), (0.5, 0.87), (0, 0))],
    "z": [_poly((0, 1), (1, 1), (0, 0), (1, 0))],
}


# ── Gesture ───────────────────────────────────────────────────────────────────

@register
class PathGesture(Gesture):
    name, family = "path", "path"
    doc = __doc__
    params = {"min_length": (120, 40, 400), "threshold": (0.5, 0.2, 0.95)}
    templates: dict[str, list[tuple]] = {k: [normalize(t) for t in v] for k, v in BUILTIN.items()}
    user_file: Path | None = None

    def __init__(self, overrides=None):
        super().__init__(overrides)
        self.stroke = {s: [] for s in SIDES}
        self.capture: str | None = None  # name to save the next stroke under

    @classmethod
    def events(cls):
        return [f"path.{k}" for k in cls.templates]

    @classmethod
    def load_user(cls, path: Path):
        cls.user_file = Path(path)
        if cls.user_file.exists():
            for name, samples in json.loads(cls.user_file.read_text()).items():
                cls.templates.setdefault(name, []).extend(normalize(s) for s in samples)

    @classmethod
    def save_user(cls, name: str, pts: np.ndarray):
        cls.templates.setdefault(name, []).append(normalize(pts))
        if cls.user_file:
            data = json.loads(cls.user_file.read_text()) if cls.user_file.exists() else {}
            data.setdefault(name, []).append(np.round(pts, 1).tolist())
            cls.user_file.parent.mkdir(parents=True, exist_ok=True)
            cls.user_file.write_text(json.dumps(data))

    @classmethod
    def recognize(cls, pts) -> tuple[str, float]:
        q = normalize(pts)
        best = min(((distance(q, t), k) for k, ts in cls.templates.items() for t in ts), default=(9, ""))
        return best[1], max(0.0, 1.0 - best[0] / 3.0)

    def update(self, frame):
        for side in SIDES:
            h = frame.hand(side)
            if h is not None and h.extended - {"thumb"} == {"index"}:
                self.stroke[side].append(h["index"].tip[:2].copy())  # x/y plane, facing the user
            elif self.stroke[side]:
                yield from self._finish(side, frame.t)

    def _finish(self, side, t):
        pts, self.stroke[side] = np.array(self.stroke[side]), []
        if len(pts) < 8 or np.linalg.norm(np.diff(pts, axis=0), axis=1).sum() < self.p["min_length"]:
            return
        if self.capture:
            name, self.capture = self.capture, None
            self.save_user(name, pts)
            yield GestureEvent("path.recorded", "fire", name, side, t)
            return
        name, score = self.recognize(pts)
        if score >= self.p["threshold"]:
            yield GestureEvent(f"path.{name}", "fire", round(score, 3), side, t)
