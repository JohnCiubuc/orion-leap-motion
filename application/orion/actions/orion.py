"""Actions that control Orion itself (always allowed through, even in exclusive modes)."""

from . import CTX, action


@action("orion.mode", mode="air_mouse", state="toggle", choices={"state": ["toggle", "on", "off"]})
def mode(ev, mode, state):
    """Turn a mode (a group of bindings, e.g. air_mouse) on/off."""
    CTX["engine"].set_mode(mode, None if state == "toggle" else state == "on")


@action("orion.pause")
def pause(ev):
    """Pause / resume all gesture actions."""
    e = CTX["engine"]
    e.set_paused(not e.router.paused)


@action("orion.record_shape", name="my_shape")
def record_shape(ev, name):
    """Save the next drawn stroke as a new path template called `name`."""
    CTX["engine"].capture_path(name)


@action("orion.restart_device", service=False)
def restart_device(ev, service):
    """Wake the Leap controller (unpause + USB reset). `service` restarts the tracking service instead."""
    CTX["engine"].restart_device(service=service)
