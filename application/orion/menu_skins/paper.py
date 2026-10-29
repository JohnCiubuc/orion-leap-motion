"""Paper: flat light slices with a heavy ink outline and a hard offset shadow; the hovered slice turns signal orange."""

import math

from . import skin
from .aurora import Aurora, _mix


@skin("paper")
class Paper(Aurora):
    INK, GLASS, GLASS_HI, HOT, ACCENT = (0.04, 0.05, 0.07), (0.93, 0.945, 0.965), (0.93, 0.945, 0.965), (1.0, 0.35, 0.21), (1.0, 0.45, 0.28)
    LABEL, LABEL_HOT, HUE = INK, (1.0, 1.0, 1.0), 11

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        for dx, dy, fill in ((5, 5, None), (0, 0, _mix(_mix(self.GLASS, self.HOT, s.lift), (1, 1, 1), s.flash))):
            cr.new_path()
            cr.arc(sx + dx, sy + dy, r_out, theta - half, theta + half)
            cr.arc_negative(sx + dx, sy + dy, r_in, theta + half, theta - half)
            cr.close_path()
            if fill is None:  # the hard shadow
                cr.set_source_rgba(0, 0, 0, 0.55 * s.alpha)
                cr.fill()
                continue
            cr.set_source_rgba(*fill, s.alpha)
            cr.fill_preserve()
            cr.set_line_width(3)
            cr.set_line_join(1)
            cr.set_source_rgba(*self.INK, s.alpha)
            cr.stroke()
