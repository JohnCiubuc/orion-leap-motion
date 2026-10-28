"""OrionDo pie: a pie-sized, click-through layer-shell window drawn with cairo.

Part of the overlay process (see overlay_gtk.py, which runs as a script, hence the bare import of menu_anim).
Messages from the engine move targets in MenuAnim; a 16 ms tick asks it for the current view and redraws, and
the window is unmapped once the pie has collapsed.
"""

import math
import time
from collections import deque

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk, Gtk4LayerShell as LS  # noqa: E402

from menu_anim import MenuAnim, MenuView  # noqa: E402

R_IN, R_OUT, R_PULL = 70.0, 170.0, 230.0  # px: slice ring, and where the marker fires an item
SIZE = 560  # px square: room for the pull ring and the marker's 1.1× clamp. Unanchored, the compositor centres it,
# and redrawing this instead of the whole monitor took the 4K overlay from 28 % of a core to a fraction of that
GAP = math.radians(3)  # between slices
LIFT, STRETCH = 14.0, 26.0  # px a hovered slice moves out, and a fully pulled one on top of that
BASE, HOT, ACCENT = (0.055, 0.07, 0.16), (0.2, 0.38, 0.62), (0.56, 0.78, 1.0)


def _mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


class MenuWindow:
    def __init__(self, app, place, click_through):
        """`place(win)` puts the window on the focused monitor (False: don't show); `click_through(win)` empties its input region."""
        self.anim, self.view, self.trail = MenuAnim(), MenuView(), deque(maxlen=7)
        self.place, self.click_through, self.broken, self.tick_id = place, click_through, False, None
        self.win = Gtk.Window(application=app, decorated=False)
        LS.init_for_window(self.win)
        LS.set_namespace(self.win, "orion-menu")
        LS.set_layer(self.win, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(self.win, LS.KeyboardMode.NONE)
        LS.set_exclusive_zone(self.win, -1)
        self.win.set_default_size(SIZE, SIZE)
        self.win.connect("map", self._mapped)
        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self._draw)
        self.win.set_child(self.area)

    def _mapped(self, win):
        if not self.click_through(win):  # a surface that could eat clicks must never stay up
            self.broken = True
            win.set_visible(False)

    def handle(self, msg):
        now, op = time.monotonic(), msg.get("op")
        if op == "open":
            if self.broken or not self.place(self.win):
                return
            self.anim.open(msg["labels"], now)
            self.trail.clear()
            self.win.set_visible(True)
            self.tick_id = self.tick_id or GLib.timeout_add(16, self._tick)
        elif op == "update":
            self.anim.update(msg["x"], msg["y"], msg["hover"], msg["pull"], now)
        elif op == "fire":
            self.anim.fire(msg["index"], now)
        elif op == "close":
            self.anim.close(now)

    def _tick(self):
        self.view = self.anim.step(time.monotonic())
        self.trail.append(self.view.marker)
        if not self.view.visible:
            self.win.set_visible(False)  # unmapped: nothing on screen, nothing to hit
            self.tick_id = None
            return False
        self.area.queue_draw()
        return True

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self, area, cr, w, h):
        v = self.view
        if not v.visible or not v.slices:
            return
        cx, cy, n = w / 2, h / 2, len(v.slices)
        half = max(math.pi / n - GAP / 2, 0.01)
        shown = min(s.alpha for s in v.slices)
        self._draw_hub(cr, cx, cy, shown)
        for i, s in enumerate(v.slices):
            if s.alpha <= 0:
                continue
            theta = i * 2 * math.pi / n - math.pi / 2  # slice 0 at the top, clockwise
            off = s.lift * LIFT + s.stretch * STRETCH
            ox, oy = cx + math.cos(theta) * off, cy + math.sin(theta) * off
            cr.new_path()
            cr.arc(ox, oy, R_OUT * s.scale, theta - half, theta + half)
            cr.arc_negative(ox, oy, R_IN * s.scale, theta + half, theta - half)
            cr.close_path()
            if s.glow > 0.01:  # soft halo behind the hovered slice
                cr.set_line_width(9)
                cr.set_source_rgba(*ACCENT, 0.22 * s.glow * s.alpha)
                cr.stroke_preserve()
            r, g, b = _mix(_mix(BASE, HOT, s.lift), (1, 1, 1), s.flash)
            cr.set_source_rgba(r, g, b, (0.80 + 0.12 * s.lift) * s.alpha)
            cr.fill_preserve()
            cr.set_line_width(1.5)
            cr.set_source_rgba(*ACCENT, (0.3 + 0.5 * s.lift) * s.alpha)
            cr.stroke()
            self._draw_label(cr, v, i, ox, oy, theta, s)
        self._draw_pull(cr, v, cx, cy, half, n, shown)
        self._draw_marker(cr, v, cx, cy, shown)

    def _draw_hub(self, cr, cx, cy, a):
        cr.new_path()  # show_text leaves a current point: an arc would draw a line from it
        cr.arc(cx, cy, 22, 0, 2 * math.pi)  # the centre: a tap here closes the menu
        cr.set_source_rgba(*BASE, 0.7 * a)
        cr.fill_preserve()
        cr.set_line_width(1.5)
        cr.set_source_rgba(*ACCENT, 0.35 * a)
        cr.stroke()

    def _draw_label(self, cr, v, i, ox, oy, theta, s):
        r = (R_IN + R_OUT) / 2 * s.scale
        cr.select_font_face("Sora", 0, 1)
        cr.set_font_size(22 * (0.9 + 0.1 * s.scale))
        label = self.anim.labels[i]
        ext = cr.text_extents(label)
        cr.move_to(ox + math.cos(theta) * r - ext.width / 2 - ext.x_bearing, oy + math.sin(theta) * r - ext.height / 2 - ext.y_bearing)
        cr.set_source_rgba(0.9, 0.93, 1.0, (0.75 + 0.25 * s.lift) * s.alpha)
        cr.show_text(label)

    def _draw_pull(self, cr, v, cx, cy, half, n, a):
        cr.new_path()
        cr.arc(cx, cy, R_PULL, 0, 2 * math.pi)  # the activation ring
        cr.set_line_width(1)
        cr.set_source_rgba(*ACCENT, 0.18 * a)
        cr.stroke()
        if v.hover is not None and v.arc > 0.01:  # the pull fills outward from the middle of the hovered slice's arc
            cr.new_path()
            theta = v.hover * 2 * math.pi / n - math.pi / 2
            cr.arc(cx, cy, R_PULL, theta - half * v.arc, theta + half * v.arc)
            cr.set_line_width(4)
            cr.set_line_cap(1)
            cr.set_source_rgba(*ACCENT, 0.9 * a)
            cr.stroke()

    def _draw_marker(self, cr, v, cx, cy, a):
        cr.new_path()
        pts = [(cx + min(max(x, -1.1), 1.1) * R_PULL, cy - min(max(y, -1.1), 1.1) * R_PULL) for x, y in self.trail]
        for k, (x, y) in enumerate(pts[:-1]):  # a faint trail, oldest smallest
            f = (k + 1) / len(pts)
            cr.arc(x, y, 2 + 3 * f, 0, 2 * math.pi)
            cr.set_source_rgba(*ACCENT, 0.25 * f * a)
            cr.fill()
        x, y = pts[-1]
        cr.arc(x, y, 7, 0, 2 * math.pi)
        cr.set_source_rgba(*ACCENT, a)
        cr.fill_preserve()
        cr.set_line_width(2)
        cr.set_source_rgba(*BASE, 0.8 * a)
        cr.stroke()
