"""Steam user review scores for the library page, cached in `steam_rating`.

One row per library key. The appid comes from your Steam library when you own the game, else
from a Steam store search on the exact title (the same strict lookup `art.py` uses). Reviews come
from the public appreviews summary: no key, no login. Network runs only in `fetch()` (ingest and
steam, never build), capped by `[ratings] budget` per run; Steam's rate limit (HTTP 429) ends the
run early and the rest waits for the next one.
"""

from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from . import art
from .sheet import norm

REVIEWS = "https://store.steampowered.com/appreviews/{appid}?json=1&language=all&purchase_type=all&num_per_page=0"
DEFAULTS = {"enabled": True, "budget": 250, "refresh_days": 30, "retry_days": 14, "pause_s": 0.3, "min_reviews": 10}

SCHEMA = """
CREATE TABLE IF NOT EXISTS steam_rating (
  key TEXT PRIMARY KEY, name TEXT NOT NULL,
  appid INTEGER,       -- NULL = no Steam app by this exact title
  positive INTEGER, total INTEGER,
  checked_at TEXT NOT NULL
);
"""


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **cfg.get("ratings", {})}


def summary(appid: int) -> tuple[int, int] | None:
    """(positive, total) user reviews of a Steam app, or None when the call fails."""
    try:
        body, _ = art._get(REVIEWS.format(appid=appid))
        q = json.loads(body)["query_summary"]
        return int(q["total_positive"]), int(q["total_reviews"])
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        return None


def fetch(db: sqlite3.Connection, wanted: list[tuple[str, str, int | None]], cfg: dict,
          now: datetime | None = None) -> str:
    """Rate `wanted` ([(key, name, appid or None)], most important first) that isn't cached or is
    due a refresh. At most [ratings] budget games a run."""
    s = settings(cfg)
    if not s["enabled"]:
        return "ratings: disabled"
    now = now or datetime.now()
    cached = {k: (a, c) for k, a, c in db.execute("SELECT key, appid, checked_at FROM steam_rating")}
    fresh = (now - timedelta(days=s["refresh_days"])).isoformat(timespec="seconds")
    retry = (now - timedelta(days=s["retry_days"])).isoformat(timespec="seconds")
    # a game never rated goes first, then the oldest rating
    todo = [(0, "", k, n, a) for k, n, a in wanted if k not in cached]
    todo += [(1, cached[k][1], k, n, a) for k, n, a in wanted if k in cached
             and cached[k][1] < (fresh if cached[k][0] else retry)]
    todo.sort(key=lambda t: (t[0], t[1]))
    alias = art.aliases(cfg)
    done = miss = 0
    for _, _, key, name, appid in todo[: s["budget"]]:
        appid = appid or cached.get(key, (None,))[0]
        if not appid:
            for n in alias.get(key) or [name]:
                appid = art.steam_search(n)
                if appid:
                    break
            time.sleep(s["pause_s"])
        got = summary(appid) if appid else None
        if appid and got is None:
            break  # throttled or offline: keep what is cached, try again next run
        pos, tot = got if got else (None, None)
        db.execute("INSERT OR REPLACE INTO steam_rating VALUES (?, ?, ?, ?, ?, ?)",
                   (key, name, appid, pos, tot, now.isoformat(timespec="seconds")))
        db.commit()
        done += got is not None
        miss += got is None
        time.sleep(s["pause_s"])
    left = max(0, len(todo) - s["budget"])
    return f"ratings: {done} rated, {miss} not on Steam" + (f", {left} left for the next run" if left else "")


def load(db: sqlite3.Connection, min_reviews: int = DEFAULTS["min_reviews"]) -> dict[str, dict]:
    """{key: {appid, pct, n}} for every rated game. pct is None under `min_reviews` reviews."""
    out = {}
    for key, appid, pos, tot in db.execute("SELECT key, appid, positive, total FROM steam_rating WHERE appid IS NOT NULL"):
        out[key] = {"appid": appid, "pct": round(100 * pos / tot) if tot and tot >= min_reviews else None, "n": tot}
    return out


def wanted(rows: list[dict]) -> list[tuple[str, str, int | None]]:
    """Library rows as fetch() wants them: games you own on Steam first (appid known)."""
    own = [(r["key"], r["game"], r.get("appid")) for r in rows if r.get("steam")]
    rest = [(r["key"], r["game"], r.get("appid")) for r in rows if not r.get("steam")]
    return own + rest


def attach(rows: list[dict], rated: dict[str, dict]) -> None:
    for r in rows:
        x = rated.get(r["key"])
        if not x:
            continue
        r.setdefault("appid", x["appid"])
        if x["pct"] is not None:
            r["rating"], r["reviews"] = x["pct"], x["n"]
