"""Neon: no fill, each slice a glowing tube outline like a bar sign; the hovered one is switched on hot."""

from . import skin
from .aurora import Aurora, _mix


@skin("neon")
class Neon(Aurora):
    INK, GLASS, GLASS_HI, HOT, ACCENT = (0.04, 0.02, 0.06), (0.54, 0.16, 0.47), (0.78, 0.22, 0.68), (1.0, 0.31, 0.85), (1.0, 0.31, 0.85)
    LABEL, LABEL_HOT, HUE = (0.85, 0.54, 0.78), (1.0, 1.0, 1.0), 313

    def _shadow(self, cr, cairo, ox, oy, a):  # nothing behind the tubes
        pass

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        cr.new_path()
        cr.arc(sx, sy, r_out, theta - half, theta + half)
        cr.arc_negative(sx, sy, r_in, theta + half, theta - half)
        cr.close_path()
        cr.set_line_join(1)
        lit = max(s.lift, s.flash)
        for width, strength in ((16, 0.04), (10, 0.08), (5, 0.16)):  # the glow, faint even when off
            cr.set_line_width(width)
            cr.set_source_rgba(*self.ACCENT, strength * (0.35 + 0.65 * lit) * s.alpha)
            cr.stroke_preserve()
        cr.set_line_width(3 + lit)
        cr.set_source_rgba(*_mix(self.GLASS, self.HOT, lit), s.alpha)
        cr.stroke_preserve()
        cr.set_line_width(1.2)  # the hot core of a lit tube
        cr.set_source_rgba(*_mix(self.GLASS_HI, (1, 1, 1), 0.8), lit * s.alpha)
        cr.stroke()
