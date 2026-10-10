"""Steam user review scores and Steam's Metacritic score for the library page, cached in `steam_rating`.

One row per library key. The appid comes from your Steam library when you own the game, else
from a Steam store search on the exact title (the same strict lookup `art.py` uses). Reviews come
from the public appreviews summary; the Metacritic score from the store's appdetails (only asked
for games whose sheets hold none). No key, no login. Network runs only in `fetch()` (ingest and
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

REVIEWS = "https://store.steampowered.com/appreviews/{appid}?json=1&language=all&purchase_type=all&num_per_page=0"
DETAILS = "https://store.steampowered.com/api/appdetails?appids={appid}&filters=metacritic"
DEFAULTS = {"enabled": True, "budget": 250, "refresh_days": 30, "retry_days": 14, "pause_s": 0.3, "min_reviews": 10}

SCHEMA = """
CREATE TABLE IF NOT EXISTS steam_rating (
  key TEXT PRIMARY KEY, name TEXT NOT NULL,
  appid INTEGER,       -- NULL = no Steam app by this exact title
  positive INTEGER, total INTEGER,
  checked_at TEXT NOT NULL,
  metacritic INTEGER,  -- Steam's copy of the Metacritic score, NULL = none
  mc_checked_at TEXT   -- NULL = never asked
);
"""


def migrate(db: sqlite3.Connection) -> None:
    cols = {r[1] for r in db.execute("PRAGMA table_info(steam_rating)")}
    if cols and "metacritic" not in cols:
        db.execute("ALTER TABLE steam_rating ADD COLUMN metacritic INTEGER")
        db.execute("ALTER TABLE steam_rating ADD COLUMN mc_checked_at TEXT")


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


def metacritic(appid: int) -> int | None | bool:
    """Steam's Metacritic score for an app: the number, None when the store lists none, False when
    the call failed."""
    try:
        body, _ = art._get(DETAILS.format(appid=appid))
        d = json.loads(body)[str(appid)]
        if not d.get("success"):
            return None
        score = ((d.get("data") or {}).get("metacritic") or {}).get("score")
        return int(score) if score else None
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def fetch(db: sqlite3.Connection, wanted: list[tuple], cfg: dict, now: datetime | None = None) -> str:
    """Rate `wanted` ([(key, name, appid or None, needs_metacritic)], most important first) that
    isn't cached or is due a refresh. At most [ratings] budget games a run."""
    s = settings(cfg)
    if not s["enabled"]:
        return "ratings: disabled"
    now = now or datetime.now()
    stamp = now.isoformat(timespec="seconds")
    cached = {k: (a, c, m) for k, a, c, m in db.execute("SELECT key, appid, checked_at, mc_checked_at FROM steam_rating")}
    fresh = (now - timedelta(days=s["refresh_days"])).isoformat(timespec="seconds")
    retry = (now - timedelta(days=s["retry_days"])).isoformat(timespec="seconds")
    todo = []  # (new first, then oldest), key, name, appid, reviews due, metacritic due
    for k, n, a, need_mc in wanted:
        if k not in cached:
            todo.append((0, "", k, n, a, True, bool(need_mc)))
            continue
        app, at, mc_at = cached[k]
        due = at < (fresh if app else retry)
        mc_due = bool(need_mc and app and mc_at is None)
        if due or mc_due:
            todo.append((1, at, k, n, a, due, mc_due))
    todo.sort(key=lambda t: (t[0], t[1]))
    alias = art.aliases(cfg)
    done = miss = 0
    stopped = False
    for _, _, key, name, appid, want_rev, want_mc in todo[: s["budget"]]:
        old = db.execute("SELECT appid, positive, total, checked_at, metacritic, mc_checked_at FROM steam_rating"
                         " WHERE key = ?", (key,)).fetchone()
        appid = appid or (old[0] if old else None)
        if not appid:
            for n in alias.get(key) or [name]:
                appid = art.steam_search(n)
                if appid:
                    break
            time.sleep(s["pause_s"])
        pos, tot, at = (old[1], old[2], old[3]) if old else (None, None, stamp)
        mc, mc_at = (old[4], old[5]) if old else (None, None)
        if appid and want_rev:
            got = summary(appid)
            if got is None:
                stopped = True  # throttled or offline: keep what is cached, try again next run
                break
            (pos, tot), at = got, stamp
            time.sleep(s["pause_s"])
        elif not appid:
            at = stamp
        if appid and want_mc:
            got = metacritic(appid)
            if got is False:
                stopped = True
                break
            mc, mc_at = got, stamp
            time.sleep(s["pause_s"])
        db.execute("INSERT OR REPLACE INTO steam_rating VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (key, name, appid, pos, tot, at, mc, mc_at))
        db.commit()
        done += bool(appid)
        miss += not appid
    left = len(todo) - done - miss if stopped else max(0, len(todo) - s["budget"])
    return (f"ratings: {done} rated, {miss} not on Steam" + (", Steam stopped answering" if stopped else "")
            + (f", {left} left for the next run" if left else ""))


def load(db: sqlite3.Connection, min_reviews: int = DEFAULTS["min_reviews"]) -> dict[str, dict]:
    """{key: {appid, pct, n, mc}} for every game with a Steam app. pct is None under `min_reviews`."""
    out = {}
    for key, appid, pos, tot, mc in db.execute(
            "SELECT key, appid, positive, total, metacritic FROM steam_rating WHERE appid IS NOT NULL"):
        out[key] = {"appid": appid, "mc": mc,
                    "pct": round(100 * pos / tot) if tot and tot >= min_reviews else None, "n": tot}
    return out


def wanted(rows: list[dict]) -> list[tuple[str, str, int | None, bool]]:
    """Library rows as fetch() wants them: games that can leave first (the leaving page shows
    their score), then games you own on Steam (appid known), then the rest. The last field says
    the game has no Metacritic yet."""
    def rank(r):
        return 0 if r.get("gp_leaves") or r.get("ps_leaves") else 1 if r.get("steam") else 2
    return [(r["key"], r["game"], r.get("appid"), r.get("mc") is None) for r in sorted(rows, key=rank)]


def attach(rows: list[dict], rated: dict[str, dict]) -> None:
    for r in rows:
        x = rated.get(r["key"])
        if not x:
            continue
        r.setdefault("appid", x["appid"])
        if x["pct"] is not None:
            r["rating"], r["reviews"] = x["pct"], x["n"]
        if r.get("mc") is None and x.get("mc"):
            r["mc"] = float(x["mc"])
