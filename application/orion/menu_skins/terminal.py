"""Terminal: black slices, monospace labels, and a prompt with a cursor on the hovered one."""

from . import skin
from .aurora import Aurora


@skin("terminal")
class Terminal(Aurora):
    INK, GLASS, GLASS_HI, HOT, ACCENT = (0.01, 0.03, 0.02), (0.02, 0.05, 0.03), (0.04, 0.16, 0.08), (0.17, 0.85, 0.31), (0.17, 0.85, 0.31)
    LABEL, LABEL_HOT, HUE = (0.17, 0.85, 0.31), (0.71, 1.0, 0.78), 135
    FONT = "monospace"

    def _text(self, s):
        return f"> {s.label.lower()}_" if s.lift > 0.5 else s.label.lower()

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        cr.new_path()
        cr.arc(sx, sy, r_out, theta - half, theta + half)
        cr.arc_negative(sx, sy, r_in, theta + half, theta - half)
        cr.close_path()
        cr.set_source_rgba(*(self.GLASS_HI if s.lift > 0.5 or s.flash > 0.3 else self.GLASS), 0.96 * s.alpha)
        cr.fill_preserve()
        cr.set_line_width(1.2)
        cr.set_source_rgba(*self.ACCENT, (0.45 + 0.55 * s.lift) * s.alpha)
        cr.stroke()
