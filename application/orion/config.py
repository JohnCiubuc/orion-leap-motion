"""TOML config + XDG paths. Hand edits are picked up live (mtime polling);
saves from the UI go through tomlkit so your comments and layout survive."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import tomlkit

APP = "orion-renewal"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / APP
CONFIG_FILE = CONFIG_DIR / "config.toml"
PLUGIN_DIR = CONFIG_DIR / "plugins"
TEMPLATES_FILE = CONFIG_DIR / "templates.json"
RECORDINGS_DIR = DATA_DIR / "recordings"
DEFAULT_FILE = Path(__file__).with_name("default.toml")


class Config:
    def __init__(self, path: Path = CONFIG_FILE):
        self.path = Path(path)
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(DEFAULT_FILE.read_text())
        PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
        self.load()

    def load(self):
        defaults = tomllib.loads(DEFAULT_FILE.read_text())
        self.data = tomllib.loads(self.path.read_text())
        self.data["general"] = {**defaults["general"], **self.data.get("general", {})}
        for key in ("gestures", "profiles", "modes"):
            self.data.setdefault(key, {})
        self.data.setdefault("bindings", [])
        self.mtime = self.path.stat().st_mtime

    def changed_on_disk(self) -> bool:
        try:
            return self.path.stat().st_mtime != self.mtime
        except FileNotFoundError:
            return False

    def save(self, data: dict | None = None):
        if data is not None:
            self.data = data
        doc = tomlkit.parse(self.path.read_text())
        _merge(doc, self.data)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(tomlkit.dumps(doc))
        tmp.replace(self.path)  # atomic: a half-written file is never read
        self.mtime = self.path.stat().st_mtime

    def __getitem__(self, key):
        return self.data[key]

    @property
    def general(self) -> dict:
        return self.data["general"]


def _merge(doc, data: dict):
    """Write `data` into a tomlkit document in place, keeping comments on untouched keys."""
    for k in [k for k in doc if k not in data]:
        del doc[k]
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(doc.get(k), dict):
            _merge(doc[k], v)
        elif doc.get(k) != v:
            doc[k] = _clean(v)


def _clean(v):  # drop None (TOML has no null)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v
