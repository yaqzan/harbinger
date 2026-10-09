"""Snapshots: every run's scores in SQLite, so the page can show how odds moved."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from . import STATE_DIR

DB_FILE = STATE_DIR / "harbinger.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, as_of TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS scores (
  run_id INTEGER NOT NULL REFERENCES runs(id), game TEXT NOT NULL, key TEXT NOT NULL,
  list TEXT NOT NULL, wave TEXT, cohort INTEGER, p REAL, band TEXT, hours REAL,
  urgency TEXT, owned INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS scores_run ON scores(run_id);
"""


def connect(path=DB_FILE) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def baseline(db: sqlite3.Connection, kind: str):
    """The ingest run to compare against: the last one, or the one before it if this
    build follows that ingest (a Steam sync or rebuild re-scores the same inputs)."""
    rows = db.execute("SELECT id, at FROM runs WHERE kind = 'ingest' ORDER BY id DESC LIMIT 2").fetchall()
    if kind == "ingest":
        pick = rows[0] if rows else None
    else:
        pick = rows[1] if len(rows) > 1 else None
    if not pick:
        return None, {}
    scores = {k: (p, w) for k, p, w in db.execute(
        "SELECT key, p, wave FROM scores WHERE run_id = ? AND p IS NOT NULL", (pick[0],))}
    return pick[1], scores


def record(db: sqlite3.Connection, kind: str, as_of: str, note: str, rows: list[dict]) -> int:
    cur = db.execute("INSERT INTO runs (at, kind, as_of, note) VALUES (?, ?, ?, ?)",
                     (datetime.now().isoformat(timespec="seconds"), kind, as_of, note))
    run_id = cur.lastrowid
    db.executemany(
        "INSERT INTO scores (run_id, game, key, list, wave, cohort, p, band, hours, urgency, owned)"
        " VALUES (:run, :game, :key, :list, :wave, :cohort, :p, :band, :hours, :urgency, :owned)",
        [{"run": run_id, "cohort": None, "p": None, "band": None, "hours": None, "urgency": None,
          "wave": None, "owned": 0, **r} for r in rows])
    db.commit()
    return run_id


def history(db: sqlite3.Connection, limit: int = 12) -> list[dict]:
    q = """SELECT r.at, r.kind, r.note,
                  SUM(s.list = 'confirmed'), SUM(s.band = 'Likely'), SUM(s.band = 'Possible')
           FROM runs r LEFT JOIN scores s ON s.run_id = r.id
           WHERE r.kind = 'ingest' GROUP BY r.id ORDER BY r.id DESC LIMIT ?"""
    return [{"at": at, "kind": kind, "note": note or "", "confirmed": c or 0, "likely": lk or 0,
             "possible": ps or 0} for at, kind, note, c, lk, ps in db.execute(q, (limit,))]
