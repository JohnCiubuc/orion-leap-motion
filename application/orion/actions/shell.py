"""Escape hatch: run anything."""

from __future__ import annotations

import subprocess

from . import action


@action("shell", cmd="notify-send Orion 'Hello from a gesture'")
def shell(ev, cmd):
    """Run a shell command (detached). $ORION_GESTURE / $ORION_VALUE are set."""
    import os
    env = {**os.environ, "ORION_GESTURE": ev.name, "ORION_VALUE": str(ev.value)}
    subprocess.Popen(cmd, shell=True, env=env, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@action("notify", title="Orion", body="{gesture}")
def notify(ev, title, body):
    """Desktop notification. {gesture} and {value} are substituted."""
    text = body.format(gesture=ev.name, value=ev.value)
    subprocess.Popen(["notify-send", "-a", "Orion Renewal", title, text], start_new_session=True)
