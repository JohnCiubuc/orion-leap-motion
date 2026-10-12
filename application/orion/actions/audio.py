"""System volume through PipeWire's wpctl."""

from __future__ import annotations

import subprocess

from . import action

SINK = "@DEFAULT_AUDIO_SINK@"
_base = {"vol": 0.5}


def _wpctl(*args) -> str:
    return subprocess.run(["wpctl", *args], capture_output=True, text=True, check=True).stdout


def get_volume() -> float:
    return float(_wpctl("get-volume", SINK).split()[1])  # "Volume: 0.42 [MUTED]"


@action("audio.volume", step=5)
def volume(ev, step):
    """Change volume by `step` percent (negative = quieter)."""
    _wpctl("set-volume", "-l", "1.0", SINK, f"{abs(step)}%{'+' if step > 0 else '-'}")


@action("audio.mute")
def mute(ev):
    """Toggle mute."""
    _wpctl("set-mute", SINK, "toggle")


@action("audio.dial", continuous=True, per_degree=0.4)
def dial(ev, per_degree):
    """Volume knob for continuous gestures (e.g. rotate): value in degrees × per_degree = % change."""
    if ev.phase == "begin":
        _base["vol"] = get_volume()
    elif ev.phase == "update":
        v = min(1.0, max(0.0, _base["vol"] + float(ev.value) * per_degree / 100))
        _wpctl("set-volume", SINK, f"{v:.3f}")
