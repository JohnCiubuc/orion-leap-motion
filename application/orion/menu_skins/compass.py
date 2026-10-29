"""Compass: brass-edged wedges inside a ring of tick marks and N/E/S/W, with a needle that swings toward the hovered item."""

import math

from . import skin
from .aurora import R_OUT, Aurora, _mix


@skin("compass")
class Compass(Aurora):
    INK, GLASS, GLASS_HI, HOT, ACCENT = (0.04, 0.05, 0.08), (0.09, 0.10, 0.14), (0.24, 0.19, 0.09), (0.95, 0.80, 0.45), (0.79, 0.66, 0.42)
    LABEL, LABEL_HOT, HUE = (0.85, 0.79, 0.63), (1.0, 0.90, 0.66), 40

    def draw(self, cr, v, w, h):
        self.view = v  # the needle reads every slice's hover
        super().draw(cr, v, w, h)

    def _shadow(self, cr, cairo, ox, oy, a):  # in place of the soft shadow: the bezel
        cr.new_path()
        cr.arc(ox, oy, R_OUT + 20, 0, 2 * math.pi)
        cr.set_line_width(1.2)
        cr.set_source_rgba(*self.ACCENT, 0.5 * a)
        cr.stroke()
        for k in range(72):
            t = k * math.pi / 36 - math.pi / 2
            r1 = R_OUT + (32 if k % 18 == 0 else 28 if k % 6 == 0 else 25)
            cr.move_to(ox + math.cos(t) * (R_OUT + 20), oy + math.sin(t) * (R_OUT + 20))
            cr.line_to(ox + math.cos(t) * r1, oy + math.sin(t) * r1)
        cr.set_line_width(1)
        cr.set_source_rgba(*self.ACCENT, 0.55 * a)
        cr.stroke()
        cr.select_font_face("monospace", 0, 1)
        cr.set_font_size(13)
        cr.set_source_rgba(*self.ACCENT, 0.9 * a)
        for k, letter in enumerate("NESW"):
            t = k * math.pi / 2 - math.pi / 2
            ext = cr.text_extents(letter)
            cr.move_to(ox + math.cos(t) * (R_OUT + 46) - ext.width / 2 - ext.x_bearing, oy + math.sin(t) * (R_OUT + 46) - ext.height / 2 - ext.y_bearing)
            cr.show_text(letter)

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        cr.new_path()
        cr.arc(sx, sy, r_out, theta - half, theta + half)
        cr.arc_negative(sx, sy, r_in, theta + half, theta - half)
        cr.close_path()
        cr.set_source_rgba(*_mix(self.GLASS, self.GLASS_HI, s.lift), 0.94 * s.alpha)
        cr.fill_preserve()
        cr.set_line_width(1.1 + 0.8 * s.lift)
        cr.set_source_rgba(*self.ACCENT, (0.5 + 0.5 * s.lift) * s.alpha)
        cr.stroke()

    def _hub(self, cr, cairo, ox, oy, a):
        super()._hub(cr, cairo, ox, oy, a)
        x = sum(math.sin(s.angle) * s.lift for s in self.view.slices)
        y = -sum(math.cos(s.angle) * s.lift for s in self.view.slices)
        mag = min(math.hypot(x, y), 1.0)
        if mag < 0.03:
            return
        ux, uy = x / math.hypot(x, y), y / math.hypot(x, y)
        cr.new_path()  # a diamond: long toward the item, short behind
        cr.move_to(ox + ux * 40 * mag, oy + uy * 40 * mag)
        cr.line_to(ox - uy * 7, oy + ux * 7)
        cr.line_to(ox - ux * 14 * mag, oy - uy * 14 * mag)
        cr.line_to(ox + uy * 7, oy - ux * 7)
        cr.close_path()
        cr.set_source_rgba(*self.HOT, 0.95 * a * mag)
        cr.fill()
