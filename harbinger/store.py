"""harbinger.sqlite: the imported sheet, the Steam library, title matches and score snapshots.

Each source module owns its tables' schema (sheet.SCHEMA, steam.SCHEMA, titles.SCHEMA); the
snapshot tables (every run's scores, so the page can show how odds moved) live here.
"""

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
CREATE TABLE IF NOT EXISTS queue_alert (
  key TEXT NOT NULL, wave TEXT NOT NULL, stage TEXT NOT NULL, game TEXT NOT NULL, sent_at TEXT NOT NULL,
  PRIMARY KEY (key, wave, stage)
);
"""


def connect(path=DB_FILE) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    from . import psn, sheet, steam, titles
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys = ON")
    sheet.migrate(db)
    titles.migrate(db)
    for schema in (SCHEMA, sheet.SCHEMA, steam.SCHEMA, psn.SCHEMA, titles.SCHEMA):
        db.executescript(schema)
    psn.migrate(db)
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


def confirmed_keys(db: sqlite3.Connection) -> set[str] | None:
    """Verified confirmed leavers in the last ingest run; None if there's no ingest yet."""
    last = db.execute("SELECT id FROM runs WHERE kind = 'ingest' ORDER BY id DESC LIMIT 1").fetchone()
    if not last:
        return None
    return {k for (k,) in db.execute("SELECT key FROM scores WHERE run_id = ? AND list = 'confirmed'", last)}


def alerts_sent(db: sqlite3.Connection) -> set[tuple[str, str, str]]:
    """(key, wave, stage) of every queue push already delivered."""
    return set(db.execute("SELECT key, wave, stage FROM queue_alert"))


def mark_alerts(db: sqlite3.Connection, rows: list[dict]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    db.executemany("INSERT OR IGNORE INTO queue_alert (key, wave, stage, game, sent_at) VALUES (?, ?, ?, ?, ?)",
                   [(r["key"], r["wave"], r["stage"], r["game"], now) for r in rows])
    db.commit()


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
