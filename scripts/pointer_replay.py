#!/usr/bin/env python3
"""Replay a recording through the desktop pointer and print jitter/jump/edge metrics as JSON.
Usage: pointer_replay.py FILE.orec [key=value ...]   (key=value overrides gesture settings)"""
import gzip
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application"))
from orion.frame import from_dict  # noqa: E402
from orion.gestures import REGISTRY, load_builtins  # noqa: E402

SCREEN = np.array([3840.0, 2160.0])
EDGE_EPS = 1e-3  # the glide onto a limit is asymptotic, so "hit" means within 0.1 % of it
REST_SPEED = 20.0  # mm/s: palm slower than this counts as resting


def metrics(frames, overrides=None):
    load_builtins()
    g = REGISTRY["desktop_pointer"](overrides)
    pts, speeds, prev = [], [], None
    for f in frames:
        evs = [e for e in g.update(f) if e.value is not None]
        palm = f.hands[0].palm if f.hands else None
        if evs:
            pts.append(np.asarray(evs[-1].value[:2], float))
            speeds.append(np.linalg.norm(palm - prev[1]) / max(f.t - prev[0], 1e-6) if prev and palm is not None else np.inf)
        prev = (f.t, palm) if palm is not None else None
    uv = np.array(pts).reshape(-1, 2)
    step = np.linalg.norm(np.diff(uv, axis=0) * SCREEN, axis=1)
    rest = step[np.array(speeds[1:]) < REST_SPEED] if len(step) else step
    return {
        "rest_jitter_px": float(np.sqrt(np.mean(rest ** 2))) if len(rest) else 0.0,
        "max_jump_px": float(step.max()) if len(step) else 0.0,
        "reached_edges": {n: bool(len(uv) and (uv[:, i].min() <= EDGE_EPS if n in ("left", "top") else uv[:, i].max() >= 1 - EDGE_EPS))
                          for n, i in (("left", 0), ("right", 0), ("top", 1), ("bottom", 1))},
    }


if __name__ == "__main__":
    frames = [from_dict(json.loads(line)) for line in gzip.open(sys.argv[1], "rt")]
    ov = {k: float(v) for k, v in (a.split("=", 1) for a in sys.argv[2:])}
    print(json.dumps(metrics(frames, ov), indent=2))
