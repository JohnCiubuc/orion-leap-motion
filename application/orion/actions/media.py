"""MPRIS media control over the session D-Bus (Spotify, browsers, mpv, …)."""

from __future__ import annotations

from jeepney import DBusAddress, MessageType, Properties, new_method_call
from jeepney.io.blocking import open_dbus_connection

from . import action

OPS = ["PlayPause", "Play", "Pause", "Next", "Previous", "Stop"]
PATH, IFACE = "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player"
_bus = None


def _call(msg):
    global _bus
    if _bus is None:
        _bus = open_dbus_connection(bus="SESSION")
    reply = _bus.send_and_get_reply(msg, timeout=1)
    if reply.header.message_type == MessageType.error:
        raise RuntimeError(reply.body[0] if reply.body else "D-Bus error")
    return reply.body


def players() -> list[str]:
    dbus = DBusAddress("/org/freedesktop/DBus", "org.freedesktop.DBus", "org.freedesktop.DBus")
    return [n for n in _call(new_method_call(dbus, "ListNames"))[0] if n.startswith("org.mpris.MediaPlayer2.")]


def pick(hint: str = "") -> DBusAddress:
    """Player whose bus name contains `hint`, else the one playing, else the first."""
    names = players()
    if not names:
        raise RuntimeError("no MPRIS player running")
    if hint:
        names = [n for n in names if hint.lower() in n.lower()] or names
    addr = lambda n: DBusAddress(PATH, n, IFACE)  # noqa: E731
    for n in names:
        try:
            if _call(Properties(addr(n)).get("PlaybackStatus"))[0][1] == "Playing":
                return addr(n)
        except RuntimeError:
            pass
    return addr(names[0])


@action("media", op="PlayPause", player="", choices={"op": OPS})
def media(ev, op, player):
    """Play/pause/next/previous on an MPRIS player. `player` filters by name (e.g. "spotify")."""
    _call(new_method_call(pick(player), op))


@action("media.seek", seconds=10, player="")
def seek(ev, seconds, player):
    """Seek forward (or back, if negative) by `seconds`."""
    _call(new_method_call(pick(player), "Seek", "x", (int(seconds * 1e6),)))
