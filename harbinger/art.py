"""Cover art for the games on the page, cached on disk and served from our own server.

One row per sheet key in `game_art`. Sources, strictest first (every name match is exact on
`sheet.norm()`, so a sequel never borrows the original's cover):

1. your Steam library (`steam_game`, appid known)      -> Steam CDN
2. your PlayStation library (`psn_game.image_url`)      -> Sony's icon
3. Steam store search, exact name                       -> Steam CDN
4. Microsoft Store search (Games), exact name           -> store icon

Network runs only in `fetch()` (ingest and steam, never build) and is capped per run by
`[art] budget`; a miss is retried after `[art] retry_days`. Files live in `state/art/`, are named
by a hash of the key, and are shrunk with Pillow when it is installed (optional).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from . import STATE_DIR
from .sheet import norm

ART_DIR = STATE_DIR / "art"
URL_PREFIX = "/art/"
FILE_RE = re.compile(r"^[0-9a-f]{16}\.(jpg|png)$")
STEAM_CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/{name}"
STEAM_IMAGES = ("library_600x900.jpg", "header.jpg")   # portrait cover, then the wide banner
STEAM_DETAILS = "https://store.steampowered.com/api/appdetails?appids={appid}&filters=basic"
STEAM_SEARCH = "https://store.steampowered.com/api/storesearch/?term={q}&cc=us&l=en"
MS_SEARCH = ("https://displaycatalog.mp.microsoft.com/v7.0/productFamilies/autosuggest"
             "?market=US&languages=en-US&query={q}&productFamilyNames=games")
UA = "harbinger (github.com/yaqzan/harbinger)"
DEFAULTS = {"enabled": True, "budget": 150, "retry_days": 14, "max_px": 240, "pause_s": 0.2}

SCHEMA = """
CREATE TABLE IF NOT EXISTS game_art (
  key TEXT PRIMARY KEY, name TEXT NOT NULL,
  source TEXT,                    -- steam | psn | steam search | microsoft store
  file TEXT,                      -- name inside state/art/, NULL = looked and found nothing
  checked_at TEXT NOT NULL
);
"""


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **cfg.get("art", {})}


def file_for(key: str, ext: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + "." + ext


def clean(name: str) -> str:
    """The title a store knows: no "(2020)" release year or "(Game Preview)" tag."""
    return re.sub(r"\s*\((?:(?:19|20)\d\d|game preview|xbox game preview|preview)\)", "", name, flags=re.I).strip()


# ── network ────────────────────────────────────────────────────────────

def _get(url: str, timeout: int = 20) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def _image(url: str) -> tuple[bytes, str] | None:
    """The image at url as (bytes, extension), or None for anything that isn't a picture."""
    try:
        body, ctype = _get(url)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    ctype = ctype.split(";")[0].strip().lower()
    if ctype not in ("image/jpeg", "image/png") or not body:
        return None
    return body, "png" if ctype == "image/png" else "jpg"


def _shrink(body: bytes, ext: str, max_px: int) -> tuple[bytes, str]:
    try:
        from PIL import Image
    except ImportError:
        return body, ext
    try:
        im = Image.open(io.BytesIO(body))
        im.thumbnail((max_px, max_px))
        out = io.BytesIO()
        if ext == "png" and im.mode in ("RGBA", "LA", "P"):
            im.save(out, "PNG", optimize=True)
            return out.getvalue(), "png"
        im.convert("RGB").save(out, "JPEG", quality=82, optimize=True)
        return out.getvalue(), "jpg"
    except Exception:  # a file Pillow can't read is still a picture the browser may
        return body, ext


def steam_art(appid: int) -> tuple[bytes, str] | None:
    for name in STEAM_IMAGES:
        got = _image(STEAM_CDN.format(appid=appid, name=name))
        if got:
            return got
    try:  # newer apps keep art under a hashed path the fixed names don't reach
        body, _ = _get(STEAM_DETAILS.format(appid=appid))
        url = json.loads(body)[str(appid)]["data"].get("header_image") or ""
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        return None
    return _image(url) if url.startswith("https://") else None


def steam_search(name: str) -> int | None:
    """Appid of the Steam app whose name is exactly this title, else None."""
    name = clean(name)
    try:
        body, _ = _get(STEAM_SEARCH.format(q=urllib.parse.quote(name)))
        items = json.loads(body).get("items", [])
    except (urllib.error.URLError, OSError, ValueError):
        return None
    want = norm(name)
    for it in items:
        if it.get("type") == "app" and norm(it.get("name") or "") == want:
            return int(it["id"])
    return None


def microsoft_art(name: str) -> tuple[bytes, str] | None:
    name = clean(name)
    try:
        body, _ = _get(MS_SEARCH.format(q=urllib.parse.quote(name)))
        groups = json.loads(body).get("Results", [])
    except (urllib.error.URLError, OSError, ValueError):
        return None
    want = norm(name)
    for grp in groups:
        for p in grp.get("Products", []):
            icon = p.get("Icon") or ""
            if norm(p.get("Title") or "") == want and icon:
                return _image("https:" + icon if icon.startswith("//") else icon)
    return None


# ── resolving ──────────────────────────────────────────────────────────

def _local_source(db: sqlite3.Connection, key: str) -> tuple[str, int | str] | None:
    """A source we already hold an id or url for: (kind, appid or image url)."""
    r = db.execute("SELECT appid FROM steam_game WHERE key = ? AND owned = 1 LIMIT 1", (key,)).fetchone()
    if r:
        return "steam", r[0]
    r = db.execute("SELECT image_url FROM psn_game WHERE key = ? AND present = 1 AND COALESCE(image_url, '') != ''"
                   " LIMIT 1", (key,)).fetchone()
    if r:
        return "psn", r[0]
    return None


def aliases(cfg: dict) -> dict[str, list[str]]:
    """{sheet key: [store titles]} from the [art] table of titles.toml."""
    return {norm(k): [v] if isinstance(v, str) else list(v) for k, v in cfg.get("titles", {}).get("art", {}).items()}


def resolve(db: sqlite3.Connection, key: str, name: str, names: list[str] | None = None) -> tuple[str, bytes, str] | None:
    """(source, bytes, ext) for a game, or None when no source has it. `names` are the titles the
    stores use for it when they differ from the sheet's."""
    local = _local_source(db, key)
    if local and local[0] == "steam":
        got = steam_art(local[1])
        if got:
            return "steam", *got
    if local and local[0] == "psn":
        got = _image(local[1])
        if got:
            return "psn", *got
    for n in names or [name]:
        appid = steam_search(n)
        if appid:
            got = steam_art(appid)
            if got:
                return "steam search", *got
        got = microsoft_art(n)
        if got:
            return "microsoft store", *got
    return None


def fetch(db: sqlite3.Connection, wanted: dict[str, str], cfg: dict, now: datetime | None = None) -> str:
    """Look up art for `wanted` ({key: name}, most important first) that isn't cached yet.
    At most [art] budget lookups a run; a failed sync or a dead network keeps what's cached."""
    s = settings(cfg)
    if not s["enabled"]:
        return "art: disabled"
    now = now or datetime.now()
    ART_DIR.mkdir(parents=True, exist_ok=True)
    cached = {k: (f, at) for k, f, at in db.execute("SELECT key, file, checked_at FROM game_art")}
    retry_before = (now - timedelta(days=s["retry_days"])).isoformat(timespec="seconds")
    todo = [(k, n) for k, n in wanted.items()
            if k not in cached or (cached[k][0] is None and cached[k][1] < retry_before)
            or (cached[k][0] and not (ART_DIR / cached[k][0]).exists())]
    alias = aliases(cfg)
    got = miss = 0
    for key, name in todo[: s["budget"]]:
        found = resolve(db, key, name, alias.get(key) or alias.get(norm(name)))
        if found:
            source, body, ext = found
            body, ext = _shrink(body, ext, s["max_px"])
            fname = file_for(key, ext)
            (ART_DIR / fname).write_bytes(body)
            row = (key, name, source, fname)
            got += 1
        else:
            row = (key, name, None, None)
            miss += 1
        db.execute("INSERT OR REPLACE INTO game_art (key, name, source, file, checked_at) VALUES (?, ?, ?, ?, ?)",
                   (*row, now.isoformat(timespec="seconds")))
        db.commit()
        time.sleep(s["pause_s"])
    left = max(0, len(todo) - s["budget"])
    return f"art: {got} found, {miss} missing" + (f", {left} left for the next run" if left else "")


def load(db: sqlite3.Connection) -> dict[str, str]:
    """{key: "/art/<file>"} for every game whose picture is on disk."""
    return {k: URL_PREFIX + f for k, f in db.execute("SELECT key, file FROM game_art WHERE file IS NOT NULL")
            if FILE_RE.match(f) and (ART_DIR / f).exists()}


def wanted(data: dict) -> dict[str, str]:
    """Every game the page shows, keyed by sheet key, in the order the page cares about them."""
    out: dict[str, str] = {}
    for section in ("confirmed", "queue", "watchlist", "owned"):
        for r in data.get(section, []):
            key = r.get("key") or norm(r["game"])
            out.setdefault(key, r["game"])
    one = data.get("one_service", {})
    # soonest exit first, dimmed backups included: the shelf shows them side by side
    for r in sorted(one.get("rows", []) + one.get("backups", []), key=lambda r: r.get("wave") or "9999"):
        out.setdefault(r.get("key") or norm(r["game"]), r["game"])
    return out


def attach(data: dict, art: dict[str, str]) -> None:
    """Put `art` on every row whose game has a picture."""
    rows = [r for s in ("confirmed", "queue", "watchlist", "owned") for r in data.get(s, [])]
    one = data.get("one_service", {})
    rows += one.get("rows", []) + one.get("backups", [])
    for r in rows:
        url = art.get(r.get("key") or norm(r["game"]))
        if url:
            r["art"] = url
