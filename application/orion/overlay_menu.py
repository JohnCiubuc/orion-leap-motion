"""OrionDo pie: a pie-sized, click-through layer-shell window; a skin does the cairo drawing.

Part of the overlay process (see overlay_gtk.py, which runs as a script, hence the bare imports). Messages from the
engine go to a MenuController (menu_ctl.py); a 16 ms tick asks it for the current view and redraws, and the window is
unmapped once the pie has collapsed. Skins live in menu_skins/.
"""

import os
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk, Gtk4LayerShell as LS  # noqa: E402

from menu_anim import MenuAnim  # noqa: E402
from menu_ctl import MenuController  # noqa: E402
from menu_skins import get_skin  # noqa: E402

SIZE = 560  # px square: room for the pull ring and the marker's 1.1× clamp. Unanchored, the compositor centres it,
# and redrawing this instead of the whole monitor took the 4K overlay from 28 % of a core to a fraction of that.
# The skins' geometry (aurora.py) is laid out for this size.


class MenuWindow:
    def __init__(self, app, place, click_through):
        """`place(win)` puts the window on the focused monitor (False: don't show); `click_through(win)` empties its input region."""
        self.ctl, self.view = MenuController(MenuAnim, get_skin), None
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

    def set_reduced(self, on):
        self.ctl.reduced = bool(on)

    def handle(self, msg):
        now, op = time.monotonic(), msg.get("op")
        if op == "open":
            if self.broken or not self.place(self.win):
                return
            self.ctl.handle(msg, now)
            if self.ctl.broken:
                return
            self.win.set_visible(True)
            self.tick_id = self.tick_id or GLib.timeout_add(16, self._tick)
        else:
            self.ctl.handle(msg, now)

    def _tick(self):
        self.view = self.ctl.view(time.monotonic())
        if self.view is None or not self.view.visible:
            self.win.set_visible(False)  # unmapped: nothing on screen, nothing to hit
            self.tick_id = None
            return False
        self.area.queue_draw()
        return True

    def _draw(self, area, cr, w, h):
        v = self.view
        if v is None or not v.visible or not v.slices:
            return
        if not self.ctl.draw(cr, v, w, h):  # a skin that raises must not leave a surface up
            GLib.idle_add(self._draw_failed)

    def _draw_failed(self):
        self.win.set_visible(False)
        if self.ctl.broken:  # the default skin failed: nothing can draw the pie, and the engine only knows the overlay is alive.
            os._exit(3)  # Stopping the process makes it stop offering menus, so a pull can never fire an item nobody can see.
        return False
