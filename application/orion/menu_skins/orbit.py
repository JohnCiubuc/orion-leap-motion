"""Orbit: every item is a thick rounded arc on a track; the hovered one moves outward and grows a bead."""

import math

from . import skin
from .aurora import GAP, Aurora, _mix

R_ARC = 120.0  # px: the track the arcs sit on


@skin("orbit")
class Orbit(Aurora):
    INK, GLASS, GLASS_HI, HOT, ACCENT = (0.05, 0.05, 0.12), (0.29, 0.32, 0.50), (0.35, 0.38, 0.58), (0.72, 0.58, 0.96), (0.80, 0.70, 1.0)
    LABEL, LABEL_HOT, HUE = (0.62, 0.65, 0.78), (0.94, 0.90, 1.0), 265
    LABEL_R, CHEV_R = R_ARC + 52, R_ARC - 26

    def _shadow(self, cr, cairo, ox, oy, a):  # the track
        cr.new_path()
        cr.arc(ox, oy, R_ARC, 0, 2 * math.pi)
        cr.set_line_width(1.5)
        cr.set_source_rgba(*self.GLASS, 0.45 * a)
        cr.stroke()

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        r = (R_ARC + 12 * s.lift) * s.scale
        width = (11 + 8 * s.lift) * s.scale
        cr.set_line_cap(1)
        cr.new_path()
        cr.arc(sx, sy, r, theta - half + 0.06, theta + half - 0.06)
        if s.glow > 0.01:
            for extra, strength in ((16, 0.06), (8, 0.12)):
                cr.set_line_width(width + extra)
                cr.set_source_rgba(*self.ACCENT, strength * s.glow * s.alpha)
                cr.stroke_preserve()
        cr.set_line_width(width)
        cr.set_source_rgba(*_mix(self.GLASS, self.HOT, s.lift), s.alpha)
        cr.stroke()
        if s.lift > 0.02:  # the bead at the leading end
            end = theta + half - 0.06
            cr.new_path()
            cr.arc(sx + math.cos(end) * r, sy + math.sin(end) * r, (5 + 5 * s.lift) * s.scale, 0, 2 * math.pi)
            cr.set_source_rgba(*self.LABEL_HOT, s.lift * s.alpha)
            cr.fill()
