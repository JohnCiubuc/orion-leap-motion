"""Catppuccin: flat panes in the chosen flavour (latte, frappe, macchiato, mocha) with one of its accents on the hovered slice.

The palette is fixed, so the hue tint does not apply; `options` = {"flavor": ..., "accent": ...} picks it (default mocha, mauve).
"""

import math

from . import skin
from .aurora import Aurora, _mix

ACCENTS = ("rosewater", "flamingo", "pink", "mauve", "red", "maroon", "peach", "yellow", "green", "teal", "sky", "sapphire", "blue", "lavender")
# per flavour: crust, surface1, surface0, base, text, then the 14 accents in ACCENTS order
FLAVORS = {
    "latte": "dce0e8 bcc0cc ccd0da eff1f5 4c4f69 dc8a78 dd7878 ea76cb 8839ef d20f39 e64553 fe640b df8e1d 40a02b 179299 04a5e5 209fb5 1e66f5 7287fd",
    "frappe": "232634 51576d 414559 303446 c6d0f5 f2d5cf eebebe f4b8e4 ca9ee6 e78284 ea999c ef9f76 e5c890 a6d189 81c8be 99d1db 85c1dc 8caaee babbf1",
    "macchiato": "181926 494d64 363a4f 24273a cad3f5 f4dbd6 f0c6c6 f5bde6 c6a0f6 ed8796 ee99a0 f5a97f eed49f a6da95 8bd5ca 91d7e3 7dc4e4 8aadf4 b7bdf8",
    "mocha": "11111b 45475a 313244 1e1e2e cdd6f4 f5e0dc f2cdcd f5c2e7 cba6f7 f38ba8 eba0ac fab387 f9e2af a6e3a1 94e2d5 89dceb 74c7ec 89b4fa b4befe",
}


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _palette(flavor, accent):
    f = [_rgb(x) for x in FLAVORS.get(flavor, FLAVORS["mocha"]).split()]
    crust, edge, pane, base, text, accents = f[0], f[1], f[2], f[3], f[4], f[5:]
    acc = accents[ACCENTS.index(accent)] if accent in ACCENTS else accents[ACCENTS.index("mauve")]
    light = flavor == "latte"
    return {"INK": crust, "GLASS": base if light else pane, "GLASS_HI": edge, "HOT": acc, "ACCENT": acc,
            "LABEL": text, "LABEL_HOT": base if light else crust}


@skin("catppuccin")
class Catppuccin(Aurora):
    locals().update(_palette("mocha", "mauve"))
    HUE = 0
    FIXED_PALETTE = True  # the hue tint does not apply

    def tune(self, hue=None, invert=False, options=None):
        o = options or {}
        for name, c in _palette(o.get("flavor"), o.get("accent")).items():
            setattr(self, name, tuple(1 - x for x in c) if invert and name.startswith("LABEL") else c)

    def _slice(self, cr, cairo, s, sx, sy, theta, half, r_in, r_out):
        cr.new_path()
        cr.arc(sx, sy, r_out, theta - half, theta + half)
        cr.arc_negative(sx, sy, r_in, theta + half, theta - half)
        cr.close_path()
        cr.set_line_join(1)
        cr.set_source_rgba(*_mix(_mix(self.GLASS, self.HOT, s.lift), (1, 1, 1), s.flash * 0.5), 0.97 * s.alpha)
        cr.fill_preserve()
        cr.set_line_width(1.5)
        cr.set_source_rgba(*_mix(self.GLASS_HI, self.HOT, s.lift), s.alpha)
        cr.stroke()
