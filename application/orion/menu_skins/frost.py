"""Frost: pale translucent slices with a white edge. The overlay cannot blur what is behind it, so the frost is a light fill."""

from . import skin
from .aurora import Aurora, _mix


@skin("frost")
class Frost(Aurora):
    INK, GLASS, GLASS_HI, HOT, ACCENT = (0.03, 0.05, 0.10), (0.80, 0.88, 1.0), (0.90, 0.95, 1.0), (0.95, 0.98, 1.0), (1.0, 1.0, 1.0)
    LABEL, LABEL_HOT, HUE = (0.96, 0.98, 1.0), (0.04, 0.07, 0.14), 215

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        cr.new_path()
        cr.arc(sx, sy, r_out, theta - half, theta + half)
        cr.arc_negative(sx, sy, r_in, theta + half, theta - half)
        cr.close_path()
        g = cairo.LinearGradient(sx, sy - r_out, sx, sy + r_out)
        top, bottom = 0.30 + 0.32 * s.lift, 0.12 + 0.22 * s.lift
        g.add_color_stop_rgba(0, *_mix(self.GLASS, self.HOT, s.lift), top * s.alpha)
        g.add_color_stop_rgba(1, *self.GLASS, bottom * s.alpha)
        cr.set_source(g)
        cr.fill_preserve()
        cr.set_line_width(1.4)
        cr.set_source_rgba(*self.ACCENT, (0.40 + 0.5 * s.lift) * s.alpha)
        cr.stroke()
        cr.new_path()  # the inner highlight
        cr.arc(sx, sy, r_out - 4, theta - half + 0.05, theta + half - 0.05)
        cr.set_line_width(1)
        cr.set_source_rgba(*self.ACCENT, 0.30 * s.alpha)
        cr.stroke()
