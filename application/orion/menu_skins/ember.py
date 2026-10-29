"""Ember: slices fade from dark red to amber and the hovered one glows like a coal."""

from . import skin
from .aurora import Aurora, _mix


@skin("ember")
class Ember(Aurora):
    INK, GLASS, GLASS_HI, HOT, ACCENT = (0.10, 0.03, 0.02), (0.20, 0.06, 0.04), (0.38, 0.12, 0.06), (1.0, 0.55, 0.15), (1.0, 0.70, 0.30)
    LABEL, LABEL_HOT, HUE = (0.98, 0.82, 0.70), (0.18, 0.05, 0.02), 25

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        cr.new_path()
        cr.arc(sx, sy, r_out, theta - half, theta + half)
        cr.arc_negative(sx, sy, r_in, theta + half, theta - half)
        cr.close_path()
        if s.glow > 0.01:
            for width, strength in ((22, 0.05), (14, 0.09), (7, 0.15), (3, 0.22)):  # a wider, hotter bloom than Aurora's
                cr.set_line_width(width)
                cr.set_source_rgba(*self.HOT, strength * s.glow * s.alpha)
                cr.stroke_preserve()
        g = cairo.RadialGradient(sx, sy, r_in, sx, sy, r_out)
        a = (0.9 + 0.06 * s.lift) * s.alpha
        g.add_color_stop_rgba(0, *_mix(self.GLASS, self.GLASS_HI, s.lift), a)
        g.add_color_stop_rgba(1, *_mix(_mix(self.GLASS_HI, self.HOT, s.lift), (1, 1, 1), s.flash * 0.6), a)
        cr.set_source(g)
        cr.fill_preserve()
        cr.set_line_width(1.2 + s.lift)
        cr.set_source_rgba(*_mix(self.GLASS_HI, self.ACCENT, s.lift), (0.55 + 0.4 * s.lift) * s.alpha)
        cr.stroke()
