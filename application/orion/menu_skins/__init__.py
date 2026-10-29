"""Skins for the OrionDo pie: each turns the animation model's `MenuView` into cairo drawing.

A skin is a class with `MOTION` (keyword arguments for `MenuAnim`, may be empty) and `draw(cr, view, w, h)`. The overlay
runs as a script, so skins use relative imports only and import nothing from the rest of the app; they read the view they are given. To add one, drop a
file here that registers it with `@skin("name")` and import it below; select it with `skin = "name"` in
`[gestures.oriondo]`. An unknown name draws with the default.
"""

DEFAULT = "aurora"
_SKINS = {}


def skin(name):
    def register(cls):
        _SKINS[name] = cls()
        return cls
    return register


def get_skin(name):
    return _SKINS.get(name) or _SKINS[DEFAULT]


def names():
    return sorted(_SKINS)


from . import aurora, compass, ember, frost, halo, neon, orbit, paper, petal, reticle, terminal  # noqa: E402, F401  (each registers itself)
