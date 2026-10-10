"""What you've played: games marked played, playing or dropped, so the page can hide the ones you're done with.

Two sources, one table (`played_mark`):
- `notes`: a folder of Markdown notes, one per game, with `Type` and `Status` in the frontmatter
  (an Obsidian media log). `[played] notes_dir` in config.local.toml; `[played] types` says which
  Types are games and `[played] status` maps a Status to played / playing / dropped. Each import
  replaces every `notes` row; a missing folder keeps the last import. A note titled unlike the
  game ("Civilization VI") is mapped in `[played.same]` (config.local.toml: your notes, your names).
- `manual`: `py -3.11 -m harbinger played "Title" played|playing|dropped|unplayed`. A manual mark
  beats the notes for the same game (`unplayed` overrides a note), and `auto` deletes it.

A mark lands on a game by strict title match (no prefix or fuzzy rungs, like Steam): a wrong match
would hide a game you haven't played. `resolve` turns the marks into one status per row key.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from .sheet import norm

SCHEMA = """
CREATE TABLE IF NOT EXISTS played_mark (
  source TEXT NOT NULL,      -- notes | manual
  key TEXT NOT NULL,         -- norm(title)
  title TEXT NOT NULL,       -- as the source spells it
  status TEXT NOT NULL,      -- played | playing | dropped | unplayed (manual only: overrides a note)
  platform TEXT,             -- the note's Type (PS5, Switch, ...)
  updated_at TEXT NOT NULL,
  PRIMARY KEY (source, key)
);
"""

STATUSES = ("played", "playing", "dropped", "unplayed")
DONE = ("played", "dropped")       # hidden by default on the page, and never pushed about
SOURCES = ("manual", "notes", "config")  # first wins for the same game ("config" = [queue] beaten)
RANK = {"playing": 0, "played": 1, "dropped": 2, "unplayed": 3}  # two titles of one source on one game

_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)
_LINE = re.compile(r"^([A-Za-z][\w ]*):[ \t]*(.*?)\s*$", re.M)


def settings(cfg: dict) -> dict:
    p = cfg.get("played", {})
    return {"notes_dir": p.get("notes_dir", ""), "types": set(p.get("types", ())),
            "status": {k.lower(): v for k, v in p.get("status", {}).items()},
            "same": {norm(k): v for k, v in p.get("same", {}).items()}}


def frontmatter(text: str) -> dict[str, str]:
    """Top-level `key: value` pairs of a note's YAML frontmatter (lists and nesting ignored)."""
    m = _FRONT.match(text)
    if not m:
        return {}
    return {k: v.strip().strip('"').strip("'") for k, v in _LINE.findall(m.group(1)) if v.strip()}


def read_notes(folder: Path, types: set[str], status_map: dict[str, str]) -> list[dict]:
    """[{title, status, platform}] for every game note with a mapped Status. The title is the
    note's `Title` property, else its file name."""
    out = []
    for path in sorted(folder.rglob("*.md")):
        try:
            fm = frontmatter(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError):
            continue
        st = status_map.get(fm.get("Status", "").lower())
        if fm.get("Type") not in types or st not in STATUSES:
            continue
        title = fm.get("Title") or path.stem
        if norm(title):
            out.append({"title": title, "status": st, "platform": fm["Type"]})
    return out


def import_notes(db: sqlite3.Connection, cfg: dict) -> str:
    s = settings(cfg)
    if not s["notes_dir"]:
        return ""  # not set up: nothing to say
    folder = Path(s["notes_dir"])
    if not folder.is_dir():
        return f"played: notes folder not found ({folder}), kept the last import"
    notes = read_notes(folder, s["types"], s["status"])
    now = datetime.now().isoformat(timespec="seconds")
    rows = {}
    for n in notes:
        k = norm(n["title"])
        if k not in rows or RANK[n["status"]] < RANK[rows[k][3]]:
            rows[k] = ("notes", k, n["title"], n["status"], n["platform"], now)
    with db:
        db.execute("DELETE FROM played_mark WHERE source = 'notes'")
        db.executemany("INSERT INTO played_mark VALUES (?, ?, ?, ?, ?, ?)", rows.values())
    count = {st: sum(r[3] == st for r in rows.values()) for st in ("played", "playing", "dropped")}
    return "played: " + ", ".join(f"{n} {st}" for st, n in count.items()) + " from notes"


def mark(db: sqlite3.Connection, title: str, status: str) -> None:
    """Set a manual mark; `auto` removes it so the notes decide again."""
    k = norm(title)
    with db:
        db.execute("DELETE FROM played_mark WHERE source = 'manual' AND key = ?", (k,))
        if status != "auto":
            db.execute("INSERT INTO played_mark VALUES ('manual', ?, ?, ?, NULL, ?)",
                       (k, title, status, datetime.now().isoformat(timespec="seconds")))


def load(db: sqlite3.Connection, cfg: dict | None = None) -> list[dict]:
    """Every mark; a title in [played.same] is looked up under the name it maps to."""
    same = settings(cfg or {})["same"]
    return [{"source": s, "title": same.get(norm(t), t), "status": st, "platform": p}
            for s, t, st, p in db.execute("SELECT source, title, status, platform FROM played_mark")]


def resolve(marks: list[dict], key_of) -> dict[str, str]:
    """{row key: played | playing | dropped}. `key_of(title)` is the row a title lands on, or None.
    Per row the first source in SOURCES wins; within one source, playing beats played beats
    dropped. An `unplayed` winner means no mark."""
    best: dict[str, tuple[int, int, str]] = {}
    for m in marks:
        k = key_of(m["title"])
        if not k:
            continue
        rank = (SOURCES.index(m["source"]), RANK[m["status"]], m["status"])
        if k not in best or rank < best[k]:
            best[k] = rank
    return {k: st for k, (_, _, st) in best.items() if st != "unplayed"}


def report(marks: list[dict], key_of) -> list[dict]:
    """The marks no row picked up (not on a service or in a library you have, or spelled differently)."""
    return [m for m in marks if m["status"] != "unplayed" and not key_of(m["title"])]
