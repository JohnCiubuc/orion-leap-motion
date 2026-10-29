"""Halo: a thin segmented ring with the labels outside it, so the middle of the screen stays clear."""

import math

from . import skin
from .aurora import Aurora

RING = 128.0  # px: the middle of the ring's band


@skin("halo")
class Halo(Aurora):
    INK, GLASS, GLASS_HI, HOT, ACCENT = (0.04, 0.05, 0.09), (0.35, 0.38, 0.50), (0.35, 0.38, 0.50), (0.61, 0.89, 0.48), (0.61, 0.89, 0.48)
    LABEL, LABEL_HOT = (0.72, 0.75, 0.85), (1.0, 1.0, 1.0)
    HUE = 96
    LABEL_R, CHEV_R = RING + 46, RING - 24

    def _shadow(self, cr, cairo, ox, oy, a):  # nothing behind the ring
        pass

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        band = (5 + 7 * s.lift) * s.scale  # the band thickens under the marker
        cr.new_path()
        cr.arc(sx, sy, RING * s.scale + band, theta - half, theta + half)
        cr.arc_negative(sx, sy, RING * s.scale - band, theta + half, theta - half)
        cr.close_path()
        if s.glow > 0.01:
            for width, strength in ((14, 0.06), (7, 0.12)):
                cr.set_line_width(width)
                cr.set_source_rgba(*self.ACCENT, strength * s.glow * s.alpha)
                cr.stroke_preserve()
        k = s.lift + s.flash * (1 - s.lift)
        cr.set_source_rgba(*[a + (b - a) * k for a, b in zip(self.GLASS, self.HOT)], (0.75 + 0.25 * s.lift) * s.alpha)
        cr.fill()
