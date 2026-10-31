"""Measure the Leap (MediaPipe) source against Leap's own tracking, live, through a guided session.

    ../.venv/bin/python scripts/leap_mp_compare.py [speed]     (speed 1 = ~50 s; 0.2 for a quick smoke run)

Follow the prompts. For each phase it prints how often each tracker saw a hand, how the two cameras agreed, which poses
each tracker's frames fired, and (for held poses) how far apart the two trackers put each fingertip. The first phase
(moving the hand) also prints the correlation of the two palm tracks: a negative one means an axis sign or the camera
order in orion/leap_mp.py needs flipping.
"""

import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application"))

from orion.config import DEFAULT_FILE  # noqa: E402
from orion.frame import FINGERS  # noqa: E402
from orion.gestures import REGISTRY, load_builtins  # noqa: E402
from orion.leap_mp import LeapMediaPipeSource  # noqa: E402

PHASES = [("move", "move your open hand slowly around over the device (left/right, up/down, nearer/further)", 10),
          ("open_palm", "hold an open hand, fingers spread", 4),
          ("touch_middle", "hold your thumb on your MIDDLE fingertip", 4),
          ("touch_ring", "hold your thumb on your RING fingertip", 4),
          ("touch_pinky", "hold your thumb on your PINKY fingertip", 4),
          ("ok", "make the OK sign (thumb and index touching)", 4),
          ("peace", "make a peace sign", 4),
          ("fist", "make a fist", 4)]
POSES = ("open_palm", "touch_middle", "touch_ring", "touch_pinky", "ok", "pinch", "peace", "fist")


def fired(frames):
    """How many times each pose began over `frames`."""
    out = {}
    for name in POSES:
        g = REGISTRY[name]()
        out[name] = sum(e.phase == "begin" for f in frames for e in g.update(f))
    return out


def nearest(t, series, within=0.04):
    best = min(series, key=lambda p: abs(p[0] - t), default=None)
    return best[1] if best and abs(best[0] - t) <= within else None


def main(speed):
    load_builtins()
    cfg = tomllib.loads(DEFAULT_FILE.read_text())["leap_mp"]
    phase, data = [None], {p[0]: {"mp": [], "ref": [], "agree": []} for p in PHASES}

    def on_mp(frame):
        if phase[0]:
            data[phase[0]]["mp"].append((time.monotonic(), frame))
            data[phase[0]]["agree"].append(src.status.get("agreement"))

    def on_ref(frame):
        if phase[0]:
            data[phase[0]]["ref"].append((time.monotonic(), frame))

    src = LeapMediaPipeSource(on_mp, lambda img: None, cfg=cfg)
    src.on_reference = on_ref
    src.start()
    time.sleep(2)  # connect, build the rectifier, load the model
    if src.status.get("error"):
        sys.exit(src.status["error"])
    for name, prompt, seconds in PHASES:
        print(f"\n>>> {prompt}")
        for n in (3, 2, 1):
            print(f"    starting in {n}…", end="\r", flush=True)
            time.sleep(1 * max(speed, 0.34))
        print(" " * 30, end="\r")
        phase[0] = name
        time.sleep(seconds * speed)
        phase[0] = None
    src.stop()

    print("\n══════════ results ══════════")
    for name, prompt, _ in PHASES:
        d = data[name]
        mp, ref = [f for _, f in d["mp"]], [f for _, f in d["ref"]]
        share = lambda frames: 100 * sum(bool(f.hands) for f in frames) / max(len(frames), 1)  # noqa: E731
        agree = Counter(d["agree"])
        print(f"\n[{name}]  MediaPipe: {len(mp)} frames, hand in {share(mp):.0f} %   Leap: {len(ref)} frames, hand in {share(ref):.0f} %")
        print("  cameras:", ", ".join(f"{k} {100 * v / max(len(mp), 1):.0f} %" for k, v in agree.most_common()))
        print("  poses fired  MediaPipe:", {k: v for k, v in fired(mp).items() if v} or "none",
              "  Leap:", {k: v for k, v in fired(ref).items() if v} or "none")
        pairs = []  # (MediaPipe hand, Leap hand) seen at about the same moment
        for t, f in d["mp"]:
            other = nearest(t, d["ref"])
            if f.hands and other and other.hands:
                pairs.append((f.hands[0], other.hands[0]))
        if not pairs:
            continue
        print(f"  hand side agrees: {100 * sum(m.side == r.side for m, r in pairs) / len(pairs):.0f} % of {len(pairs)} paired frames")
        if name == "move":
            for axis, label in enumerate("xyz"):
                a, b = [m.palm[axis] for m, _ in pairs], [r.palm[axis] for _, r in pairs]
                print(f"  palm {label} correlation: {np.corrcoef(a, b)[0, 1]:+.2f}")
        else:
            print("  fingertip |MediaPipe − Leap| mm (median):",
                  {FINGERS[k]: round(float(np.median([np.linalg.norm(m.fingers[k].tip - r.fingers[k].tip) for m, r in pairs])), 1)
                   for k in range(5)})


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 1.0)
