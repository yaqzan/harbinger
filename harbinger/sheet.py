"""Read u/ABattleVet's "XBOX Game Pass Master List" through its public CSV export."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime

from . import STATE_DIR

CSV_URL = "https://docs.google.com/spreadsheets/d/{id}/gviz/tq?tqx=out:csv&gid={gid}"
SHEET_DIR = STATE_DIR / "sheet"
TABS = ("master", "leaving_soon", "removed", "premium", "first_party", "ea_play")


def norm(name: str) -> str:
    """Match key for titles across the sheet, its tabs, Steam and the forecast."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\((game preview|early access|pc|xbox series x\|s)\)", " ", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def resolve(name: str, keys) -> str | None:
    """The sheet key another source's title refers to, or None.

    Exact match first, then the same letters without spaces ("CloverPit"), then with a
    trailing year dropped ("Keeper (2025)"), then a unique word-prefix ("Sopa" for
    "Sopa: Tale of the Stolen Potato"). Ambiguous prefixes resolve to nothing.
    """
    key = norm(name)
    keys = list(keys)
    if key in keys:
        return key
    compact = key.replace(" ", "")
    strip_year = lambda k: re.sub(r" (19|20)\d\d$", "", k)
    for k in keys:
        if k.replace(" ", "") == compact or strip_year(k) == key:
            return k
    pref = [k for k in keys if k.startswith(key + " ")]
    return pref[0] if len(pref) == 1 else None


def month(value: str) -> date | None:
    """'Oct 2025' -> date(2025, 10, 1)."""
    try:
        return datetime.strptime(value.strip(), "%b %Y").date()
    except ValueError:
        return None


def num(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


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


def fetch(cfg: dict) -> dict[str, str]:
    """Download every tab as CSV text and cache it under state/sheet/."""
    SHEET_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for tab in TABS:
        url = CSV_URL.format(id=cfg["sheet"]["id"], gid=cfg["sheet"][tab])
        req = urllib.request.Request(url, headers={"User-Agent": "harbinger/1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode("utf-8")
        (SHEET_DIR / f"{tab}.csv").write_text(text, encoding="utf-8")
        out[tab] = text
    return out


def load_cached() -> dict[str, str]:
    missing = [t for t in TABS if not (SHEET_DIR / f"{t}.csv").exists()]
    if missing:
        raise SystemExit(f"no cached sheet tabs ({', '.join(missing)}): run `py -3.11 -m harbinger ingest` first")
    return {t: (SHEET_DIR / f"{t}.csv").read_text(encoding="utf-8") for t in TABS}


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def parse_games(text: str) -> list[Game]:
    """Master List layout (cols A-V): two header rows, then one game per row."""
    games = []
    for r in _rows(text)[2:]:
        r = r + [""] * (22 - len(r))
        if not r[0].strip():
            continue
        games.append(Game(
            name=r[0].strip(), system=r[1], status=r[3].strip(),
            added_month=month(r[4]), removed_month=month(r[5]), months=num(r[6]),
            hours=num(r[10]), metacritic=num(r[9]), genre=r[11], notes=r[13],
            premium_status=r[17].strip(), premium_added=month(r[18]),
        ))
    return games


def title_set(text: str, skip_rows: int = 1) -> set[str]:
    """First-column titles of a simple list tab, normalized."""
    return {norm(r[0]) for r in _rows(text)[skip_rows:] if r and r[0].strip()}


@dataclass
class Sheet:
    games: list[Game]
    leaving: list[Game]
    removed: list[Game]
    first_party: set[str]
    ea_play: set[str]
    premium: set[str]
    fetched: str


def parse(tabs: dict[str, str], fetched: str) -> Sheet:
    return Sheet(
        games=parse_games(tabs["master"]),
        leaving=parse_games(tabs["leaving_soon"]),
        removed=parse_games(tabs["removed"]),
        first_party=title_set(tabs["first_party"]),
        ea_play=title_set(tabs["ea_play"]),
        premium={g.key for g in parse_games(tabs["premium"]) if g.status in ("Active", "Leaving Soon")},
        fetched=fetched,
    )
