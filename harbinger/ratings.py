"""Steam user review scores, Steam's Metacritic score and a trailer for the library page, cached in `steam_rating`.

One row per library key. The appid comes from your Steam library when you own the game, else
from a Steam store search on the exact title (the same strict lookup `art.py` uses). Reviews come
from the public appreviews summary; the Metacritic score from the store's appdetails (only asked
for games whose sheets hold none, in the same call that finds the trailer). No key, no login. Network runs only in `fetch()` (ingest and
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
DETAILS = "https://store.steampowered.com/api/appdetails?appids={appid}&filters=metacritic,movies"
# the API lists only HLS/DASH streams now; the 480p mp4 of the same movie id is still on the CDN and
# is the one file every browser plays with a plain <video> and seeks with a Range request
MOVIE_MP4 = "https://cdn.akamai.steamstatic.com/steam/apps/{id}/movie480.mp4"
MOVIE_TRIES = 2   # best-ranked movies checked for a live mp4 before giving up
DEFAULTS = {"enabled": True, "budget": 250, "refresh_days": 30, "retry_days": 14, "pause_s": 0.3, "min_reviews": 10,
            "cooldown_hours": 1.0, "respect_cooldown": True}

SCHEMA = """
CREATE TABLE IF NOT EXISTS steam_rating (
  key TEXT PRIMARY KEY, name TEXT NOT NULL,
  appid INTEGER,       -- NULL = no Steam app by this exact title
  positive INTEGER, total INTEGER,
  checked_at TEXT NOT NULL,
  metacritic INTEGER,  -- Steam's copy of the Metacritic score, NULL = none
  mc_checked_at TEXT,  -- NULL = never asked
  trailer TEXT,        -- https mp4 of the store trailer, NULL = none
  trailer_poster TEXT,
  trailer_checked_at TEXT  -- NULL = never asked
);
CREATE TABLE IF NOT EXISTS fill_state (k TEXT PRIMARY KEY, v TEXT NOT NULL);  -- "cooldown_until": ISO time

"""


def migrate(db: sqlite3.Connection) -> None:
    cols = {r[1] for r in db.execute("PRAGMA table_info(steam_rating)")}
    if cols and "metacritic" not in cols:
        db.execute("ALTER TABLE steam_rating ADD COLUMN metacritic INTEGER")
        db.execute("ALTER TABLE steam_rating ADD COLUMN mc_checked_at TEXT")
    if cols and "trailer" not in cols:
        for c in ("trailer TEXT", "trailer_poster TEXT", "trailer_checked_at TEXT"):
            db.execute(f"ALTER TABLE steam_rating ADD COLUMN {c}")


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **cfg.get("ratings", {})}


def cooldown_until(db: sqlite3.Connection) -> datetime | None:
    """When Steam last pushed back, the time before which no run asks it again."""
    r = db.execute("SELECT v FROM fill_state WHERE k = 'cooldown_until'").fetchone()
    return datetime.fromisoformat(r[0]) if r else None


def _cool_down(db: sqlite3.Connection, now: datetime, hours: float) -> None:
    until = (now + timedelta(hours=hours)).isoformat(timespec="seconds")
    db.execute("INSERT OR REPLACE INTO fill_state VALUES ('cooldown_until', ?)", (until,))
    db.commit()


def summary(appid: int) -> tuple[int, int] | None:
    """(positive, total) user reviews of a Steam app, or None when the call fails."""
    try:
        body, _ = art._get(REVIEWS.format(appid=appid))
        q = json.loads(body)["query_summary"]
        return int(q["total_positive"]), int(q["total_reviews"])
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        return None


def rank_movies(movies: list[dict]) -> list[dict]:
    """The store movies best first for a quick look: gameplay footage, then anything but a teaser or
    an announcement, then the rest, each group in the store's own order."""
    def score(m):
        name = (m.get("name") or "").lower()
        if "gameplay" in name:
            return 0
        if any(w in name for w in ("teaser", "announce", "reveal", "cinematic", "accolades", "review")):
            return 2
        return 1
    return sorted((m for m in movies if isinstance(m, dict) and isinstance(m.get("id"), int)), key=score)


def _live(url: str) -> bool:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": art.UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200 and r.headers.get("Content-Type", "").startswith("video/")
    except (urllib.error.URLError, OSError, ValueError):
        return False


def details(appid: int) -> tuple[int | None, dict | None] | bool:
    """(Metacritic score or None, trailer {src, poster, name} or None) for an app, or False when the
    call failed."""
    try:
        body, _ = art._get(DETAILS.format(appid=appid))
        d = json.loads(body)[str(appid)]
        if not d.get("success"):
            return None, None
        data = d.get("data") or {}
        score = (data.get("metacritic") or {}).get("score")
        movies = data.get("movies") or []
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, AttributeError):
        return False
    trailer = None
    for m in rank_movies(movies)[:MOVIE_TRIES]:
        src = MOVIE_MP4.format(id=m["id"])
        if _live(src):
            poster = m.get("thumbnail") or ""
            trailer = {"src": src, "poster": poster if poster.startswith("https://") else "",
                       "name": str(m.get("name") or "")}
            break
    return (int(score) if score else None), trailer


def fetch(db: sqlite3.Connection, wanted: list[tuple], cfg: dict, now: datetime | None = None) -> str:
    """Rate `wanted` ([(key, name, appid or None, needs_metacritic)], most important first) that
    isn't cached or is due a refresh; games cached before trailers existed get theirs the same way.
    At most [ratings] budget games a run."""
    s = settings(cfg)
    if not s["enabled"]:
        return "ratings: disabled"
    now = now or datetime.now()
    until = cooldown_until(db)
    if s["respect_cooldown"] and until and until > now:  # Steam pushed back recently: don't keep knocking
        return f"ratings: cooling down until {until:%H:%M}"
    stamp = now.isoformat(timespec="seconds")
    cached = {k: (a, c, m, t, ta) for k, a, c, m, t, ta in db.execute(
        "SELECT key, appid, checked_at, mc_checked_at, trailer, trailer_checked_at FROM steam_rating")}
    fresh = (now - timedelta(days=s["refresh_days"])).isoformat(timespec="seconds")
    retry = (now - timedelta(days=s["retry_days"])).isoformat(timespec="seconds")
    todo = []  # (new first, then oldest), key, name, appid, reviews due, metacritic due, trailer due
    for k, n, a, need_mc in wanted:
        if k not in cached:
            todo.append((0, "", k, n, a, True, bool(need_mc), True))
            continue
        app, at, mc_at, trailer, tr_at = cached[k]
        due = at < (fresh if app else retry)
        mc_due = bool(need_mc and app and mc_at is None)
        tr_due = bool(app and (tr_at is None or (trailer is None and tr_at < fresh)))
        if due or mc_due or tr_due:
            todo.append((1, at, k, n, a, due, mc_due, tr_due))
    todo.sort(key=lambda t: (t[0], t[1]))
    alias = art.aliases(cfg)
    done = miss = 0
    stopped = False
    for _, _, key, name, appid, want_rev, want_mc, want_tr in todo[: s["budget"]]:
        old = db.execute("SELECT appid, positive, total, checked_at, metacritic, mc_checked_at, trailer,"
                         " trailer_poster, trailer_checked_at FROM steam_rating WHERE key = ?", (key,)).fetchone()
        appid = appid or (old[0] if old else None)
        if not appid:
            for n in alias.get(key) or [name]:
                appid = art.steam_search(n)
                if appid:
                    break
            time.sleep(s["pause_s"])
        pos, tot, at = (old[1], old[2], old[3]) if old else (None, None, stamp)
        mc, mc_at = (old[4], old[5]) if old else (None, None)
        tr, poster, tr_at = (old[6], old[7], old[8]) if old else (None, None, None)
        if appid and want_rev:
            got = summary(appid)
            if got is None:
                stopped = True  # throttled or offline: keep what is cached, try again next run
                break
            (pos, tot), at = got, stamp
            time.sleep(s["pause_s"])
        elif not appid:
            at = stamp
        if appid and (want_mc or want_tr):  # one store call answers both
            got = details(appid)
            if got is False:
                stopped = True
                break
            if want_mc:
                mc, mc_at = got[0], stamp
            if want_tr:
                tr, poster, tr_at = (got[1]["src"], got[1]["poster"], stamp) if got[1] else (None, None, stamp)
            time.sleep(s["pause_s"])
        db.execute("INSERT OR REPLACE INTO steam_rating (key, name, appid, positive, total, checked_at, metacritic,"
                   " mc_checked_at, trailer, trailer_poster, trailer_checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (key, name, appid, pos, tot, at, mc, mc_at, tr, poster, tr_at))
        db.commit()
        done += bool(appid)
        miss += not appid
    if stopped:
        _cool_down(db, now, s["cooldown_hours"])
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


def trailers(db: sqlite3.Connection) -> dict[str, dict]:
    """{key: {src, poster}} for every game with a trailer."""
    return {k: {"src": t, "poster": p or ""} for k, t, p in db.execute(
        "SELECT key, trailer, trailer_poster FROM steam_rating WHERE trailer LIKE 'https://%'")}


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


def attach_trailers(data: dict, found: dict[str, dict]) -> None:
    """Put each game's trailer on every row of the page that shows it."""
    for r in art.rows(data):
        t = found.get(r.get("key") or norm(r["game"]))
        if t:
            r["trailer"] = t
