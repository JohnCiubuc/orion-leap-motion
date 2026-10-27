"""Gesture overlay: a small translucent card in a corner of the focused monitor.

Runs as its own process under the *system* Python (needs python-gobject + gtk4-layer-shell
from pacman, not the venv), started by orion/overlay.py with LD_PRELOAD set for the
layer-shell library. Reads JSON lines on stdin:
    {"type": "config", "opacity": .85, "seconds": 1.6, "corner": "top-right", "margin": 16}
    {"type": "show", "title": "Swipe left", "detail": "hypr.dispatch", "hand": "right", "key": "…"}

It is a wlr-layer-shell surface, not a window: Hyprland never tiles, focuses or lists it,
it takes no keyboard focus and clicks pass straight through it.
"""

import json
import os
import socket
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell as LS  # noqa: E402

CSS = """
window { background: transparent; }
.card { background: rgba(14, 19, 42, 0.86); border: 1px solid rgba(80, 98, 170, 0.45);
        border-radius: 14px; padding: 12px 16px 12px 14px; box-shadow: 0 8px 28px rgba(0,0,0,.45); }
.bar { border-radius: 3px; min-width: 3px; background: #8fc7ff; }
.bar.right { background: #ffa463; }
.bar.none { background: #8a93b8; }
.title { font-family: "Sora", "IBM Plex Sans", sans-serif; font-weight: 600; font-size: 15px; color: #e6ecff; }
.detail { font-family: "IBM Plex Sans", sans-serif; font-size: 12px; color: #8a93b8; }
"""
EDGES = {"top-right": ("TOP", "RIGHT"), "top-left": ("TOP", "LEFT"),
         "bottom-right": ("BOTTOM", "RIGHT"), "bottom-left": ("BOTTOM", "LEFT")}


# ── Focused monitor (Hyprland IPC; elsewhere the compositor picks) ───────────

def focused_connector():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        return None
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.connect(f"{os.environ.get('XDG_RUNTIME_DIR', '/tmp')}/hypr/{sig}/.socket.sock")
            s.sendall(b"j/monitors")
            data = b"".join(iter(lambda: s.recv(65536), b""))
        return next((m["name"] for m in json.loads(data) if m.get("focused")), None)
    except Exception:
        return None


def gdk_monitor(connector):
    monitors = Gdk.Display.get_default().get_monitors()
    for i in range(monitors.get_n_items()):
        m = monitors.get_item(i)
        if m.get_connector() == connector:
            return m
    return None


# ── Overlay window ────────────────────────────────────────────────────────────

class Overlay:
    def __init__(self, app):
        self.cfg = {"opacity": 0.85, "seconds": 1.6, "corner": "top-right", "margin": 16}
        self.win = Gtk.Window(application=app, decorated=False, resizable=False)
        LS.init_for_window(self.win)
        LS.set_namespace(self.win, "orion-overlay")  # target for Hyprland `layerrule`s (blur, animation)
        LS.set_layer(self.win, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(self.win, LS.KeyboardMode.NONE)  # never steals focus
        self.win.connect("map", self._click_through)

        self.bar, self.title, self.detail = Gtk.Box(), Gtk.Label(xalign=0), Gtk.Label(xalign=0)
        self.title.add_css_class("title")
        self.detail.add_css_class("detail")
        self.bar.add_css_class("bar")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.append(self.title)
        text.append(self.detail)
        card = Gtk.Box(spacing=12)
        card.add_css_class("card")
        card.set_size_request(280, -1)
        card.append(self.bar)
        card.append(text)
        self.win.set_child(card)

        css = Gtk.CssProvider()
        css.load_from_string(CSS) if hasattr(css, "load_from_string") else css.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, 800)
        self.apply_config()
        self.hide_id = self.fade_id = None
        self.last_key, self.count = None, 0

    def _click_through(self, *_):
        try:
            import cairo
            self.win.get_surface().set_input_region(cairo.Region())  # empty input region: clicks pass through
        except Exception:
            pass

    def apply_config(self):
        for edge in LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT:
            LS.set_anchor(self.win, edge, False)
        for name in EDGES.get(self.cfg["corner"], EDGES["top-right"]):
            LS.set_anchor(self.win, getattr(LS.Edge, name), True)
            LS.set_margin(self.win, getattr(LS.Edge, name), int(self.cfg["margin"]))

    # ── Messages ──────────────────────────────────────────────────────────────

    def handle(self, msg):
        if msg.get("type") == "config":
            self.cfg.update({k: v for k, v in msg.items() if k != "type"})
            self.apply_config()
        elif msg.get("type") == "show":
            self.show(msg)

    def show(self, msg):
        key = msg.get("key")
        self.count = self.count + 1 if key and key == self.last_key and self.win.get_visible() else 1
        self.last_key = key
        self.title.set_text(msg.get("title", "") + (f"  ×{self.count}" if self.count > 1 else ""))
        self.detail.set_text(msg.get("detail", ""))
        self.detail.set_visible(bool(msg.get("detail")))
        for c in ("left", "right", "none"):
            self.bar.remove_css_class(c)
        self.bar.add_css_class(msg.get("hand") if msg.get("hand") in ("left", "right") else "none")

        if not self.win.get_visible():  # (re)map on the monitor that has focus right now
            mon = gdk_monitor(focused_connector())
            LS.set_monitor(self.win, mon)
            self.win.set_visible(True)
        self._stop_fade()
        self.win.set_opacity(float(self.cfg["opacity"]))
        if self.hide_id:
            GLib.source_remove(self.hide_id)
        self.hide_id = GLib.timeout_add(int(float(self.cfg["seconds"]) * 1000), self._fade_out)

    def _stop_fade(self):
        if self.fade_id:
            GLib.source_remove(self.fade_id)
            self.fade_id = None

    def _fade_out(self):
        self.hide_id = None

        def step():
            o = self.win.get_opacity() - 0.08
            if o <= 0.02:
                self.fade_id = None
                self.win.set_visible(False)  # unmapped: nothing on screen, nothing to hit
                return False
            self.win.set_opacity(o)
            return True
        self.fade_id = GLib.timeout_add(16, step)
        return False


# ── Entry: stdin JSON lines → overlay (exits when Orion closes the pipe) ─────

def main():
    if not LS.is_supported():
        print("overlay: compositor has no wlr-layer-shell support", file=sys.stderr)
        sys.exit(2)
    app = Gtk.Application(application_id="dev.orion.overlay", flags=0x20)  # NON_UNIQUE

    def activate(app):
        ov, buf = Overlay(app), b""
        app.hold()

        def on_input(fd, cond):
            nonlocal buf
            chunk = os.read(fd, 65536)
            if not chunk:
                app.quit()
                return False
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                try:
                    ov.handle(json.loads(line))
                except ValueError:
                    pass
            return True
        GLib.io_add_watch(sys.stdin.fileno(), GLib.IO_IN | GLib.IO_HUP, on_input)

    app.connect("activate", activate)
    app.run([])


if __name__ == "__main__":
    main()
