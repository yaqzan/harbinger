"""u/ABattleVet's Game Pass and PS Plus master lists: download each workbook, import into SQLite.

Each ingest downloads each public sheet as one xlsx (no Google login, no gids), reads the tabs
in SERVICES[service] with the stdlib, checks every mapped column still has the header we expect, and
replaces the `sheet_row` table in one transaction. Differences from the previous import go to
`sheet_change`, so the database remembers when a game flipped to Leaving Soon or its
Completion changed. Build reads `sheet_row`; it never touches the workbook.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import sqlite3
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from io import BytesIO

from . import STATE_DIR

XLSX_URL = "https://docs.google.com/spreadsheets/d/{id}/export?format=xlsx"
SHEET_DIR = STATE_DIR / "sheet"
# The last workbook imported per service is kept as state/sheet/<service>.xlsx, for debugging.


_FOLD = str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ß": "ss", "ł": "l",
                       "Ł": "L", "đ": "d", "Đ": "D", "þ": "th", "Þ": "Th", "™": "", "®": "", "©": "",
                       "’": "'", "‘": "'"})
_ROMAN = {r: str(n) for n, r in enumerate(
    "i ii iii iv v vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix xx".split(), 1)}


def norm(name: str) -> str:
    """Match key for titles across the sheet, its tabs, Steam and the forecast.

    Drops ™/®, folds accents and ø/æ, and writes roman numerals as digits ("Chivalry II" and
    Steam's "Chivalry 2" share a key).
    """
    s = unicodedata.normalize("NFKD", name.translate(_FOLD)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\((game preview|early access|pc|xbox series x\|s)\)", " ", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(_ROMAN.get(w, w) for w in s.split())


EDITION = re.compile(r" (game of the year|goty|definitive|deluxe|digital deluxe|complete|enhanced|ultimate"
                     r"|standard|premium|special|gold|anniversary|remastered|directors cut|director s cut)( edition)?$")
_YEAR = re.compile(r" (19|20)\d\d$")


def strip_edition(key: str) -> str:
    return EDITION.sub("", _YEAR.sub("", key))


def sequel_gap(a: str, b: str) -> bool:
    """True when two keys differ only by numbers: "sniper elite 3" vs "sniper elite 4", "portal" vs
    "portal 2". Those are different games, never a match or a near miss."""
    diff = set(a.split()) ^ set(b.split())
    return bool(diff) and all(w.isdigit() for w in diff)


class Index:
    """Sheet keys indexed for resolve(): build once, look up many titles."""

    def __init__(self, keys):
        self.keys = set(keys)
        self.compact, self.year, self.base = {}, {}, {}
        for k in self.keys:
            self.compact.setdefault(k.replace(" ", ""), []).append(k)
            self.year.setdefault(_YEAR.sub("", k), []).append(k)
            self.base.setdefault(strip_edition(k), []).append(k)

    def lookup(self, name: str, loose: bool = True) -> tuple[str | None, str]:
        """(sheet key, rung): exact, compact, year, edition; with loose, also prefix and fuzzy."""
        key = norm(name)
        if not key:
            return None, "none"
        if key in self.keys:
            return key, "exact"
        for rung, table, probe in (("compact", self.compact, key.replace(" ", "")),
                                   ("year", self.year, _YEAR.sub("", key)),
                                   ("edition", self.base, strip_edition(key))):
            hits = table.get(probe, [])
            if len(hits) == 1:
                return hits[0], rung
        if not loose:
            return None, "none"
        pref = [k for k in self.keys if k.startswith(key + " ") and not k[len(key) + 1:].split()[0].isdigit()]
        if len(pref) == 1:
            return pref[0], "prefix"
        close = [k for k in difflib.get_close_matches(key, self.keys, n=2, cutoff=FUZZY) if not sequel_gap(k, key)]
        if close and (len(close) == 1 or difflib.SequenceMatcher(None, key, close[1]).ratio() < FUZZY):
            return close[0], "fuzzy"
        return None, "none"


FUZZY = 0.93  # a typo ("MechWarriror"), not a different game


def resolve(name: str, keys) -> str | None:
    """The sheet key another source's title refers to, or None.

    Exact match first, then the same letters without spaces ("CloverPit"), then with a
    trailing year dropped ("Keeper (2025)"), then the same game minus an edition suffix
    ("Hades Definitive Edition"), then a unique word-prefix that isn't a sequel number ("Sopa"
    for "Sopa: Tale of the Stolen Potato"), then a near-identical spelling (a typo). Ambiguous
    rungs resolve to nothing.
    """
    return Index(keys).lookup(name)[0]


# ── tabs and their columns ─────────────────────────────────────────────
# (column letter, field, text the header cell must contain). A header that no longer matches
# fails the import, which keeps the previous one: the sheet's owner moved a column.

_BASE = [("A", "title", "Game"), ("B", "system", "System"), ("C", "xcloud", "xCloud"), ("D", "status", "Status"),
         ("E", "added", "Added"), ("F", "removed", "Removed"), ("G", "months", "Months"),
         ("H", "release", "Release"), ("I", "age_years", "Age"), ("J", "metacritic", "Metacritic"),
         ("K", "completion_h", "Completion"), ("L", "genre", "Genre")]
_RATED = [("M", "series_xs", "Series X|S"), ("N", "owner_notes", "Owner Notes"), ("O", "esrb", "ESRB"),
          ("P", "esrb_descriptors", "ESRB Content Descriptors")]


@dataclass(frozen=True)
class Tab:
    sheet: str              # tab name in the workbook
    header_row: int
    columns: list
    groups: dict = field(default_factory=dict)  # row-1 labels that tell repeated headers apart


TABS = {
    "master": Tab("Master List", 2, _BASE + _RATED + [
        ("Q", "community_notes", "Community Notes"),
        ("R", "premium_status", "Status"), ("S", "premium_added", "Added"), ("T", "premium_delay", "Delay"),
        ("U", "essential_added", "Added"), ("V", "essential_delay", "Delay")],
        groups={"R": "GP Premium", "U": "GP Essential"}),
    "leaving_soon": Tab("Leaving Soon", 2, _BASE),
    "removed": Tab("Removed", 2, _BASE),
    "likely_leaving": Tab("Likely Leaving", 2, _BASE + _RATED + [("Q", "public_notes", "Public Notes")]),
    "returning": Tab("Returning Titles", 2, _BASE + _RATED[:2]),
    "retro": Tab("Retro Classics", 2, _BASE + _RATED + [("Q", "public_notes", "Public Notes")]),
    "premium": Tab("Game Pass Premium", 2, _BASE + _RATED + [
        ("Q", "community_notes", "Community Notes"),
        ("R", "premium_status", "Status"), ("S", "premium_added", "Added"), ("T", "premium_delay", "Delay")]),
    "essential": Tab("Game Pass Essential", 2, _BASE + _RATED + [
        ("Q", "public_notes", "Public Notes"),
        ("R", "essential_added", "Essential Join Date"), ("S", "essential_months", "Months")]),
    "first_party": Tab("Xbox Game Studios", 1, [("A", "title", "Published or Developed"), ("B", "studio", "Studio"),
                                                ("C", "added", "Added")]),
    "ea_play": Tab("EA Play", 1, [("A", "title", "Games"), ("B", "system", "Platform"), ("C", "added", "Added"),
                                  ("D", "status", "Status")]),
    "upcoming": Tab("Upcoming", 2, [("A", "title", "Game"), ("B", "added", "GP Date")]),
}
# Not imported: Tiers, PC, xCloud, Series X|S and Xbox are filtered views of the Master List;
# Copy of Removed duplicates Removed; Suggestions holds reader names; Cross Play has no use yet.

# The PS Plus list ("Complete NA Playstation Plus Master List", same author). Its Tier column
# (Essential / Extra / Premium (...)) replaces Game Pass's per-tier tabs.
_PS = [("A", "title", "Game"), ("B", "system", "System"), ("C", "tier", "Tier"), ("D", "status", "Status"),
       ("E", "added", "Added"), ("F", "removed", "Removed"), ("G", "months", "Months"),
       ("H", "release", "Release"), ("I", "age_years", "Age"), ("J", "metacritic", "Metacritic"),
       ("K", "user_score", "User"), ("L", "completion_h", "Completion"), ("M", "genre", "Genre"),
       ("N", "owner_notes", "Notes"), ("O", "streaming", "Streaming"), ("P", "local_multiplayer", "Local Multiplayer")]
PS_TABS = {
    "master": Tab("Master List", 2, _PS),
    "leaving_soon": Tab("Leaving Soon", 2, _PS),
    "removed": Tab("Removed", 2, _PS),
    "likely_leaving": Tab("Likely Leaving", 2, _PS),
}
# Not imported: Monthly, Extra, Premium, Classics, Remasters, VR, PS5/PS4 Download, PS3,
# Cloud/PC Streaming and Vita Monthly are filtered views of the Master List; Suggestions holds
# reader names.

SERVICES = {"xbox": TABS, "playstation": PS_TABS}

FIELDS = ["system", "xcloud", "status", "added", "removed", "months", "release", "age_years", "metacritic",
          "completion_h", "genre", "series_xs", "owner_notes", "esrb", "esrb_descriptors", "community_notes",
          "public_notes", "premium_status", "premium_added", "premium_delay", "essential_added",
          "essential_delay", "essential_months", "studio", "tier", "user_score", "streaming",
          "local_multiplayer"]
DATES = {"added", "removed", "release", "premium_added", "essential_added"}
NUMBERS = {"months", "age_years", "metacritic", "completion_h", "premium_delay", "essential_delay", "essential_months",
           "user_score"}
VOLATILE = {"months", "essential_months"}  # live formulas off TODAY(): not logged as changes


# ── reading the workbook ───────────────────────────────────────────────

_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_EXCEL_EPOCH = date(1899, 12, 30)


def read_xlsx(data: bytes, wanted: set[str]) -> dict[str, dict[int, dict[str, object]]]:
    """{tab name: {row number: {column letter: value}}} for the wanted tabs.

    Values are str, float or bool as cached in the file; error cells (#N/A) are dropped.
    """
    z = zipfile.ZipFile(BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{_M}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{_M}t")))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(f"{_M}sheet"):
        name = sh.get("name")
        if name not in wanted:
            continue
        target = rels[sh.get(_R)].lstrip("/")
        path = target if target.startswith("xl/") else f"xl/{target}"
        rows: dict[int, dict[str, object]] = {}
        for c in ET.fromstring(z.read(path)).iter(f"{_M}c"):
            t, v = c.get("t"), c.find(f"{_M}v")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{_M}t"))
            elif v is None or v.text is None or t == "e":
                continue
            elif t == "s":
                val = shared[int(v.text)]
            elif t == "str":
                val = v.text
            elif t == "b":
                val = v.text == "1"
            else:
                val = float(v.text)
            m = re.match(r"([A-Z]+)(\d+)$", c.get("r"))
            rows.setdefault(int(m.group(2)), {})[m.group(1)] = val
        out[name] = rows
    return out


def _date(v) -> str | None:
    """Sheet date cell -> 'YYYY-MM-DD', 'YYYY-MM' for month-only text, else the raw text."""
    if v is None or v == "":
        return None
    if isinstance(v, float):
        return (_EXCEL_EPOCH + timedelta(days=int(v))).isoformat()
    s = str(v).strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    for fmt in ("%B %Y", "%b %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m")
        except ValueError:
            pass
    return s


def _cell(fld: str, v):
    if fld in DATES:
        return _date(v)
    if isinstance(v, str):
        v = v.strip()
        if fld in NUMBERS and v:
            try:
                return float(v)
            except ValueError:
                return v  # keep odd text ("TBD") rather than lose it
        return v or None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float) and fld not in NUMBERS and v.is_integer():
        return str(int(v))
    return v


class SheetLayoutError(RuntimeError):
    """A tab is missing or a header moved."""


def extract(book: dict, tabs: dict[str, Tab] = TABS) -> dict[str, list[dict]]:
    """Workbook cells -> {tab key: [row dicts with FIELDS]}, checking every header first."""
    out = {}
    for tab, spec in tabs.items():
        cells = book.get(spec.sheet)
        if cells is None:
            raise SheetLayoutError(f"tab '{spec.sheet}' is missing")
        head = cells.get(spec.header_row, {})
        for col, fld, want in spec.columns:
            got = str(head.get(col, ""))
            if want.lower() not in got.lower():
                raise SheetLayoutError(f"'{spec.sheet}' column {col} reads '{got}', expected '{want}' ({fld})")
        for col, want in spec.groups.items():
            got = str(cells.get(1, {}).get(col, ""))
            if want.lower() not in got.lower():
                raise SheetLayoutError(f"'{spec.sheet}' row 1 column {col} reads '{got}', expected '{want}'")
        rows = []
        for n in sorted(r for r in cells if r > spec.header_row):
            raw = cells[n]
            title = str(raw.get("A", "")).strip()
            if not title:
                continue
            row = {"row": n, "title": title, "key": norm(title), **{f: None for f in FIELDS}}
            for col, fld, _ in spec.columns[1:]:
                row[fld] = _cell(fld, raw.get(col))
            rows.append(row)
        # stint: 1 for a game's first time on the service, 2 when it came back, ...
        seen: dict[str, int] = {}
        for row in sorted(rows, key=lambda r: (str(r["added"] or ""), r["row"])):
            seen[row["key"]] = row["stint"] = seen.get(row["key"], 0) + 1
        out[tab] = rows
    return out


def sheet_id(cfg: dict, service: str) -> str | None:
    return cfg["sheet"]["id"] if service == "xbox" else cfg.get("playstation", {}).get("sheet_id")


def fetch(cfg: dict, service: str = "xbox") -> bytes:
    url = XLSX_URL.format(id=sheet_id(cfg, service))
    req = urllib.request.Request(url, headers={"User-Agent": "harbinger/1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


# ── the database ───────────────────────────────────────────────────────

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS sheet_import (
  id INTEGER PRIMARY KEY, service TEXT NOT NULL, fetched_at TEXT NOT NULL, bytes INTEGER, sha256 TEXT,
  tabs TEXT,          -- JSON {{tab: rows}}
  changes INTEGER     -- rows written to sheet_change (NULL for the first, baseline import)
);
-- The latest import, one row per game per tab (a game back for a second stint has two rows).
-- Dates: 'YYYY-MM-DD', 'YYYY-MM' when the sheet only gives a month, or the sheet's own text.
CREATE TABLE IF NOT EXISTS sheet_row (
  import_id INTEGER NOT NULL REFERENCES sheet_import(id), service TEXT NOT NULL,  -- xbox | playstation
  tab TEXT NOT NULL, row INTEGER NOT NULL, title TEXT NOT NULL, key TEXT NOT NULL, stint INTEGER NOT NULL,
  {", ".join(f + (" REAL" if f in NUMBERS else " TEXT") for f in FIELDS)},
  PRIMARY KEY (service, tab, key, stint)
);
CREATE INDEX IF NOT EXISTS sheet_row_key ON sheet_row(key);
-- What changed between one import and the one before it.
CREATE TABLE IF NOT EXISTS sheet_change (
  import_id INTEGER NOT NULL REFERENCES sheet_import(id), service TEXT NOT NULL, tab TEXT NOT NULL,
  key TEXT NOT NULL, stint INTEGER NOT NULL, title TEXT NOT NULL,
  kind TEXT NOT NULL,  -- added | dropped | changed
  field TEXT, old TEXT, new TEXT
);
CREATE INDEX IF NOT EXISTS sheet_change_key ON sheet_change(key);
"""

_COLS = ["import_id", "service", "tab", "row", "title", "key", "stint"] + FIELDS


def migrate(db: sqlite3.Connection) -> None:
    """Sheet tables from before the PS Plus import (no service column) are dropped: they hold
    re-importable data, and the next ingest rebuilds them."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(sheet_row)")}
    if cols and "service" not in cols:
        db.executescript("DROP TABLE sheet_row; DROP TABLE sheet_change; DROP TABLE sheet_import;")


def import_rows(db: sqlite3.Connection, tabs: dict[str, list[dict]], fetched_at: str,
                raw: bytes | None = None, service: str = "xbox") -> str:
    """Replace this service's sheet_row rows and log the differences, in one transaction."""
    # Re-key the old rows with today's norm(), so a matching tweak never reads as a sheet change.
    old = {(r["tab"], norm(r["title"]), r["stint"]): r
           for r in _select(db, "SELECT * FROM sheet_row WHERE service = ?", (service,))}
    first = not old and not db.execute("SELECT 1 FROM sheet_import WHERE service = ?", (service,)).fetchone()
    with db:
        cur = db.execute("INSERT INTO sheet_import (service, fetched_at, bytes, sha256, tabs) VALUES (?, ?, ?, ?, ?)",
                         (service, fetched_at, len(raw) if raw else None,
                          hashlib.sha256(raw).hexdigest() if raw else None,
                          json.dumps({t: len(rs) for t, rs in tabs.items()})))
        imp = cur.lastrowid
        changes = []
        new_ids = set()
        for tab, rows in tabs.items():
            for r in rows:
                ident = (tab, r["key"], r["stint"])
                new_ids.add(ident)
                prev = old.get(ident)
                if first:
                    continue
                if prev is None:
                    changes.append((imp, service, tab, r["key"], r["stint"], r["title"], "added", None, None, None))
                    continue
                for f in FIELDS:
                    if f not in VOLATILE and _same(prev[f], r[f]) is False:
                        changes.append((imp, service, tab, r["key"], r["stint"], r["title"], "changed", f,
                                        _txt(prev[f]), _txt(r[f])))
        for ident, prev in old.items():
            if ident not in new_ids and ident[0] in tabs:
                changes.append((imp, service, *ident, prev["title"], "dropped", None, None, None))
        db.execute("DELETE FROM sheet_row WHERE service = ?", (service,))
        db.executemany(f"INSERT INTO sheet_row ({', '.join(_COLS)}) VALUES ({', '.join('?' * len(_COLS))})",
                       [(imp, service, tab, *[r[c] for c in _COLS[3:]]) for tab, rows in tabs.items() for r in rows])
        db.executemany("INSERT INTO sheet_change VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", changes)
        db.execute("UPDATE sheet_import SET changes = ? WHERE id = ?", (None if first else len(changes), imp))
    total = sum(len(rs) for rs in tabs.values())
    if first:
        return f"{service} sheet imported: {total} rows across {len(tabs)} tabs (baseline)"
    return f"{service} sheet imported: {total} rows, {len(changes)} changes since the last import"


def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            pass
    return a == b


def _txt(v) -> str | None:
    if v is None:
        return None
    return f"{v:g}" if isinstance(v, float) else str(v)


def ingest(db: sqlite3.Connection, cfg: dict, service: str = "xbox") -> str:
    """Download, check and import one service's workbook. A failure keeps the previous import."""
    spec = SERVICES[service]
    try:
        raw = fetch(cfg, service)
        tabs = extract(read_xlsx(raw, {t.sheet for t in spec.values()}), spec)
    except (OSError, zipfile.BadZipFile, ET.ParseError, SheetLayoutError) as e:
        if service == "xbox" and not db.execute("SELECT 1 FROM sheet_import WHERE service = 'xbox'").fetchone():
            raise SystemExit(f"sheet import failed and there is no earlier one: {e}")
        return f"{service} sheet import failed ({e}); kept the previous one"
    SHEET_DIR.mkdir(parents=True, exist_ok=True)
    (SHEET_DIR / f"{service}.xlsx").write_bytes(raw)
    return import_rows(db, tabs, datetime.now().isoformat(timespec="seconds"), raw, service)


def _select(db: sqlite3.Connection, q: str, args=()) -> list[dict]:
    cur = db.execute(q, args)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur]


def load_rows(db: sqlite3.Connection, service: str = "xbox") -> tuple[dict[str, list[dict]], str | None]:
    imp = db.execute("SELECT fetched_at FROM sheet_import WHERE service = ? ORDER BY id DESC LIMIT 1",
                     (service,)).fetchone()
    if not imp and service == "xbox":
        raise SystemExit("no sheet in the database yet: run `py -3.11 -m harbinger ingest` first")
    tabs: dict[str, list[dict]] = {t: [] for t in SERVICES[service]}
    for r in _select(db, "SELECT * FROM sheet_row WHERE service = ? ORDER BY tab, row", (service,)):
        tabs.setdefault(r["tab"], []).append(r)
    return tabs, imp[0] if imp else None


def load(db: sqlite3.Connection, cfg: dict) -> "Sheet":
    tabs, fetched = load_rows(db)
    return parse(tabs, fetched, cfg.get("scope", {}).get("skip_systems", ()))


# ── what the model reads ───────────────────────────────────────────────

def month(value) -> date | None:
    """'2025-10-21' or '2025-10' -> date(2025, 10, 1)."""
    m = re.match(r"(\d{4})-(\d\d)", str(value or ""))
    return date(int(m.group(1)), int(m.group(2)), 1) if m else None


def _num(v) -> float | None:
    return v if isinstance(v, (int, float)) else None


@dataclass
class Game:
    name: str
    system: str
    status: str
    added_month: date | None
    removed_month: date | None
    months: float | None
    hours: float | None
    metacritic: float | None
    genre: str
    notes: str
    premium_status: str
    premium_added: date | None
    key: str = field(init=False)

    def __post_init__(self):
        self.key = norm(self.name)


def game(r: dict) -> Game:
    return Game(
        name=r["title"], system=r.get("system") or "", status=r.get("status") or "",
        added_month=month(r.get("added")), removed_month=month(r.get("removed")), months=_num(r.get("months")),
        hours=_num(r.get("completion_h")), metacritic=_num(r.get("metacritic")), genre=r.get("genre") or "",
        notes=r.get("owner_notes") or "", premium_status=r.get("premium_status") or "",
        premium_added=month(r.get("premium_added")),
    )


@dataclass
class Sheet:
    games: list[Game]
    leaving: list[Game]
    removed: list[Game]
    first_party: set[str]
    ea_play: set[str]
    premium: set[str]
    fetched: str
    out_of_scope: set[str] = field(default_factory=set)  # keys whose every row is a skipped system


def parse(tabs: dict[str, list[dict]], fetched: str, skip_systems=()) -> Sheet:
    """Row dicts (as stored in sheet_row) -> the Sheet the model reads.

    Rows whose System is one of `skip_systems` ([scope] in config.toml; "PC" = PC Game Pass
    only) are left out. A title with both a PC row and a console row keeps the console row.
    """
    skip = set(skip_systems)
    keep = lambda r: (r.get("system") or "") not in skip
    games = lambda t: [game(r) for r in tabs.get(t, []) if keep(r)]
    scoped = {r["key"] for r in tabs.get("master", []) if keep(r)}
    return Sheet(
        out_of_scope={r["key"] for r in tabs.get("master", []) if not keep(r)} - scoped,
        games=games("master"),
        leaving=games("leaving_soon"),
        removed=games("removed"),
        first_party={r["key"] for r in tabs.get("first_party", [])},
        ea_play={r["key"] for r in tabs.get("ea_play", [])},
        premium={g.key for g in games("premium") if g.status in ("Active", "Leaving Soon")},
        fetched=fetched,
    )
