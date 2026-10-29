"""A PNG of a skin for the editor: the real skin, drawn with the user's labels and slice sizes, one slice hovered.

pycairo lives in the system Python (the overlay's), not in the engine's venv, so `png` runs this file as a script there.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SIZE = 560  # the overlay window's size


def png(name, labels, weights=None, hue=None, invert=False) -> bytes:
    python = os.environ.get("ORION_OVERLAY_PYTHON") or shutil.which("python3", path="/usr/bin:/bin")
    arg = json.dumps({"name": name, "labels": labels, "weights": weights, "hue": hue, "invert": invert})
    return subprocess.run([python, str(Path(__file__)), arg], capture_output=True, timeout=10, check=True).stdout


def _draw(arg):
    import cairo
    from menu_anim import MenuAnim  # bare imports, like overlay_menu.py: this runs as a script
    from menu_skins import get_skin
    a = json.loads(arg)
    skin = get_skin(a["name"])
    if hasattr(skin, "tune"):
        skin.tune(a["hue"], a["invert"])
    anim = MenuAnim(**skin.MOTION)
    anim.open(a["labels"], 0.0, None, a["weights"])
    anim.update(0.0, 0.5, 1 if len(a["labels"]) > 1 else 0, 0.45, 0.0)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, SIZE, SIZE)
    cr = cairo.Context(surf)
    cr.set_source_rgb(0.04, 0.05, 0.1)  # a dark desktop behind the translucent pie
    cr.paint()
    skin.draw(cr, anim.step(2.0), SIZE, SIZE)
    surf.write_to_png(sys.stdout.buffer)


if __name__ == "__main__":
    _draw(sys.argv[1])
