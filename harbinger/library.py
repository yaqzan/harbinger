"""The library page's list: every game on Game Pass (console) or your PS Plus tier, plus the games
you own on Steam or PlayStation, merged into one row per game.

A row says which of four places has it (`gp`, `ps`, `steam`, `psn`) so the page can filter by
overlap: Game Pass only, PS Plus only, Steam only, on both services, and so on. Scores: the sheets'
Metacritic and PlayStation user score, and Steam user reviews (`ratings.py`, attached after).
Pure: libraries in, rows out; no network, no database.
"""

from __future__ import annotations

from .sheet import norm

OWNED_ON_PSN = ("PlayStation", "PS disc")  # a PS Plus claim is membership, not ownership


def _year(release: str) -> int | None:
    s = str(release or "")[:4]
    return int(s) if s.isdigit() and 1970 <= int(s) <= 2100 else None


def _leave(row: dict) -> list | None:
    if not row.get("wave"):
        return None
    return [row["wave"], row["band"], row["p"]]


def rows(cx, side, steam: dict, psn: dict | None, one: dict) -> list[dict]:
    """One dict per game: {game, key, gp, ps, steam, psn, mc, us, hours, genre, year, played,
    gp_leaves, ps_leaves, appid}. Sorted by name; the page sorts and filters."""
    pm = side.pm
    out: dict[str, dict] = {}

    def blank(key: str, name: str) -> dict:
        return {"game": name, "key": key, "gp": 0, "ps": "", "steam": 0, "psn": 0}

    # Game Pass on the console, now
    for k, g in cx.by_key.items():
        if g.status not in ("Active", "Leaving Soon"):
            continue
        r = out.setdefault(k, blank(k, g.name))
        r.update(gp=1, mc=g.metacritic, hours=g.hours, genre=g.genre, year=_year(g.release))
    # the same game on PS Plus joins the Game Pass row; the rest get their own
    ps_to_row: dict[str, str] = {}
    if pm:
        for k in [k for k, r in out.items() if r["gp"]]:
            pk = pm.key(out[k]["game"], loose=False)
            if pk:
                ps_to_row[pk] = k
    for g in side.games:
        k = ps_to_row.get(g.key, g.key)
        r = out.setdefault(k, blank(k, g.name))
        r["ps"] = g.tier or "PS Plus"
        for f, v in (("mc", g.metacritic), ("hours", g.hours), ("genre", g.genre), ("year", _year(g.release))):
            if r.get(f) in (None, "") and v not in (None, ""):
                r[f] = v
        if g.user_score is not None:
            r["us"] = g.user_score

    def place(name: str) -> str:
        """The row a library title belongs to (a new one when no catalogue has it)."""
        xk = cx.match.key(name, loose=False)
        if xk in out:
            return xk
        pk = pm.key(name, loose=False) if pm else None
        if pk and ps_to_row.get(pk, pk) in out:
            return ps_to_row.get(pk, pk)
        return xk or norm(name)

    def own(name: str, flag: str, played: float | None, appid: int | None = None) -> None:
        k = place(name)
        r = out.get(k)
        if r is None:
            r = out[k] = blank(k, name)
            old = cx.by_key.get(k)  # a game that left Game Pass still has its sheet facts
            if old:
                r.update(mc=old.metacritic, hours=old.hours, genre=old.genre, year=_year(old.release))
        if flag == "ps":
            r["ps"] = r["ps"] or "Claimed"
        else:
            r[flag] = 1
        if played:
            r["played"] = max(r.get("played", 0), played)
        if appid:
            r["appid"] = appid

    for rec in (steam.get("games") or {}).values():
        own(rec["name"], "steam", rec.get("played_h"), rec.get("appid"))
    for rec in ((psn or {}).get("games") or {}).values():
        own(rec["name"], "psn" if rec.get("where") in OWNED_ON_PSN else "ps", rec.get("played_h"))

    # when a game leaves, per service
    for src in (one.get("rows", []), one.get("backups", [])):
        for x in src:
            on_ps = x["service"].startswith("PS")
            k = ps_to_row.get(x["key"], x["key"]) if on_ps else x["key"]
            r = out.get(k)
            lv = _leave(x)
            if r and lv:
                r["ps_leaves" if on_ps else "gp_leaves"] = lv
    for r in out.values():
        for f in ("mc", "us", "hours", "genre", "year", "played"):
            if not r.get(f):
                r.pop(f, None)
    return sorted(out.values(), key=lambda r: r["game"].lower())
