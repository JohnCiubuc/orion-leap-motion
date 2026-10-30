"""The overlay menu window's logic without GTK: engine ops in, a skin-drawn view out.

Dependencies are injected (`anim_factory` builds a MenuAnim, `get_skin` looks a skin up by name), so this file imports
nothing from orion and works both bare-imported by the overlay script and as `orion.menu_ctl` in tests.
"""

import logging

log = logging.getLogger("orion.menu")


class MenuController:
    def __init__(self, anim_factory, get_skin, reduced_motion=False):
        self.anim_factory, self.get_skin, self.reduced = anim_factory, get_skin, reduced_motion
        self.anim = self.skin = None
        self.failed = set()  # skins that raised while drawing; they are not used again
        self.broken = False  # the default skin raised too: nothing is drawn from then on

    def handle(self, msg, now):
        op = msg.get("op")
        if op == "open":
            self._open(msg, now)
        elif self.anim is None:
            return
        elif op == "enter":
            self.anim.enter(msg["labels"], now, msg["back"], msg.get("parent", ""), msg.get("subs"), msg.get("weights"))
        elif op == "back":
            self.anim.back(msg["labels"], now, msg["back"], msg["away"], msg.get("subs"), msg.get("weights"))
        elif op == "update":
            self.anim.update(msg["x"], msg["y"], msg["hover"], msg["pull"], now)
        elif op == "fire":
            self.anim.fire(msg["index"], now)
        elif op == "close":
            self.anim.close(now)

    def _open(self, msg, now):
        skin = self.get_skin(msg.get("skin"))
        if skin in self.failed:
            skin = self.get_skin(None)
        if skin in self.failed:
            self.broken = True
            return
        self.skin = skin
        if hasattr(skin, "tune"):
            skin.tune(msg.get("hue"), msg.get("invert", False), msg.get("options"))
        self.anim = self.anim_factory(reduced_motion=self.reduced, **skin.MOTION)
        self.anim.open(msg["labels"], now, msg.get("subs"), msg.get("weights"))

    def view(self, now):
        """The current MenuView, or None when nothing should be on screen."""
        return None if self.broken or self.anim is None else self.anim.step(now)

    def draw(self, cr, view, w, h) -> bool:
        """False if the skin raised: the caller hides the window. A skin that raised is not used for later menus."""
        try:
            self.skin.draw(cr, view, w, h)
            return True
        except Exception:
            log.exception("menu skin %s failed to draw", type(self.skin).__name__)
            self.failed.add(self.skin)
            self.broken = self.skin is self.get_skin(None)  # the default has nothing to fall back to
            self.anim = None
            return False
