"""Calibrate and measure the Leap (MediaPipe) source against Leap's own tracking, live, through a guided session.

    ../.venv/bin/python scripts/leap_mp_compare.py [--hybrid] [speed] [new]   (speed 1 = ~6 min; 0.2 for a smoke run; `new` = only the newer phases)

Follow the prompts, palm down over the device unless told otherwise. It records both trackers at once, prints a report
(axis signs and scale from the three sweeps, which poses each tracker fired in each phase, hand side agreement, fingertip
differences), and saves both recordings (with the phase of every frame) next to your other recordings so thresholds can
be retuned offline.

`--hybrid` runs the Leap + MediaPipe source instead and compares the merged hands against the Leap's own (`frame.leap`).
"""

import gzip
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application"))

from orion.config import RECORDINGS_DIR, Config  # noqa: E402
from orion.frame import FINGERS, to_dict  # noqa: E402
from orion.gestures import REGISTRY, load_builtins  # noqa: E402
from orion.leap_hybrid import LeapHybridSource  # noqa: E402
from orion.leap_mp import LeapMediaPipeSource  # noqa: E402

# (phase, what to do, seconds, pose that should fire or None)
PHASES = [
    ("sweep_x", "open hand, palm down: slide it LEFT and RIGHT slowly, keeping the same height", 8, None),
    ("sweep_y", "open hand, palm down: RAISE and LOWER it slowly, staying over the device", 8, None),
    ("sweep_z", "open hand, palm down: push it AWAY from you and pull it back toward you slowly", 8, None),
    ("still", "open hand, palm down, fingers spread, held still about 20 cm above the centre of the device", 5, "open_palm"),
    ("touch_middle", "thumb tip on your MIDDLE fingertip (other fingers relaxed or straight), hold", 4, "touch_middle"),
    ("touch_ring", "thumb tip on your RING fingertip, hold", 4, "touch_ring"),
    ("touch_pinky", "thumb tip on your PINKY fingertip, hold", 4, "touch_pinky"),
    ("ok", "OK sign: thumb and INDEX fingertips together, other three fingers straight, hold", 4, "ok"),
    ("pinch", "PINCH grip: thumb and index together, other fingers curled in, hold", 4, "pinch"),
    ("peace", "peace sign (index and middle up, thumb over ring and pinky), hold", 4, "peace"),
    ("fist", "fist, hold", 4, "fist"),
    ("relaxed", "a relaxed, half-curled hand, as when you are not gesturing, hold", 4, None),
    ("tap_middle", "TAP thumb to middle fingertip, release, 4 times, pausing about a second between", 7, None),
    ("ring_left", "thumb on RING fingertip, hand over the LEFT edge of the device, hold", 4, "touch_ring"),
    ("pinky_right", "thumb on PINKY fingertip, hand over the RIGHT edge of the device, hold", 4, "touch_pinky"),
    ("away", "take BOTH hands completely out of view of the device", 4, None),
    # ── palm up ──
    ("up_open", "palm UP, open hand, fingers spread, held still about 20 cm above the device", 4, "open_palm"),
    ("up_touch_middle", "palm UP: thumb tip on your MIDDLE fingertip, hold", 4, "touch_middle"),
    ("up_touch_ring", "palm UP: thumb tip on your RING fingertip, hold", 4, "touch_ring"),
    ("up_touch_pinky", "palm UP: thumb tip on your PINKY fingertip, hold", 4, "touch_pinky"),
    ("up_ok", "palm UP: OK sign (thumb and index together, other three straight), hold", 4, "ok"),
    ("up_fist", "palm UP: fist, hold", 4, "fist"),
    # ── thumbs in line with the camera ──
    ("thumb_down", "fist, thumb pointing straight DOWN toward the device (a thumbs down), held over the device", 4, "thumbs_down"),
    # ── index pointing out ──
    ("point_out", "index finger pointing OUT away from you, other fingers curled, hand over the device", 4, None),
    ("point_up", "index finger pointing UP at the ceiling, other fingers curled, hand over the device", 4, None),
    # ── flat palm-down hand, one digit at a time pointing at the camera ──
    ("flat_thumb_down", "palm DOWN, hand open and flat: bend ONLY the THUMB down toward the device (it crosses over the palm)", 4, None),
    ("flat_index_down", "palm DOWN, hand flat: bend ONLY the INDEX finger straight down, its tip pointing at the device", 4, None),
    ("flat_middle_down", "palm DOWN, hand flat: bend ONLY the MIDDLE finger straight down, its tip pointing at the device", 4, None),
    ("flat_ring_down", "palm DOWN, hand flat: bend ONLY the RING finger straight down, its tip pointing at the device", 4, None),
    ("flat_pinky_down", "palm DOWN, hand flat: bend ONLY the PINKY straight down, its tip pointing at the device", 4, None),
    ("flat_roll", "palm DOWN, hand flat: bend thumb, index, middle, ring, pinky down one after another, then straighten them in the same order; twice", 12, None),
]
NEW = ("up_", "thumb_", "point_", "flat_")  # phases added for the hybrid; `new` on the command line runs only these (plus the sweeps and "still")
POSES = ("open_palm", "touch_middle", "touch_ring", "touch_pinky", "ok", "pinch", "peace", "fist", "thumbs_down")
SWEEP_AXIS = {"sweep_x": 0, "sweep_y": 1, "sweep_z": 2}


def fired(frames):
    """How many times each pose began over `frames`."""
    out = {}
    for name in POSES:
        g = REGISTRY[name]()
        out[name] = sum(e.phase == "begin" for f in frames for e in g.update(f))
    return out


def nearest(t, series, within=0.05):
    best = min(series, key=lambda p: abs(p[0] - t), default=None)
    return best[1] if best and abs(best[0] - t) <= within else None


def pairs_of(d):
    """(MediaPipe hand, Leap hand) seen at about the same moment."""
    out = []
    for t, f in d["mp"]:
        other = nearest(t, d["ref"])
        if f.hands and other and other.hands:
            out.append((f.hands[0], other.hands[0]))
    return out


def save(data, stamp, hybrid=False):
    """Both trackers' frames, one JSON line each with the phase it was recorded in."""
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, name in (("mp", "hybrid" if hybrid else "mediapipe"), ("ref", "leap")):
        paths[name] = RECORDINGS_DIR / f"{stamp}-calibration-{name}.orec"
        with gzip.open(paths[name], "wt") as fh:
            for phase, d in data.items():
                for _, frame in d[key]:
                    fh.write(json.dumps({**to_dict(frame), "phase": phase}) + "\n")
    return paths


def main(speed, only_new=False, hybrid=False):
    global PHASES
    if only_new:
        PHASES = [p for p in PHASES if p[0].startswith(NEW) or p[0] in ("sweep_x", "sweep_y", "sweep_z", "still")]
    load_builtins()
    cfg = Config()["leap_mp"]
    phase, data = [None], {p[0]: {"mp": [], "ref": [], "agree": []} for p in PHASES}

    def on_mp(frame):
        if phase[0]:
            now = time.monotonic()
            data[phase[0]]["mp"].append((now, frame))
            data[phase[0]]["agree"].append(src.status.get("agreement"))
            if hybrid:  # the hybrid carries the Leap's own frame with every merged one
                data[phase[0]]["ref"].append((now, frame.leap))

    def on_ref(frame):
        if phase[0]:
            data[phase[0]]["ref"].append((time.monotonic(), frame))

    if hybrid:
        src = LeapHybridSource(on_mp, lambda img: None, cfg=cfg, hybrid=Config()["leap_hybrid"])
    else:
        src = LeapMediaPipeSource(on_mp, lambda img: None, cfg=cfg)
        src.on_reference = on_ref
    src.start()
    time.sleep(3)  # connect, build the rectifier, load the model
    if src.status.get("error"):
        sys.exit(src.status["error"])
    print(f"settings: cameras={cfg['cameras']} delegate={src.status.get('delegate')} hand_mm={cfg['hand_mm']}")
    for name, prompt, seconds, _ in PHASES:
        print(f"\n>>> [{name}] {prompt}")
        for n in (3, 2, 1):
            print(f"    starting in {n}…", end="\r", flush=True)
            time.sleep(1 * max(speed, 0.34))
        print(" " * 30, end="\r")
        phase[0] = name
        time.sleep(seconds * speed)
        phase[0] = None
    src.stop()
    paths = save(data, time.strftime("%Y-%m-%d_%H-%M-%S"), hybrid)

    print("\n══════════ results ══════════")
    print("\nAxis signs and scale (MediaPipe palm vs Leap palm; slope 1.0 and correlation +1.0 are perfect)")
    for name, axis in SWEEP_AXIS.items():
        pairs = pairs_of(data[name])
        if len(pairs) < 20:
            print(f"  {name}: only {len(pairs)} paired frames, no result")
            continue
        row = []
        for a, label in enumerate("xyz"):
            mp, leap = [m.palm[a] for m, _ in pairs], [r.palm[a] for _, r in pairs]
            row.append(f"{label}: corr {np.corrcoef(mp, leap)[0, 1]:+.2f} slope {np.polyfit(leap, mp, 1)[0]:+.2f}"
                       + ("  <== the axis you moved" if a == axis else ""))
        print(f"  {name}: " + " | ".join(row))
    still = pairs_of(data["still"])
    if still:
        mp, leap = np.median([m.palm for m, _ in still], axis=0), np.median([r.palm for _, r in still], axis=0)
        print(f"  still: MediaPipe palm {mp.round(0)} mm, Leap palm {leap.round(0)} mm"
              f"  -> hand_mm {cfg['hand_mm']} would become {cfg['hand_mm'] * leap[1] / mp[1]:.0f} for matching height")
        normal = lambda hands: np.median([h.normal for h in hands], axis=0).round(2)  # noqa: E731
        print(f"  still: palm normal MediaPipe {normal([m for m, _ in still])}, Leap {normal([r for _, r in still])}"
              "  (palm down should read about [0, -1, 0] on both)")
    sides = [m.side == r.side for p in data.values() for m, r in pairs_of(p)]
    print(f"  hand side agrees: {100 * sum(sides) / max(len(sides), 1):.0f} % of {len(sides)} paired frames")

    print("\nPer phase")
    for name, _, _, want in PHASES:
        d = data[name]
        mp, ref = [f for _, f in d["mp"]], [f for _, f in d["ref"]]
        share = lambda frames: 100 * sum(bool(f.hands) for f in frames) / max(len(frames), 1)  # noqa: E731
        got_mp, got_ref = {k: v for k, v in fired(mp).items() if v}, {k: v for k, v in fired(ref).items() if v}
        verdict = ""
        if want:
            extra = sorted(set(got_mp) - {want})
            verdict = ("  MP: " + ("OK" if got_mp.get(want) == 1 else f"MISS ({got_mp.get(want, 0)}x)")
                       + (f", also fired {extra}" if extra else ""))
        print(f"[{name}] MP {len(mp)} frames, hand {share(mp):.0f} %  Leap {len(ref)} frames, hand {share(ref):.0f} %"
              f"  cameras: {dict(Counter(d['agree']))}\n    fired MP: {got_mp or 'none'}   Leap: {got_ref or 'none'}{verdict}")
        pairs = pairs_of(d)
        if pairs:
            ext = lambda hands: " ".join(f"{100 * np.mean([f in h.extended for h in hands]):3.0f}" for f in FINGERS)  # noqa: E731
            normal = lambda hands: np.median([h.normal for h in hands], axis=0).round(1)  # noqa: E731
            print(f"    extended % (thumb index middle ring pinky)   MP {ext([m for m, _ in pairs])}  |  Leap {ext([r for _, r in pairs])}"
                  f"   palm normal MP {normal([m for m, _ in pairs])} Leap {normal([r for _, r in pairs])}")
        if pairs and name not in SWEEP_AXIS:
            print("    fingertip |MP − Leap| mm (median):",
                  {FINGERS[k]: round(float(np.median([np.linalg.norm(m.fingers[k].tip - r.fingers[k].tip) for m, r in pairs])), 1)
                   for k in range(5)})
    print("\nsaved:", *(f"\n  {p}" for p in paths.values()))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a not in ("new", "--hybrid")]
    main(float(args[0]) if args else 1.0, only_new="new" in sys.argv[1:], hybrid="--hybrid" in sys.argv[1:])
