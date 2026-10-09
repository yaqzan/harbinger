"""Steam Web API: owned games, playtime and achievements, imported into SQLite.

Credentials come from the STEAM_API_KEY / STEAM_ID environment variables, else from
[steam] api_key / id in config.local.toml (gitignored). Never in tracked files or in
data.json. The profile's game details must be public or GetOwnedGames returns nothing.

Tables: `steam_game` (every game ever seen in the library, with every field GetOwnedGames
gives), `steam_achievement` (per achievement, for the games we fetch them for),
`steam_history` (a row whenever a game's playtime or achievement count moves) and
`steam_sync` (one row per sync).
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Callable

from .sheet import norm

API = "https://api.steampowered.com"

SCHEMA = """
CREATE TABLE IF NOT EXISTS steam_sync (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, games INTEGER, achievements_fetched INTEGER, note TEXT
);
CREATE TABLE IF NOT EXISTS steam_game (
  appid INTEGER PRIMARY KEY, name TEXT NOT NULL, key TEXT NOT NULL,
  owned INTEGER NOT NULL DEFAULT 1,          -- 0 once it drops out of the library (refund, removed)
  playtime_min INTEGER, playtime_2weeks_min INTEGER, playtime_windows_min INTEGER,
  playtime_mac_min INTEGER, playtime_linux_min INTEGER, playtime_deck_min INTEGER,
  playtime_offline_min INTEGER, last_played TEXT, has_stats INTEGER, has_leaderboards INTEGER,
  icon_hash TEXT, content_descriptors TEXT,
  ach_done INTEGER, ach_total INTEGER, ach_checked_at TEXT,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS steam_game_key ON steam_game(key);
CREATE TABLE IF NOT EXISTS steam_achievement (
  appid INTEGER NOT NULL, apiname TEXT NOT NULL, achieved INTEGER NOT NULL, unlocked_at TEXT,
  PRIMARY KEY (appid, apiname)
);
CREATE TABLE IF NOT EXISTS steam_history (
  sync_id INTEGER NOT NULL REFERENCES steam_sync(id), appid INTEGER NOT NULL,
  playtime_min INTEGER, ach_done INTEGER
);
CREATE INDEX IF NOT EXISTS steam_history_app ON steam_history(appid);
"""


def _env(name: str) -> str | None:
    """Process env first, then the user's registry env (setx doesn't reach running shells)."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, name)[0] or None
    except (ImportError, OSError):
        return None


def _get(path: str, **params) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "harbinger/1"}), timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _steam_id(key: str, raw: str) -> str:
    if raw.isdigit() and len(raw) == 17:
        return raw
    vanity = raw.rstrip("/").split("/")[-1]
    resp = _get("ISteamUser/ResolveVanityURL/v1/", key=key, vanityurl=vanity)["response"]
    if resp.get("success") != 1:
        raise RuntimeError(f"couldn't resolve Steam vanity name '{vanity}'")
    return resp["steamid"]


def credentials(cfg: dict) -> tuple[str | None, str | None]:
    local = cfg.get("steam", {})
    return (_env("STEAM_API_KEY") or local.get("api_key") or None,
            _env("STEAM_ID") or str(local.get("id") or "") or None)


def fetch(cfg: dict, want: Callable[[str], bool]) -> dict:
    """{"owned": [GetOwnedGames entries], "achievements": {appid: [entries]}}.

    Achievements are fetched for played games whose name `want` accepts.
    """
    key, raw_id = credentials(cfg)
    sid = _steam_id(key, raw_id)
    owned = _get("IPlayerService/GetOwnedGames/v1/", key=key, steamid=sid, include_appinfo=1,
                 include_played_free_games=1)["response"].get("games", [])
    ach = {}
    for g in owned:
        if g.get("playtime_forever", 0) > 0 and want(g.get("name", "")):
            try:
                ach[g["appid"]] = _get("ISteamUserStats/GetPlayerAchievements/v1/", key=key, steamid=sid,
                                       appid=g["appid"])["playerstats"].get("achievements", [])
            except urllib.error.HTTPError:
                pass  # games with no achievements answer 400
    return {"owned": owned, "achievements": ach}


def _ts(epoch) -> str | None:
    return datetime.fromtimestamp(epoch).isoformat(timespec="seconds") if epoch else None


def save(db: sqlite3.Connection, raw: dict, at: str) -> str:
    """Upsert the library, per-achievement rows and history, in one transaction."""
    prev = {a: (p, d) for a, p, d in db.execute("SELECT appid, playtime_min, ach_done FROM steam_game")}
    ach = raw["achievements"]
    with db:
        sync_id = db.execute("INSERT INTO steam_sync (at, games, achievements_fetched) VALUES (?, ?, ?)",
                             (at, len(raw["owned"]), len(ach))).lastrowid
        db.execute("UPDATE steam_game SET owned = 0")
        moved = 0
        for g in raw["owned"]:
            appid = g["appid"]
            done = total = None
            if appid in ach:
                done, total = sum(1 for a in ach[appid] if a.get("achieved")), len(ach[appid])
                db.executemany(
                    "INSERT OR REPLACE INTO steam_achievement VALUES (?, ?, ?, ?)",
                    [(appid, a["apiname"], int(a.get("achieved", 0)), _ts(a.get("unlocktime"))) for a in ach[appid]])
            row = {
                "appid": appid, "name": g.get("name") or str(appid), "key": norm(g.get("name") or ""),
                "playtime_min": g.get("playtime_forever", 0), "playtime_2weeks_min": g.get("playtime_2weeks"),
                "playtime_windows_min": g.get("playtime_windows_forever"),
                "playtime_mac_min": g.get("playtime_mac_forever"),
                "playtime_linux_min": g.get("playtime_linux_forever"),
                "playtime_deck_min": g.get("playtime_deck_forever"),
                "playtime_offline_min": g.get("playtime_disconnected"),
                "last_played": _ts(g.get("rtime_last_played")),
                "has_stats": int(bool(g.get("has_community_visible_stats"))),
                "has_leaderboards": int(bool(g.get("has_leaderboards"))),
                "icon_hash": g.get("img_icon_url"),
                "content_descriptors": json.dumps(g["content_descriptorids"]) if g.get("content_descriptorids") else None,
                "at": at,
            }
            db.execute("""
                INSERT INTO steam_game (appid, name, key, owned, playtime_min, playtime_2weeks_min,
                  playtime_windows_min, playtime_mac_min, playtime_linux_min, playtime_deck_min,
                  playtime_offline_min, last_played, has_stats, has_leaderboards, icon_hash,
                  content_descriptors, first_seen, last_seen)
                VALUES (:appid, :name, :key, 1, :playtime_min, :playtime_2weeks_min, :playtime_windows_min,
                  :playtime_mac_min, :playtime_linux_min, :playtime_deck_min, :playtime_offline_min,
                  :last_played, :has_stats, :has_leaderboards, :icon_hash, :content_descriptors, :at, :at)
                ON CONFLICT(appid) DO UPDATE SET name = excluded.name, key = excluded.key, owned = 1,
                  playtime_min = excluded.playtime_min, playtime_2weeks_min = excluded.playtime_2weeks_min,
                  playtime_windows_min = excluded.playtime_windows_min, playtime_mac_min = excluded.playtime_mac_min,
                  playtime_linux_min = excluded.playtime_linux_min, playtime_deck_min = excluded.playtime_deck_min,
                  playtime_offline_min = excluded.playtime_offline_min, last_played = excluded.last_played,
                  has_stats = excluded.has_stats, has_leaderboards = excluded.has_leaderboards,
                  icon_hash = excluded.icon_hash, content_descriptors = excluded.content_descriptors,
                  last_seen = excluded.last_seen""", row)
            if appid in ach:
                # Achievement counts are kept from the last time we fetched them, never blanked.
                db.execute("UPDATE steam_game SET ach_done = ?, ach_total = ?, ach_checked_at = ? WHERE appid = ?",
                           (done, total, at, appid))
            old = prev.get(appid)
            new_done = done if appid in ach else (old[1] if old else None)
            if old is None or old[0] != row["playtime_min"] or old[1] != new_done:
                db.execute("INSERT INTO steam_history VALUES (?, ?, ?, ?)",
                           (sync_id, appid, row["playtime_min"], new_done))
                moved += old is not None
        gone = db.execute("SELECT COUNT(*) FROM steam_game WHERE owned = 0").fetchone()[0]
        note = f"Steam synced: {len(raw['owned'])} owned games, {moved} moved since the last sync"
        if ach:
            note += f", achievements for {len(ach)}"
        if gone:
            note += f", {gone} no longer in the library"
        db.execute("UPDATE steam_sync SET note = ? WHERE id = ?", (note, sync_id))
    return note


def sync(db: sqlite3.Connection, cfg: dict, want: Callable[[str], bool]) -> str:
    """Fetch and save. Any failure keeps what the database already has."""
    key, raw_id = credentials(cfg)
    if not key or not raw_id:
        return "Steam skipped: no Steam id / API key (see config.local.example.toml)"
    try:
        raw = fetch(cfg, want)
    except (urllib.error.URLError, RuntimeError, KeyError, ValueError) as e:
        return f"Steam sync failed ({e}); kept the previous one"
    if not raw["owned"]:
        return "Steam returned no games (is the profile's game details setting public?)"
    return save(db, raw, datetime.now().isoformat(timespec="seconds"))


def load(db: sqlite3.Connection) -> dict:
    """{"synced_at", "games": {norm(name): {name, appid, played_h, ach_done, ach_total}}} of owned games."""
    last = db.execute("SELECT at FROM steam_sync ORDER BY id DESC LIMIT 1").fetchone()
    games = {}
    for appid, name, key, mins, done, total in db.execute(
            "SELECT appid, name, key, playtime_min, ach_done, ach_total FROM steam_game WHERE owned = 1"
            " ORDER BY playtime_min"):  # two apps with one name: the more played one wins
        games[key] = {"name": name, "appid": appid, "played_h": round((mins or 0) / 60, 1),
                      "ach_done": done, "ach_total": total}
    return {"synced_at": last[0] if last else None, "games": games}
