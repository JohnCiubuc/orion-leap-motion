"""Gesture overlay: a small translucent card in a corner of the focused monitor.

Runs as its own process under the *system* Python (needs python-gobject + gtk4-layer-shell
from pacman, not the venv), started by orion/overlay.py with LD_PRELOAD set for the
layer-shell library. Reads JSON lines on stdin:
    {"type": "config", "opacity": .85, "seconds": 1.6, "corner": "top-right", "margin": 16,
     "precision_ring": true}
    {"type": "show", "title": "Swipe left", "detail": "hypr.dispatch", "hand": "right", "key": "…"}
    {"type": "ring", "on": true}     # precision ring around the cursor (needs config precision_ring)

It is a wlr-layer-shell surface, not a window: Hyprland never tiles, focuses or lists it,
it takes no keyboard focus and clicks pass straight through it.
"""

import json
import os
import socket
import sys
import time

import gi

# Probe at 4K: full-monitor ring costs ~55% CPU on vulkan, ~30% gl, ~12% cairo (damage-clipped to the ring).
os.environ.setdefault("GSK_RENDERER", "cairo")
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

def _ipc(cmd):
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        return None
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(0.2)  # a wedged compositor must not stall the GTK loop
            s.connect(f"{os.environ.get('XDG_RUNTIME_DIR', '/tmp')}/hypr/{sig}/.socket.sock")
            s.sendall(cmd)
            data = b"".join(iter(lambda: s.recv(65536), b""))
        return json.loads(data)
    except Exception:
        return None


def focused_monitor():
    return next((m for m in _ipc(b"j/monitors") or [] if m.get("focused")), None)


def focused_connector():
    m = focused_monitor()
    return m and m.get("name")


def cursor_position():
    """Global layout coordinates of the pointer, or None (never raises)."""
    try:
        c = _ipc(b"j/cursorpos")
        return float(c["x"]), float(c["y"])
    except Exception:
        return None


def ease_out_cubic(t):
    return 1 - (1 - min(max(t, 0.0), 1.0)) ** 3


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
        self._init_ring(app)

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

    def _click_through(self, win, *_):
        try:
            import cairo
            win.get_surface().set_input_region(cairo.Region())  # empty input region: clicks pass through
            return True
        except Exception:
            return False

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
            self.set_ring(self.ring_want)  # precision_ring may have flipped
        elif msg.get("type") == "show":
            self.show(msg)
        elif msg.get("type") == "ring":
            self.set_ring(bool(msg.get("on")))

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

    # ── Precision ring ────────────────────────────────────────────────────────
    # A full-monitor transparent surface with an empty input region, redrawn on a 16 ms timer
    # only while the ring is visible; the probe showed this is cheap (nothing is damaged but the
    # ring) and avoids the lag of moving a small surface via margins.

    def _init_ring(self, app):
        self.ring_win = Gtk.Window(application=app, decorated=False)  # resizable: anchors stretch it over the monitor
        LS.init_for_window(self.ring_win)
        LS.set_namespace(self.ring_win, "orion-ring")
        LS.set_layer(self.ring_win, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(self.ring_win, LS.KeyboardMode.NONE)
        LS.set_exclusive_zone(self.ring_win, -1)  # ignore other bars' reserved space
        for edge in LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT:
            LS.set_anchor(self.ring_win, edge, True)
        self.ring_win.connect("map", self._ring_map)
        area = Gtk.DrawingArea()
        area.set_draw_func(self._draw_ring)
        self.ring_win.set_child(area)
        self.ring_area = area
        self.ring_target = False  # effective state after setting + safety checks
        self.ring_want = False  # what the engine asked for
        self.ring_broken = False  # input region failed: never show a surface that could eat clicks
        self.ring_r, self.ring_a = 44.0, 0.0
        self.ring_anim = None  # (t0, ms, r0, r1, a0, a1)
        self.ring_xy = None  # cursor in monitor-local coordinates
        self.ring_mon = None  # (name, x, y) of the monitor the surface sits on
        self.ring_tick_id, self.ring_last_check = None, 0.0

    def _ring_map(self, win):
        if not self._click_through(win):
            self.ring_broken = True
            win.set_visible(False)

    def set_ring(self, on):
        self.ring_want = on
        on = on and bool(self.cfg.get("precision_ring", True)) and not self.ring_broken
        if on == self.ring_target:
            return  # repeated on must not restart the zoom
        self.ring_target = on
        visible = self.ring_win.get_visible()
        if not on and not visible:
            return
        if on and not visible:
            if not self._place_ring():  # no Hyprland / IPC down: no cursor to follow, so no ring
                self.ring_target = False
                return
            self.ring_r, self.ring_a, self.ring_xy = 44.0, 0.0, None  # drawn only once a real position arrives
            self.ring_win.set_visible(True)
        r1, a1, ms = (20.0, 1.0, 160) if on else (44.0, 0.0, 120)
        self.ring_anim = (time.monotonic(), ms, self.ring_r, r1, self.ring_a, a1)
        if not self.ring_tick_id:
            self.ring_tick_id = GLib.timeout_add(17, self._ring_tick)  # <= 60 Hz

    def _place_ring(self):
        m = focused_monitor()
        if not m:
            return False
        self.ring_mon = (m["name"], m["x"], m["y"])
        LS.set_monitor(self.ring_win, gdk_monitor(m["name"]))
        return True

    def _ring_tick(self):
        now = time.monotonic()
        if now - self.ring_last_check > 0.25:  # cursor may have crossed to another monitor
            self.ring_last_check = now
            m = focused_monitor()
            if m and self.ring_mon and m["name"] != self.ring_mon[0] and self.ring_win.get_visible():
                self.ring_win.set_visible(False)  # remap: the layer-shell monitor is fixed at map time
                self._place_ring()
                self.ring_win.set_visible(True)
        pos = cursor_position()
        dirty = False
        if pos and self.ring_mon:
            xy = (pos[0] - self.ring_mon[1], pos[1] - self.ring_mon[2])
            dirty, self.ring_xy = xy != self.ring_xy, xy
        if self.ring_anim:
            t0, ms, r0, r1, a0, a1 = self.ring_anim
            t = (now - t0) * 1000 / ms
            e = ease_out_cubic(t)
            self.ring_r, self.ring_a = r0 + (r1 - r0) * e, a0 + (a1 - a0) * e
            dirty = True
            if t >= 1:
                self.ring_anim = None
                if a1 == 0.0:  # faded out: unmapped, nothing on screen, nothing to hit
                    self.ring_win.set_visible(False)
                    self.ring_tick_id = None
                    return False
        if dirty:
            self.ring_area.queue_draw()
        return True

    def _draw_ring(self, area, cr, w, h):
        a = self.ring_a * float(self.cfg["opacity"])
        if a <= 0 or not self.ring_xy:
            return
        x, y = self.ring_xy
        cr.arc(x, y, self.ring_r, 0, 6.2832)
        cr.set_line_width(4)
        cr.set_source_rgba(0.05, 0.07, 0.16, a * 0.5)  # dark halo keeps it visible on light backgrounds
        cr.stroke_preserve()
        cr.set_line_width(2)
        cr.set_source_rgba(0.56, 0.78, 1.0, a)
        cr.stroke()


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
