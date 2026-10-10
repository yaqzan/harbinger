"""Harbinger: which Game Pass games are leaving, and which of them you can still finish.

State lives in harbinger/state/ (gitignored): harbinger.sqlite (the imported sheet, the
Steam library, title matches, score snapshots), the forecast and data.json. `serve` hands the page in web/ plus state/data.json.

Settings: harbinger/config.toml (shared model numbers, tracked) overlaid by
config.local.toml at the repo root (your Steam account, watched games, push settings;
gitignored). Copy config.local.example.toml to start one.
"""

import tomllib
from pathlib import Path

__version__ = "1.1.0"

PKG_DIR = Path(__file__).resolve().parent
ROOT = PKG_DIR.parent
STATE_DIR = PKG_DIR / "state"
WEB_DIR = ROOT / "web"
CONFIG_FILE = PKG_DIR / "config.toml"
LOCAL_CONFIG_FILE = ROOT / "config.local.toml"
TITLES_FILE = PKG_DIR / "titles.toml"
OUTPUT_FILE = STATE_DIR / "data.json"
LIBRARY_FILE = STATE_DIR / "library.json"  # every game on a service or in your libraries, for /library


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: Path = CONFIG_FILE, local: Path | None = LOCAL_CONFIG_FILE) -> dict:
    """The shared config with your local one merged over it (tables merge, values replace).

    Tests pass local=None so a developer's own watchlist never changes their results.
    Title corrections (titles.toml) land in cfg["titles"].
    """
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    if local is not None and local.exists():
        with open(local, "rb") as f:
            cfg = _merge(cfg, tomllib.load(f))
    if TITLES_FILE.exists():
        with open(TITLES_FILE, "rb") as f:
            cfg["titles"] = tomllib.load(f)
    return cfg
