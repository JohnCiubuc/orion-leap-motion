"""Constellation: items are stars joined by faint lines; the hovered star flares into a four-point sparkle."""

import math

from . import skin
from .aurora import Aurora, _mix

R_STAR = 128.0  # px from the centre


@skin("constellation")
class Constellation(Aurora):
    INK, GLASS, GLASS_HI, HOT, ACCENT = (0.02, 0.03, 0.08), (0.45, 0.55, 0.85), (0.62, 0.72, 1.0), (1.0, 1.0, 1.0), (0.62, 0.72, 1.0)
    LABEL, LABEL_HOT, HUE = (0.66, 0.72, 0.88), (1.0, 1.0, 1.0), 223
    LABEL_R, CHEV_R = R_STAR + 36, R_STAR - 24

    def draw(self, cr, v, w, h):
        self.view = v  # the outline joins every star
        super().draw(cr, v, w, h)

    def _star(self, ox, oy, s):
        t = s.angle - math.pi / 2
        r = (R_STAR + 10 * s.lift + 14 * s.stretch) * s.scale
        return ox + math.cos(t) * r, oy + math.sin(t) * r

    def _shadow(self, cr, cairo, ox, oy, a):  # in place of the soft shadow: a few fixed background stars, then the outline
        for k in range(26):
            cr.new_path()
            cr.arc(ox + ((k * 97) % 300) - 150, oy + ((k * 53 + 20) % 300) - 150, 0.9 + (k % 3) * 0.4, 0, 2 * math.pi)
            cr.set_source_rgba(*self.GLASS_HI, 0.30 * a)
            cr.fill()
        pts = [self._star(ox, oy, s) for s in self.view.slices]
        if len(pts) > 1:
            cr.new_path()
            cr.move_to(*pts[0])
            for p in pts[1:]:
                cr.line_to(*p)
            if self.view.back is None:
                cr.close_path()
            cr.set_line_width(1)
            cr.set_source_rgba(*self.GLASS_HI, 0.30 * a)
            cr.stroke()

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        ox, oy = self.origin
        x, y = self._star(ox, oy, s)
        cr.new_path()  # the line from the centre to the star
        cr.move_to(ox, oy)
        cr.line_to(x, y)
        cr.set_line_width(1 + s.lift)
        cr.set_source_rgba(*self.GLASS_HI, (0.22 + 0.6 * s.lift) * s.alpha)
        cr.stroke()
        halo = (9 + 12 * s.lift + 10 * s.flash) * s.scale
        g = cairo.RadialGradient(x, y, 0, x, y, halo * 2)
        g.add_color_stop_rgba(0, *self.GLASS_HI, (0.45 + 0.4 * s.lift) * s.alpha)
        g.add_color_stop_rgba(1, *self.GLASS_HI, 0)
        cr.new_path()
        cr.arc(x, y, halo * 2, 0, 2 * math.pi)
        cr.set_source(g)
        cr.fill()
        if s.lift > 0.02:  # the four-point sparkle
            reach, thin = (8 + 14 * s.lift) * s.scale, 2.5 * s.scale
            cr.new_path()
            cr.move_to(x - reach, y)
            cr.line_to(x, y - thin)
            cr.line_to(x + reach, y)
            cr.line_to(x, y + thin)
            cr.close_path()
            cr.move_to(x, y - reach)
            cr.line_to(x + thin, y)
            cr.line_to(x, y + reach)
            cr.line_to(x - thin, y)
            cr.close_path()
            cr.set_source_rgba(*self.HOT, s.lift * s.alpha)
            cr.fill()
        cr.new_path()
        cr.arc(x, y, (3 + 1.5 * s.lift) * s.scale, 0, 2 * math.pi)
        cr.set_source_rgba(*_mix(self.LABEL, self.HOT, s.lift), s.alpha)
        cr.fill()
