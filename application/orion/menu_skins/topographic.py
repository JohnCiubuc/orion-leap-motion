"""Topographic: each slice is a set of contour lines; the hovered one gets more, brighter lines and a faint fill."""

import math

from . import skin
from .aurora import Aurora, _mix


@skin("topographic")
class Topographic(Aurora):
    INK, GLASS, GLASS_HI, HOT, ACCENT = (0.03, 0.06, 0.04), (0.36, 0.48, 0.40), (0.30, 0.42, 0.34), (0.48, 0.85, 0.56), (0.48, 0.85, 0.56)
    LABEL, LABEL_HOT, HUE = (0.72, 0.82, 0.75), (0.94, 1.0, 0.96), 135

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        cr.new_path()  # a dark pane keeps the label readable over the lines
        cr.arc(sx, sy, r_out, theta - half, theta + half)
        cr.arc_negative(sx, sy, r_in, theta + half, theta - half)
        cr.close_path()
        cr.set_source_rgba(*self.INK, 0.6 * s.alpha)
        cr.fill_preserve()
        cr.set_source_rgba(*self.HOT, (0.14 * s.lift + 0.4 * s.flash) * s.alpha)
        cr.fill()
        rings = 5 + round(3 * s.lift)
        label_r = self.LABEL_R * r_out / 170  # leave the label's own band clear
        for k in range(rings):
            r = r_in + (r_out - r_in) * (k + 0.5) / rings
            if abs(r - label_r) < 11:
                continue
            squeeze = k * 0.012  # inner contours reach a little less far round, like a hill
            cr.new_path()
            cr.arc(sx, sy, r, theta - half + squeeze, theta + half - squeeze)
            cr.set_line_width(1 + 0.5 * s.lift)
            cr.set_source_rgba(*_mix(self.GLASS, self.HOT, s.lift), (0.65 + 0.3 * s.lift) * s.alpha)
            cr.stroke()
