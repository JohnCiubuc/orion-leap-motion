"""Aurora, the default OrionDo look: soft glass slices over a faint shadow, a springy travel to each submenu with the
parent left behind as a ghost hub, and an accent that warms toward whatever you are about to pull."""

import colorsys
import math
from collections import deque

from . import skin

R_IN, R_OUT, R_PULL = 70.0, 170.0, 230.0  # px: slice ring, and where the marker fires an item
TRAVEL = 120.0  # px one step into a submenu moves the pie: the middle of the slice ring
GAP = math.radians(3)  # between slices
LIFT, STRETCH = 14.0, 26.0  # px a hovered slice moves out, and a fully pulled one on top of that
GHOST_R, HUB_R = 17.0, 22.0
INK, GLASS, GLASS_HI, HOT, ACCENT = (0.04, 0.05, 0.12), (0.10, 0.13, 0.29), (0.20, 0.26, 0.52), (0.27, 0.48, 0.88), (0.60, 0.80, 1.0)


def _mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _clamp(t):
    return min(max(t, 0.0), 1.0)


def _ease_out(t):
    return 1 - (1 - _clamp(t)) ** 3


@skin("aurora")
class Aurora:
    MOTION = {"travel_time": 0.2}
    # Subclasses are other skins: they change the palette, the radii of the label and chevron, and `_slice`. Every colour
    # a skin draws with comes from these seven, so `tune` can recolour any skin: the five palette colours rotate to a
    # chosen hue, the two text colours (at rest, and on the hovered slice) can be flipped light/dark.
    INK, GLASS, GLASS_HI, HOT, ACCENT = INK, GLASS, GLASS_HI, HOT, ACCENT
    LABEL = LABEL_HOT = (0.9, 0.93, 1.0)
    HUE = 218  # degrees: the hue of this skin's accent as shipped
    FONT = "Sora"
    LABEL_R, CHEV_R = (R_IN + R_OUT) / 2, R_OUT - 15  # px from the centre at sc = 1
    PALETTE = ("INK", "GLASS", "GLASS_HI", "HOT", "ACCENT")

    def tune(self, hue=None, invert=False):
        """Recolour for the next menu: `hue` (degrees, None keeps the skin's own) and `invert` for the text colours."""
        shift = 0.0 if hue is None else (hue - self.HUE) / 360
        base = type(self)
        for name in self.PALETTE:
            h, l, sat = colorsys.rgb_to_hls(*getattr(base, name))
            setattr(self, name, colorsys.hls_to_rgb((h + shift) % 1.0, l, sat))
        for name in ("LABEL", "LABEL_HOT"):
            c = getattr(base, name)
            setattr(self, name, tuple(1 - x for x in c) if invert else c)

    def __init__(self):
        self.trail = deque(maxlen=7)

    def draw(self, cr, v, w, h):
        import cairo
        if not v.visible or not v.slices:
            self.trail.clear()
            return
        cx, cy = w / 2, h / 2
        ox, oy = cx + v.pan[0] * TRAVEL, cy + v.pan[1] * TRAVEL
        shown = min(s.alpha for s in v.slices)
        self._shadow(cr, cairo, ox, oy, shown)
        for layer in v.leaving:
            self._slices(cr, cairo, cx + layer.center[0] * TRAVEL, cy + layer.center[1] * TRAVEL, layer.slices,
                         picked=layer.picked, leave=layer.leave)
        self._ghosts(cr, cairo, ox, oy, v, shown)
        self._slices(cr, cairo, ox, oy, v.slices)
        self._hub(cr, cairo, ox, oy, shown)
        self._pull(cr, v, ox, oy, shown, abs(v.pan[0]) + abs(v.pan[1]))
        self._pulse(cr, v, ox, oy)
        self._marker(cr, v, ox, oy, shown)

    # ── Pieces ────────────────────────────────────────────────────────────────

    def _shadow(self, cr, cairo, ox, oy, a):
        g = cairo.RadialGradient(ox, oy, R_IN, ox, oy, R_OUT + 26)
        g.add_color_stop_rgba(0, 0, 0, 0, 0.0)
        g.add_color_stop_rgba(0.55, 0, 0, 0, 0.30 * a)
        g.add_color_stop_rgba(1, 0, 0, 0, 0.0)
        cr.set_source(g)
        cr.new_path()
        cr.arc(ox, oy, R_OUT + 26, 0, 2 * math.pi)
        cr.fill()

    def _slices(self, cr, cairo, ox, oy, slices, picked=None, leave=0.0):
        for i, s in enumerate(slices):
            half = max(s.span / 2 - GAP / 2, 0.01)
            if s.alpha <= 0.002 or s.scale <= 0.002:
                continue
            theta = s.angle - math.pi / 2
            off = s.lift * LIFT + s.stretch * STRETCH
            sx, sy = ox + math.cos(theta) * off, oy + math.sin(theta) * off
            cr.save()
            if i == picked:  # the pulled slice shrinks into the spot that becomes the next hub
                mx, my = sx + math.cos(theta) * (R_IN + R_OUT) / 2, sy + math.sin(theta) * (R_IN + R_OUT) / 2
                cr.translate(mx, my)
                k = 1 - 0.75 * _ease_out(leave)
                cr.scale(k, k)
                cr.translate(-mx, -my)
            sc = 1.0 if i == picked else s.scale
            r_in, r_out = R_IN * sc, R_OUT * sc
            self._slice(cr, cairo, s, sx, sy, theta, half, r_in, r_out)
            self._label(cr, s, sx, sy, theta, sc, self._ink(s))
            cr.restore()

    def _ink(self, s):
        return _mix(self.LABEL, self.LABEL_HOT, s.lift)

    def _text(self, s):
        return s.label

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        cr.new_path()
        cr.arc(sx, sy, r_out, theta - half, theta + half)
        cr.arc_negative(sx, sy, r_in, theta + half, theta - half)
        cr.close_path()
        if s.glow > 0.01:  # soft halo, layered so it fades smoothly instead of ending in one hard edge
            for width, strength in ((18, 0.05), (11, 0.09), (5, 0.16)):
                cr.set_line_width(width)
                cr.set_source_rgba(*self.ACCENT, strength * s.glow * s.alpha)
                cr.stroke_preserve()
        g = cairo.RadialGradient(sx, sy, r_in, sx, sy, r_out)
        a = (0.88 + 0.08 * s.lift) * s.alpha
        g.add_color_stop_rgba(0, *_mix(self.GLASS_HI, self.HOT, s.lift), a)
        g.add_color_stop_rgba(1, *_mix(_mix(self.GLASS, self.HOT, s.lift * 0.6), (1, 1, 1), s.flash), a)
        cr.set_source(g)
        cr.fill_preserve()
        cr.set_line_width(1.4)
        cr.set_source_rgba(*self.ACCENT, (0.36 + 0.5 * s.lift) * s.alpha)
        cr.stroke()
        cr.new_path()  # a thin highlight just inside the outer edge reads as glass
        cr.arc(sx, sy, r_out - 3.5, theta - half + 0.05, theta + half - 0.05)
        cr.set_line_width(1.1)
        cr.set_source_rgba(1, 1, 1, (0.20 + 0.15 * s.lift) * s.alpha)
        cr.stroke()

    def _label(self, cr, s, ox, oy, theta, sc, ink):
        r = self.LABEL_R * sc
        cr.select_font_face(self.FONT, 0, 1)
        cr.set_font_size(22 * (0.9 + 0.1 * sc))
        text = self._text(s)
        ext = cr.text_extents(text)
        cr.move_to(ox + math.cos(theta) * r - ext.width / 2 - ext.x_bearing, oy + math.sin(theta) * r - ext.height / 2 - ext.y_bearing)
        cr.set_source_rgba(*ink, (0.75 + 0.25 * s.lift) * s.alpha)
        cr.show_text(text)
        if s.sub:  # a chevron at the rim says "opens a submenu"
            ux, uy = math.cos(theta), math.sin(theta)
            bx, by = ox + ux * self.CHEV_R * sc, oy + uy * self.CHEV_R * sc
            cr.new_path()
            cr.move_to(bx - ux * 3 - uy * 4, by - uy * 3 + ux * 4)
            cr.line_to(bx + ux * 3, by + uy * 3)
            cr.line_to(bx - ux * 3 + uy * 4, by - uy * 3 - ux * 4)
            cr.set_line_width(1.8)
            cr.set_line_cap(1)
            cr.set_source_rgba(*self.ACCENT, (0.6 + 0.4 * s.lift) * s.alpha)
            cr.stroke()

    def _ghosts(self, cr, cairo, ox, oy, v, shown):
        prev = (ox, oy)
        pts = []
        for g in v.ghosts:  # nearest first; each is joined to the one before it
            gx, gy = ox + g.x * TRAVEL, oy + g.y * TRAVEL
            cr.new_path()
            cr.move_to(*prev)
            cr.line_to(gx, gy)
            cr.set_line_width(2.0)
            cr.set_source_rgba(*self.ACCENT, 0.5 * g.alpha * shown)
            cr.stroke()
            prev = (gx, gy)
            pts.append((g, gx, gy))
        for g, gx, gy in pts:
            r = GHOST_R + 7 * g.lift
            if g.lift > 0.01:
                for width, strength in ((16, 0.06), (9, 0.12)):
                    cr.new_path()
                    cr.arc(gx, gy, r, 0, 2 * math.pi)
                    cr.set_line_width(width)
                    cr.set_source_rgba(*self.ACCENT, strength * g.lift * g.alpha)
                    cr.stroke()
            fade = min(1.0, g.alpha / 0.6)  # the nearest ghost is fully drawn; further ones are dimmer
            grad = cairo.RadialGradient(gx, gy - r * 0.4, 1, gx, gy, r)
            grad.add_color_stop_rgba(0, *_mix(self.GLASS_HI, self.HOT, g.lift), (0.85 + 0.1 * g.lift) * fade)
            grad.add_color_stop_rgba(1, *_mix(self.GLASS, self.HOT, g.lift * 0.6), 0.9 * fade)
            cr.new_path()
            cr.arc(gx, gy, r, 0, 2 * math.pi)
            cr.set_source(grad)
            cr.fill_preserve()
            cr.set_line_width(1.4)
            cr.set_source_rgba(*self.ACCENT, (0.35 + 0.5 * g.lift) * fade)
            cr.stroke()
            if g.label:
                cr.select_font_face("Sora", 0, 1)
                cr.set_font_size(15)
                text = g.label[:1]
                ext = cr.text_extents(text)
                cr.move_to(gx - ext.width / 2 - ext.x_bearing, gy - ext.height / 2 - ext.y_bearing)
                cr.set_source_rgba(*self.LABEL, min(1.0, 0.7 * fade + 0.2 * g.lift))
                cr.show_text(text)

    def _hub(self, cr, cairo, ox, oy, a):
        g = cairo.RadialGradient(ox, oy - 8, 1, ox, oy, HUB_R)
        g.add_color_stop_rgba(0, *self.GLASS_HI, 0.85 * a)
        g.add_color_stop_rgba(1, *self.INK, 0.85 * a)
        cr.new_path()  # show_text leaves a current point: an arc would draw a line from it
        cr.arc(ox, oy, HUB_R, 0, 2 * math.pi)  # the centre: a tap here closes the menu
        cr.set_source(g)
        cr.fill_preserve()
        cr.set_line_width(1.5)
        cr.set_source_rgba(*self.ACCENT, 0.38 * a)
        cr.stroke()

    def _pull(self, cr, v, ox, oy, a, pan):
        cr.new_path()
        cr.arc(ox, oy, R_PULL, 0, 2 * math.pi)  # the activation ring, fading while the pie is still travelling
        cr.set_line_width(1)
        cr.set_source_rgba(*self.ACCENT, 0.16 * a * (1 - min(pan, 1.0)))
        cr.stroke()
        if v.hover is None or v.arc <= 0.01:
            return
        angle = v.back.angle if v.hover < 0 and v.back else v.slices[v.hover].angle if v.hover >= 0 else None
        if angle is None:
            return
        span = v.back.span if v.hover < 0 and v.back else v.slices[v.hover].span
        half = max(span / 2 - GAP / 2, 0.01)
        theta = angle - math.pi / 2
        cr.new_path()  # the pull fills outward from the middle of the hovered slot's arc
        cr.arc(ox, oy, R_PULL, theta - half * v.arc, theta + half * v.arc)
        cr.set_line_width(4)
        cr.set_line_cap(1)
        cr.set_source_rgba(*self.ACCENT, 0.9 * a)
        cr.stroke()
        if v.hover < 0:  # and along the connector toward the parent
            cr.new_path()
            cr.move_to(ox, oy)
            cr.line_to(ox + math.cos(theta) * TRAVEL * v.arc, oy + math.sin(theta) * TRAVEL * v.arc)
            cr.set_line_width(3)
            cr.set_source_rgba(*self.ACCENT, 0.8 * a)
            cr.stroke()

    def _pulse(self, cr, v, ox, oy):
        if v.pulse >= 1.0:
            return
        cr.new_path()
        cr.arc(ox, oy, R_IN * 0.5 + (R_OUT * 1.05 - R_IN * 0.5) * _ease_out(v.pulse), 0, 2 * math.pi)
        cr.set_line_width(2.5)
        cr.set_source_rgba(*self.ACCENT, 0.45 * (1 - v.pulse) ** 1.5)
        cr.stroke()

    def _marker(self, cr, v, ox, oy, a):
        clamp = lambda t: min(max(t, -1.1), 1.1)  # noqa: E731
        self.trail.append(v.marker)
        pts = [(ox + clamp(x) * R_PULL, oy - clamp(y) * R_PULL) for x, y in self.trail]
        cr.new_path()
        for k, (x, y) in enumerate(pts[:-1]):  # a faint trail, oldest smallest
            f = (k + 1) / len(pts)
            cr.arc(x, y, 2 + 3 * f, 0, 2 * math.pi)
            cr.set_source_rgba(*self.ACCENT, 0.25 * f * a)
            cr.fill()
        x, y = pts[-1]
        cr.arc(x, y, 7, 0, 2 * math.pi)
        cr.set_source_rgba(*self.ACCENT, a)
        cr.fill_preserve()
        cr.set_line_width(2)
        cr.set_source_rgba(*self.INK, 0.8 * a)
        cr.stroke()
