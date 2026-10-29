"""Petal: soft rounded petals fanning out from the centre; the hovered one grows longer and turns a deeper colour."""

import math

from . import skin
from .aurora import R_IN, R_OUT, Aurora, _mix


@skin("petal")
class Petal(Aurora):
    INK, GLASS, GLASS_HI, HOT, ACCENT = (0.05, 0.04, 0.10), (0.36, 0.29, 0.56), (0.47, 0.37, 0.72), (0.94, 0.38, 0.57), (1.0, 0.88, 0.51)
    LABEL = LABEL_HOT = (1.0, 1.0, 1.0)
    HUE = 44

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        k = r_out / R_OUT  # the bloom scale
        length = (R_OUT + 12 * s.lift) * k
        base = R_IN * 0.45 * k
        at = lambda r, t: (sx + math.cos(t) * r, sy + math.sin(t) * r)  # noqa: E731
        wide = min(half * 1.15, 1.2)  # a lone petal must not wrap around itself
        cr.new_path()
        cr.move_to(*at(base, theta))
        cr.curve_to(*at(length * 0.45, theta - wide), *at(length * 0.95, theta - wide * 0.5), *at(length, theta))
        cr.curve_to(*at(length * 0.95, theta + wide * 0.5), *at(length * 0.45, theta + wide), *at(base, theta))
        cr.close_path()
        g = cairo.RadialGradient(sx, sy, base, sx, sy, length)
        a = (0.78 + 0.2 * s.lift) * s.alpha
        g.add_color_stop_rgba(0, *_mix(self.GLASS, self.HOT, s.lift * 0.5), a)
        g.add_color_stop_rgba(1, *_mix(self.GLASS_HI, self.HOT, s.lift), a)
        cr.set_source(g)
        cr.fill_preserve()
        cr.set_line_width(1.2)
        cr.set_source_rgba(1, 1, 1, (0.2 + 0.25 * s.lift) * s.alpha)
        cr.stroke()
