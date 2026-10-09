"""PlayStation library through Sony's PSN API, imported into SQLite.

The calls psn-api (github.com/achievements-app/psn-api) makes, in the stdlib: NPSSO -> access
code -> access + refresh tokens, then purchased games (GraphQL), played games with playtime
and trophy progress, all for the signed-in account ("me").

The NPSSO comes from the PSN_NPSSO environment variable, else `[playstation] npsso` in
config.local.toml (gitignored). Tokens are cached in state/psn_tokens.json (gitignored); the
refresh token lasts about two months, then a fresh NPSSO is needed. Disc games can't be seen
by any API: list them under `[playstation] discs` in config.local.toml.

Tables: `psn_game` (kind purchased | played), `psn_trophy`, `psn_history` (a row whenever
playtime or trophy progress moves) and `psn_sync`.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from . import STATE_DIR
from .sheet import norm
from .steam import _env

AUTH = "https://ca.account.sony.com/api/authz/v3/oauth"
CLIENT_ID = "09515159-7237-4370-9b40-3806e67c0891"   # the PlayStation app's public client id
REDIRECT = "com.scee.psxandroid.scecompcall://redirect"
BASIC = "Basic MDk1MTUxNTktNzIzNy00MzcwLTliNDAtMzgwNmU2N2MwODkxOnVjUGprYTV0bnRCMktxc1A="
SCOPE = "psn:mobile.v2.core psn:clientapp"
GRAPHQL = "https://web.np.playstation.com/api/graphql/v1/op"
PURCHASED_HASH = "827a423f6a8ddca4107ac01395af2ec0eafd8396fc7fa204aaf9b7ed2eefa168"
GAMES = "https://m.np.playstation.com/api/gamelist/v2/users/me/titles"
TROPHIES = "https://m.np.playstation.com/api/trophy/v1/users/me/trophyTitles"
TOKEN_FILE = STATE_DIR / "psn_tokens.json"
NPSSO_HELP = ("sign in at playstation.com, open https://ca.account.sony.com/api/v1/ssocookie in the same "
              "browser and copy the npsso value into the PSN_NPSSO environment variable")

SCHEMA = """
CREATE TABLE IF NOT EXISTS psn_sync (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, purchased INTEGER, played INTEGER, trophies INTEGER, note TEXT
);
CREATE TABLE IF NOT EXISTS psn_game (
  kind TEXT NOT NULL,             -- purchased (id = entitlement) | played (id = title id)
  id TEXT NOT NULL, name TEXT NOT NULL, key TEXT NOT NULL, platform TEXT,
  membership TEXT,                -- purchased: NONE (bought) | PS_PLUS (claimed through PS Plus)
  service TEXT,                   -- played: none(purchased) = bought, other = disc or bundled, ps_plus
  is_active INTEGER, is_downloadable INTEGER, is_preorder INTEGER,
  product_id TEXT, concept_id TEXT, title_id TEXT,
  play_minutes INTEGER, play_count INTEGER, first_played TEXT, last_played TEXT, image_url TEXT,
  present INTEGER NOT NULL DEFAULT 1,   -- 0 once the last sync no longer lists it
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  PRIMARY KEY (kind, id)
);
CREATE INDEX IF NOT EXISTS psn_game_key ON psn_game(key);
CREATE TABLE IF NOT EXISTS psn_trophy (
  np_id TEXT PRIMARY KEY, name TEXT NOT NULL, key TEXT NOT NULL, platform TEXT, progress INTEGER,
  earned TEXT, defined TEXT,      -- JSON {bronze, silver, gold, platinum}
  earned_count INTEGER, defined_count INTEGER, last_updated TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS psn_history (
  sync_id INTEGER NOT NULL REFERENCES psn_sync(id), kind TEXT NOT NULL, id TEXT NOT NULL,
  play_minutes INTEGER, progress INTEGER
);
"""


class PsnAuthError(RuntimeError):
    pass


# ── auth ───────────────────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _code(npsso: str) -> str:
    q = urllib.parse.urlencode({"access_type": "offline", "client_id": CLIENT_ID, "redirect_uri": REDIRECT,
                                "response_type": "code", "scope": SCOPE})
    req = urllib.request.Request(f"{AUTH}/authorize?{q}", headers={"Cookie": f"npsso={npsso}"})
    try:
        resp = urllib.request.build_opener(_NoRedirect).open(req, timeout=30)
        loc = resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "") if e.code in (301, 302, 303, 307) else ""
    m = re.search(r"[?&]code=([^&]+)", loc)
    if not m:
        raise PsnAuthError(f"the NPSSO was refused (expired?): {NPSSO_HELP}")
    return urllib.parse.unquote(m.group(1))


def _token(form: dict) -> dict:
    req = urllib.request.Request(f"{AUTH}/token", data=urllib.parse.urlencode(form).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": BASIC})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise PsnAuthError(f"token request refused ({e.code})") from None
    now = time.time()
    return {"access": raw["access_token"], "access_until": now + raw.get("expires_in", 3600) - 60,
            "refresh": raw["refresh_token"], "refresh_until": now + raw.get("refresh_token_expires_in", 0) - 60}


def npsso(cfg: dict) -> str | None:
    return _env("PSN_NPSSO") or cfg.get("playstation", {}).get("npsso") or None


def access_token(cfg: dict) -> str:
    """A valid access token: cached, else refreshed, else from the NPSSO."""
    t = json.loads(TOKEN_FILE.read_text(encoding="utf-8")) if TOKEN_FILE.exists() else {}
    now = time.time()
    if t.get("access_until", 0) > now:
        return t["access"]
    t = None if not t or t.get("refresh_until", 0) <= now else t
    if t:
        try:
            t = _token({"refresh_token": t["refresh"], "grant_type": "refresh_token", "token_format": "jwt",
                        "scope": SCOPE})
        except PsnAuthError:
            t = None
    if not t:
        code = npsso(cfg)
        if not code:
            raise PsnAuthError(f"no NPSSO: {NPSSO_HELP}")
        t = _token({"code": _code(code), "redirect_uri": REDIRECT, "grant_type": "authorization_code",
                    "token_format": "jwt"})
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(t), encoding="utf-8")
    return t["access"]


# ── the three lists ────────────────────────────────────────────────────

def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def purchased(token: str, size: int = 100) -> list[dict]:
    out, start = [], 0
    while True:
        variables = {"isActive": True, "platform": ["ps4", "ps5"], "size": size, "start": start,
                     "sortBy": "ACTIVE_DATE", "sortDirection": "desc"}
        q = urllib.parse.urlencode({"operationName": "getPurchasedGameList", "variables": json.dumps(variables),
                                    "extensions": json.dumps({"persistedQuery": {"version": 1,
                                                                                 "sha256Hash": PURCHASED_HASH}})})
        resp = _get(f"{GRAPHQL}?{q}", token)
        games = ((resp.get("data") or {}).get("purchasedTitlesRetrieve") or {}).get("games")
        if games is None:
            raise RuntimeError(f"purchased games: unexpected answer {json.dumps(resp)[:200]}")
        out += games
        if len(games) < size:
            return out
        start += size


def _paged(url: str, key: str, token: str, limit: int) -> list[dict]:
    out, offset = [], 0
    while True:
        sep = "&" if "?" in url else "?"
        resp = _get(f"{url}{sep}limit={limit}&offset={offset}", token)
        page = resp.get(key) or []
        out += page
        nxt = resp.get("nextOffset")
        if not page or not nxt or nxt <= offset:
            return out
        offset = nxt


def fetch(cfg: dict) -> dict:
    token = access_token(cfg)
    return {"purchased": purchased(token),
            "played": _paged(f"{GAMES}?categories=ps4_game,ps5_native_game", "titles", token, 200),
            "trophies": _paged(TROPHIES, "trophyTitles", token, 800)}


# ── the database ───────────────────────────────────────────────────────

def minutes(duration: str | None) -> int | None:
    """ISO 8601 'PT12H34M56S' -> 754."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", duration or "")
    if not m:
        return None
    d, h, mi, s = (float(x or 0) for x in m.groups())
    return int(d * 1440 + h * 60 + mi + s / 60)


def save(db: sqlite3.Connection, raw: dict, at: str) -> str:
    prev = {(k, i): (p, None) for k, i, p in db.execute("SELECT kind, id, play_minutes FROM psn_game")}
    prev.update({("trophy", i): (None, p) for i, p in db.execute("SELECT np_id, progress FROM psn_trophy")})
    with db:
        sid = db.execute("INSERT INTO psn_sync (at, purchased, played, trophies) VALUES (?, ?, ?, ?)",
                         (at, len(raw["purchased"]), len(raw["played"]), len(raw["trophies"]))).lastrowid
        db.execute("UPDATE psn_game SET present = 0")
        rows = []
        for g in raw["purchased"]:
            rows.append({"kind": "purchased", "id": g["entitlementId"], "name": g.get("name") or g["entitlementId"],
                         "platform": g.get("platform"), "membership": g.get("membership"), "service": None,
                         "is_active": int(bool(g.get("isActive"))), "is_downloadable": int(bool(g.get("isDownloadable"))),
                         "is_preorder": int(bool(g.get("isPreOrder"))), "product_id": g.get("productId"),
                         "concept_id": str(g["conceptId"]) if g.get("conceptId") else None, "title_id": g.get("titleId"),
                         "play_minutes": None, "play_count": None, "first_played": None, "last_played": None,
                         "image_url": (g.get("image") or {}).get("url")})
        for g in raw["played"]:
            rows.append({"kind": "played", "id": g["titleId"], "name": g.get("name") or g["titleId"],
                         "platform": g.get("category"), "membership": None, "service": g.get("service"),
                         "is_active": None, "is_downloadable": None, "is_preorder": None, "product_id": None,
                         "concept_id": str((g.get("concept") or {}).get("id") or "") or None, "title_id": g["titleId"],
                         "play_minutes": minutes(g.get("playDuration")), "play_count": g.get("playCount"),
                         "first_played": g.get("firstPlayedDateTime"), "last_played": g.get("lastPlayedDateTime"),
                         "image_url": g.get("imageUrl")})
        moved = 0
        for r in rows:
            r.update(key=norm(r["name"]), at=at)
            db.execute("""
                INSERT INTO psn_game (kind, id, name, key, platform, membership, service, is_active, is_downloadable,
                  is_preorder, product_id, concept_id, title_id, play_minutes, play_count, first_played, last_played,
                  image_url, present, first_seen, last_seen)
                VALUES (:kind, :id, :name, :key, :platform, :membership, :service, :is_active, :is_downloadable,
                  :is_preorder, :product_id, :concept_id, :title_id, :play_minutes, :play_count, :first_played,
                  :last_played, :image_url, 1, :at, :at)
                ON CONFLICT(kind, id) DO UPDATE SET name = excluded.name, key = excluded.key,
                  platform = excluded.platform, membership = excluded.membership, service = excluded.service,
                  is_active = excluded.is_active, is_downloadable = excluded.is_downloadable,
                  is_preorder = excluded.is_preorder, product_id = excluded.product_id,
                  concept_id = excluded.concept_id, title_id = excluded.title_id,
                  play_minutes = excluded.play_minutes, play_count = excluded.play_count,
                  first_played = excluded.first_played, last_played = excluded.last_played,
                  image_url = excluded.image_url, present = 1, last_seen = excluded.last_seen""", r)
            if r["kind"] == "played":
                old = prev.get(("played", r["id"]))
                if old is None or old[0] != r["play_minutes"]:
                    db.execute("INSERT INTO psn_history VALUES (?, 'played', ?, ?, NULL)", (sid, r["id"], r["play_minutes"]))
                    moved += old is not None
        for t in raw["trophies"]:
            earned, defined = t.get("earnedTrophies") or {}, t.get("definedTrophies") or {}
            r = {"np_id": t["npCommunicationId"], "name": t.get("trophyTitleName") or t["npCommunicationId"],
                 "platform": t.get("trophyTitlePlatform"), "progress": t.get("progress"),
                 "earned": json.dumps(earned), "defined": json.dumps(defined),
                 "earned_count": sum(earned.values()), "defined_count": sum(defined.values()),
                 "last_updated": t.get("lastUpdatedDateTime"), "at": at}
            r["key"] = norm(r["name"])
            db.execute("""
                INSERT INTO psn_trophy VALUES (:np_id, :name, :key, :platform, :progress, :earned, :defined,
                  :earned_count, :defined_count, :last_updated, :at, :at)
                ON CONFLICT(np_id) DO UPDATE SET name = excluded.name, key = excluded.key, platform = excluded.platform,
                  progress = excluded.progress, earned = excluded.earned, defined = excluded.defined,
                  earned_count = excluded.earned_count, defined_count = excluded.defined_count,
                  last_updated = excluded.last_updated, last_seen = excluded.last_seen""", r)
            old = prev.get(("trophy", r["np_id"]))
            if old is None or old[1] != r["progress"]:
                db.execute("INSERT INTO psn_history VALUES (?, 'trophy', ?, NULL, ?)", (sid, r["np_id"], r["progress"]))
                moved += old is not None
        bought = sum(1 for g in raw["purchased"] if g.get("membership") == "NONE")
        note = (f"PSN synced: {bought} bought, {len(raw['purchased']) - bought} claimed through PS Plus, "
                f"{len(raw['played'])} played, {len(raw['trophies'])} trophy lists, {moved} moved since the last sync")
        db.execute("UPDATE psn_sync SET note = ? WHERE id = ?", (note, sid))
    return note


def sync(db: sqlite3.Connection, cfg: dict) -> str | None:
    """Fetch and save. None when PSN isn't set up; any failure keeps the last good library."""
    if not npsso(cfg) and not TOKEN_FILE.exists():
        return None
    try:
        raw = fetch(cfg)
    except PsnAuthError as e:
        return f"PSN sync failed: {e}; kept the previous one"
    except (urllib.error.URLError, RuntimeError, KeyError, ValueError) as e:
        return f"PSN sync failed ({e}); kept the previous one"
    return save(db, raw, datetime.now().isoformat(timespec="seconds"))


def load(db: sqlite3.Connection, cfg: dict) -> dict:
    """What you own on PlayStation, as {"synced_at", "games": {key: rec}, "claimed": [names]}.

    Owned: bought (membership NONE, not a pre-order), played as "none(purchased)" (bought), played
    as "other" (a disc or a bundled game: Demon's Souls on disc showed up this way, 2026-10-09), or
    a disc listed in config (an unplayed disc is invisible). Claimed through PS Plus is kept
    separately: it lasts while you subscribe.
    rec = {name, where, played_h, ach_done, ach_total}, the Steam shape, trophies as achievements.
    """
    last = db.execute("SELECT at FROM psn_sync ORDER BY id DESC LIMIT 1").fetchone()
    play = {}
    for key, mins in db.execute("SELECT key, SUM(play_minutes) FROM psn_game WHERE kind = 'played' AND present = 1"
                                " GROUP BY key"):
        play[key] = mins or 0
    troph = {k: (e, d) for k, e, d in db.execute("SELECT key, earned_count, defined_count FROM psn_trophy")}
    games: dict[str, dict] = {}

    def own(name, where):
        k = norm(name)
        e, d = troph.get(k, (None, None))
        games.setdefault(k, {"name": name, "where": where, "played_h": round(play.get(k, 0) / 60, 1),
                             "ach_done": e, "ach_total": d})

    # psn-api documents "none_purchased"; Sony actually sends "none(purchased)". Accept both.
    for (name,) in db.execute("SELECT name FROM psn_game WHERE present = 1 AND ((kind = 'purchased'"
                              " AND membership = 'NONE' AND is_preorder = 0) OR (kind = 'played'"
                              " AND service IN ('none(purchased)', 'none_purchased')))"):
        own(name, "PlayStation")
    for (name,) in db.execute("SELECT name FROM psn_game WHERE present = 1 AND kind = 'played' AND service = 'other'"):
        own(name, "PS disc")
    for name in cfg.get("playstation", {}).get("discs", []):
        own(name, "PS disc")
    claimed = [n for (n,) in db.execute("SELECT DISTINCT name FROM psn_game WHERE kind = 'purchased'"
                                        " AND membership = 'PS_PLUS' AND present = 1")]
    return {"synced_at": last[0] if last else None, "games": games, "claimed": claimed}
