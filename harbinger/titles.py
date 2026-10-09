"""Reconcile titles across sources: which sheet game a Steam app, forecast entry or queue name is.

Every run matches each source title to a sheet key (`sheet.Index` plus the owner's
corrections in harbinger/titles.toml) and records the result in `title_match`, once per
target catalogue: `xbox` (the Game Pass sheet) and, with a PS Plus tier set, `playstation`
(the PS Plus games your tier includes; sources Steam and the Game Pass games). Weak matches
and near misses are the issues `py -3.11 -m harbinger titles` lists; fix one by adding a line
to titles.toml, and every later build uses it.
"""

from __future__ import annotations

import difflib
import json
import re
import sqlite3
from datetime import datetime

from .sheet import Index, Sheet, norm, sequel_gap

SCHEMA = """
CREATE TABLE IF NOT EXISTS title_match (
  target TEXT NOT NULL,          -- the catalogue matched against: xbox | playstation
  source TEXT NOT NULL,          -- steam | psn | disc | forecast | confirmed | queue | manual | xbox
  source_id TEXT NOT NULL,       -- Steam appid, else the title itself
  title TEXT NOT NULL,           -- as that source spells it
  key TEXT,                      -- the sheet key it resolved to, NULL if none
  sheet_title TEXT,              -- "A + B" for a bundle
  method TEXT NOT NULL,          -- exact | compact | year | edition | prefix | fuzzy | alias | different
                                 -- | not a game | pc only | alias to a missing title | none
  candidates TEXT,               -- JSON [[sheet title, similarity]] for a near miss
  checked_at TEXT NOT NULL,
  PRIMARY KEY (target, source, source_id)
);
"""

WEAK = ("prefix", "fuzzy")     # matched on a loose rung: worth a look
NEAR = 0.85                    # similarity that makes an unmatched title a near miss
STRICT = {"steam", "xbox", "psn", "disc"}  # libraries and catalogues: no prefix or fuzzy matches
# Steam apps that are tools, not games: never matched, never suggested
NOT_A_GAME = re.compile(r"\b(public test|test server|beta client|dedicated server|playtest|demo|soundtrack|sdk)\b", re.I)


class Matcher:
    """Sheet keys plus the corrections in titles.toml.

    [same] maps a title to one sheet title, or to a list for a bundle ("Heroes of Might and
    Magic 2 & 3"). [different] lists sheet titles a title must never match.
    """

    def __init__(self, keys, titles_cfg: dict | None = None, out_of_scope=(), report_missing: bool = True,
                 elsewhere=()):
        # Out-of-scope keys (PC-only games) are matched so they can be turned away, never
        # mistaken for a console game with a similar name.
        self.skip = set(out_of_scope)
        self.index = Index(set(keys) | self.skip)
        self.keys = self.index.keys - self.skip
        t = titles_cfg or {}
        listed = lambda v: [v] if isinstance(v, str) else list(v)
        self.same = {norm(a): [norm(x) for x in listed(v)] for a, v in t.get("same", {}).items()}
        self.different = {norm(a): {norm(x) for x in listed(v)} for a, v in t.get("different", {}).items()}
        # An alias names a title in one catalogue; matched against another catalogue it falls
        # through to the normal rungs, and only the catalogue it was written for reports it missing.
        self.report_missing = report_missing
        self.elsewhere = set(elsewhere)  # keys of the other catalogue: an alias aimed there isn't missing

    def match_all(self, name: str, loose: bool = True) -> tuple[list[str], str]:
        k = norm(name)
        if k in self.same:
            hits = [x for x in self.same[k] if x in self.keys]
            if hits:
                return hits, "alias"
            if any(x in self.skip for x in self.same[k]):
                return [], "pc only"
        key, how = self.index.lookup(name, loose)
        if key is None and k in self.same and self.report_missing and not (set(self.same[k]) & self.elsewhere):
            return [], "alias to a missing title"
        if key and key in self.different.get(k, ()):
            return [], "different"
        if key in self.skip:
            return [], "pc only"
        return ([key] if key else []), how

    def match(self, name: str, loose: bool = True) -> tuple[str | None, str]:
        hits, how = self.match_all(name, loose)
        return (hits[0] if hits else None), how

    def key(self, name: str, loose: bool = True) -> str | None:
        return self.match(name, loose)[0]

    def near(self, name: str, n: int = 3) -> list[tuple[str, float]]:
        """Sheet keys close to an unmatched title: similar spelling, or one title extends the
        other ("Atlas Fallen" / "Atlas Fallen: Reign of Sand"). Sequel numbers don't count."""
        k = norm(name)
        if not k:
            return []
        skip = self.different.get(k, set())
        ratio = lambda c: round(difflib.SequenceMatcher(None, k, c).ratio(), 2)
        out = {c: ratio(c) for c in difflib.get_close_matches(k, self.keys, n=n + 3, cutoff=NEAR)}
        for c in self.keys:
            longer, shorter = (c, k) if len(c) > len(k) else (k, c)
            if (c not in out and len(shorter.split()) >= 2 and longer.startswith(shorter + " ")
                    and not longer[len(shorter) + 1:].split()[0].isdigit()):
                out[c] = ratio(c)
        keep = [(c, r) for c, r in out.items() if c not in skip and not sequel_gap(c, k)]
        return sorted(keep, key=lambda t: -t[1])[:n]


def sources(sheet: Sheet, steam_rows, forecast: dict, cfg: dict) -> list[tuple[str, str, str]]:
    """(source, source_id, title) for every title Harbinger reads from outside the sheet."""
    out = [("steam", str(appid), name) for appid, name in steam_rows]
    out += [("forecast", i["game"], i["game"]) for i in forecast.get("listed", [])]
    out += [("confirmed", c["game"], c["game"]) for c in forecast.get("confirmed", [])]
    q = cfg.get("queue", {})
    out += [("queue", n, n) for n in q.get("tracking", []) + q.get("gone", [])]
    out += [("manual", m["game"], m["game"]) for m in cfg.get("manual_confirmed", [])]
    return list({(s, i): (s, i, t) for s, i, t in out}.values())


def migrate(db: sqlite3.Connection) -> None:
    """title_match is rebuilt every run: an old layout (no target column) is simply dropped."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(title_match)")}
    if cols and "target" not in cols:
        db.execute("DROP TABLE title_match")


def _match_rows(target: str, m: Matcher, names: dict, items, now: str) -> list[tuple]:
    rows = []
    for src, sid, title in items:
        if src in STRICT and NOT_A_GAME.search(title):
            rows.append((target, src, sid, title, None, None, "not a game", None, now))
            continue
        hits, how = m.match_all(title, loose=src not in STRICT)
        key = hits[0] if hits else None
        cands = None
        if key is None and how not in ("different", "alias to a missing title", "pc only"):
            near = m.near(title)
            cands = json.dumps([[names.get(c, c), r] for c, r in near]) if near else None
        rows.append((target, src, sid, title, key, " + ".join(names.get(h, h) for h in hits) or None, how, cands, now))
    return rows


def ps_matcher(ps_games, cfg: dict) -> Matcher:
    """PS Plus games your tier includes. Game Pass aliases fall through instead of reporting."""
    return Matcher((g.key for g in ps_games), cfg.get("titles"), report_missing=False)


def reconcile(db: sqlite3.Connection, sheet: Sheet, forecast: dict, cfg: dict, ps_games=()) -> str:
    """Rebuild title_match from the current sheets, Steam library, forecast and config."""
    ps_all = {k for (k,) in db.execute("SELECT DISTINCT key FROM sheet_row WHERE service = 'playstation'")}
    m = Matcher((g.key for g in sheet.games), cfg.get("titles"), sheet.out_of_scope, elsewhere=ps_all)
    names = {}
    for g in sheet.games:
        names.setdefault(g.key, g.name)
    steam_rows = db.execute("SELECT appid, name FROM steam_game WHERE owned = 1").fetchall()
    # PlayStation games you own: bought (one row per name) and discs from config
    owned_ps = [("psn", n, n) for (n,) in db.execute(
        "SELECT DISTINCT name FROM psn_game WHERE present = 1 AND ((kind = 'purchased' AND membership = 'NONE')"
        " OR (kind = 'played' AND service IN ('none(purchased)', 'none_purchased', 'other')))")]
    owned_ps += [("disc", n, n) for n in cfg.get("playstation", {}).get("discs", [])]
    now = datetime.now().isoformat(timespec="seconds")
    rows = _match_rows("xbox", m, names, sources(sheet, steam_rows, forecast, cfg) + owned_ps, now)
    if ps_games:
        pm = ps_matcher(ps_games, cfg)
        ps_names = {g.key: g.name for g in ps_games}
        xbox_now = {g.key: g.name for g in sheet.games if g.status in ("Active", "Leaving Soon")}
        items = ([("steam", str(a), n) for a, n in steam_rows] + owned_ps
                 + [("xbox", k, n) for k, n in xbox_now.items()])
        rows += _match_rows("playstation", pm, ps_names, items, now)
    with db:
        db.execute("DELETE FROM title_match")
        db.executemany("INSERT INTO title_match VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    on = sum(1 for r in rows if r[0] == "xbox" and r[1] == "steam" and r[4])
    note = f"titles: {on} Steam games are on Game Pass"
    if ps_games:
        on_ps = sum(1 for r in rows if r[0] == "playstation" and r[1] == "steam" and r[4])
        both = sum(1 for r in rows if r[0] == "playstation" and r[1] == "xbox" and r[4])
        note += f", {on_ps} on your PS Plus tier, {both} games on both services"
    r = report(db)
    return note + f", {len(r['check']) + len(r['near']) + len(r['unmatched'])} to check"


def report(db: sqlite3.Connection) -> dict:
    """The issues: weak matches, near misses, and outside titles that should be on the sheet."""
    q = lambda where: [dict(zip(("target", "source", "title", "sheet_title", "method", "candidates"), r))
                       for r in db.execute(f"SELECT target, source, title, sheet_title, method, candidates FROM title_match"
                                           f" WHERE {where} ORDER BY target, source, title")]
    return {
        "check": q("method IN (" + ", ".join(f"'{w}'" for w in WEAK) + ")"),
        "near": q("key IS NULL AND candidates IS NOT NULL"),
        # manual_confirmed entries are off the sheet by definition; most Game Pass games
        # are simply not on PS Plus
        "unmatched": q("key IS NULL AND candidates IS NULL AND method NOT IN ('different', 'not a game', 'pc only')"
                       " AND (source NOT IN ('steam', 'psn', 'disc', 'manual', 'xbox') OR method = 'alias to a missing title')"),
        "counts": {f"{s}->{t}": (n, k) for t, s, n, k in db.execute(
            "SELECT target, source, COUNT(*), COUNT(key) FROM title_match GROUP BY target, source")},
        "methods": dict(db.execute("SELECT method, COUNT(*) FROM title_match WHERE key IS NOT NULL GROUP BY method")),
    }


def print_report(db: sqlite3.Connection) -> None:
    r = report(db)
    print("Matched to the sheet: " + ", ".join(f"{s} {k}/{n}" for s, (n, k) in sorted(r["counts"].items())))
    print("By rung: " + ", ".join(f"{m} {n}" for m, n in sorted(r["methods"].items(), key=lambda t: -t[1])))
    if r["check"]:
        print(f"\nCheck these matches ({len(r['check'])}, loose rungs):")
        for i in r["check"]:
            print(f"  {i['source']:<9} {i['title']!r} -> {i['target']} {i['sheet_title']!r} ({i['method']})")
    if r["near"]:
        print(f"\nNear misses ({len(r['near'])}, no match but close to a sheet title):")
        for i in r["near"]:
            c = "; ".join(f"{t!r} {s:.2f}" for t, s in json.loads(i["candidates"]))
            print(f"  {i['source']:<9} {i['title']!r} ~ {i['target']} {c}")
    if r["unmatched"]:
        print(f"\nNot on the sheet ({len(r['unmatched'])}):")
        for i in r["unmatched"]:
            extra = f" ({i['method']})" if i["method"] != "none" else ""
            print(f"  {i['source']:<9} {i['title']!r} ({i['target']}){extra}")
    if r["check"] or r["near"] or r["unmatched"]:
        print("\nFix one in harbinger/titles.toml ([same] or [different]), then run `py -3.11 -m harbinger build`.")
