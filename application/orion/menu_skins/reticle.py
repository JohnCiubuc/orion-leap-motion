"""Reticle: thin cyan linework, a ring of tick marks and hollow slices that fill and glow when hovered."""

import math

from . import skin
from .aurora import Aurora, R_OUT


@skin("reticle")
class Reticle(Aurora):
    INK, GLASS, GLASS_HI, HOT, ACCENT = (0.02, 0.05, 0.07), (0.03, 0.12, 0.14), (0.05, 0.20, 0.22), (0.10, 0.89, 0.82), (0.10, 0.89, 0.82)
    LABEL = LABEL_HOT = (0.75, 1.0, 0.98)
    HUE = 176

    def _shadow(self, cr, cairo, ox, oy, a):  # in place of the soft shadow: a dotted ring and tick marks around the pie
        cr.new_path()
        cr.arc(ox, oy, R_OUT + 44, 0, 2 * math.pi)
        cr.set_dash([1, 6])
        cr.set_line_width(1.2)
        cr.set_source_rgba(*self.ACCENT, 0.35 * a)
        cr.stroke()
        cr.set_dash([])
        for k in range(72):
            t = k * math.pi / 36
            long = k % 9 == 0
            r0, r1 = R_OUT + 14, R_OUT + (26 if long else 20)
            cr.move_to(ox + math.cos(t) * r0, oy + math.sin(t) * r0)
            cr.line_to(ox + math.cos(t) * r1, oy + math.sin(t) * r1)
        cr.set_line_width(1)
        cr.set_source_rgba(*self.ACCENT, 0.45 * a)
        cr.stroke()

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        cr.new_path()
        cr.arc(sx, sy, r_out, theta - half, theta + half)
        cr.arc_negative(sx, sy, r_in, theta + half, theta - half)
        cr.close_path()
        for width, strength in ((14, 0.05), (8, 0.10), (3, 0.18)):  # the glow is the same layered stroke Aurora uses
            if s.glow > 0.01:
                cr.set_line_width(width)
                cr.set_source_rgba(*self.ACCENT, strength * s.glow * s.alpha)
                cr.stroke_preserve()
        cr.set_source_rgba(*self.ACCENT, (0.04 + 0.22 * s.lift + 0.5 * s.flash) * s.alpha)
        cr.fill_preserve()
        cr.set_line_width(1 + 0.9 * s.lift)
        cr.set_source_rgba(*self.ACCENT, (0.65 + 0.35 * s.lift) * s.alpha)
        cr.stroke()
