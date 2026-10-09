"""Steam Web API: owned games, playtime and achievement progress.

Credentials come from the STEAM_API_KEY / STEAM_ID environment variables, else from
[steam] api_key / id in config.local.toml (gitignored). Never in tracked files or in
data.json. The profile's game details must be public or GetOwnedGames returns nothing.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from . import STATE_DIR
from .sheet import norm

STEAM_FILE = STATE_DIR / "steam.json"
API = "https://api.steampowered.com"


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


def sync(wanted: set[str], cfg: dict) -> tuple[dict, str]:
    """Refresh steam.json. Achievements are fetched only for `wanted` titles (normalized)."""
    key, raw_id = credentials(cfg)
    if not key or not raw_id:
        return load(), "Steam skipped: no Steam id / API key (see config.local.example.toml)"
    try:
        sid = _steam_id(key, raw_id)
        owned = _get("IPlayerService/GetOwnedGames/v1/", key=key, steamid=sid,
                     include_appinfo=1, include_played_free_games=1)["response"].get("games", [])
    except (urllib.error.URLError, RuntimeError, KeyError) as e:
        return load(), f"Steam sync failed ({e}); kept the previous one"
    if not owned:
        return load(), "Steam returned no games (is the profile's game details setting public?)"
    games = {}
    for g in owned:
        k = norm(g.get("name", ""))
        rec = {"name": g.get("name"), "appid": g["appid"],
               "played_h": round(g.get("playtime_forever", 0) / 60, 1), "ach_done": None, "ach_total": None}
        if k in wanted and g.get("playtime_forever", 0) > 0:
            try:
                ach = _get("ISteamUserStats/GetPlayerAchievements/v1/", key=key, steamid=sid,
                           appid=g["appid"])["playerstats"].get("achievements", [])
                if ach:
                    rec["ach_done"] = sum(a.get("achieved", 0) for a in ach)
                    rec["ach_total"] = len(ach)
            except urllib.error.HTTPError:
                pass  # games with no achievements answer 400
        games[k] = rec
    data = {"synced_at": datetime.now().isoformat(timespec="seconds"), "games": games}
    STEAM_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data, f"Steam synced: {len(games)} owned games"


def load() -> dict:
    if STEAM_FILE.exists():
        return json.loads(STEAM_FILE.read_text(encoding="utf-8"))
    return {"synced_at": None, "games": {}}
