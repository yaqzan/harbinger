"""Played / playing / dropped marks: the notes import, manual marks winning, and where they land."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from harbinger import played
from harbinger.build import assemble
from harbinger.sheet import parse

from .test_build import CFG, FORECAST, TABS, TODAY
from .test_plus import ps_input

TYPES = {"PC", "PS5", "Xbox Series X", "Switch"}
STATUS = {"current": "playing", "finished": "played", "dropped": "dropped"}


def note(folder: Path, name: str, body: str) -> None:
    (folder / f"{name}.md").write_text(body, encoding="utf-8")


def mark(title, status, source="notes"):
    return {"source": source, "title": title, "status": status, "platform": None}


class Notes(unittest.TestCase):
    def test_frontmatter_reads_top_level_values(self):
        fm = played.frontmatter('---\nType: "PS5"\nStatus: "Current"\nmentions:\n  - "[[x]]"\nStarted: 2026-07-02\n---\nbody')
        self.assertEqual(fm, {"Type": "PS5", "Status": "Current", "Started": "2026-07-02"})
        self.assertEqual(played.frontmatter("no frontmatter"), {})

    def test_only_game_notes_with_a_mapped_status(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            note(d, "Nine Sols", '---\nType: "PC"\nStatus: "Finished"\n---\n')
            note(d, "Dune", '---\nType: "Film"\nStatus: "Finished"\n---\n')            # not a game
            note(d, "Hades", '---\nType: "Switch"\nStatus: "Not Started"\n---\n')      # not played yet
            (d / "sub").mkdir()
            note(d / "sub", "Media - Absolum", '---\nTitle: "Absolum"\nType: "Xbox Series X"\nStatus: "Current"\n---\n')
            got = played.read_notes(d, TYPES, STATUS)
        self.assertEqual(sorted((n["title"], n["status"]) for n in got), [("Absolum", "playing"), ("Nine Sols", "played")])

    def test_import_replaces_notes_and_keeps_manual(self):
        db = sqlite3.connect(":memory:")
        db.executescript(played.SCHEMA)
        played.mark(db, "Hades", "played")
        with tempfile.TemporaryDirectory() as d:
            note(Path(d), "Nine Sols", '---\nType: "PC"\nStatus: "Current"\n---\n')
            cfg = {"played": {"notes_dir": d, "types": list(TYPES), "status": {"Current": "playing"}}}
            self.assertIn("1 playing", played.import_notes(db, cfg))
            Path(d, "Nine Sols.md").unlink()
            played.import_notes(db, cfg)
        self.assertEqual([(m["source"], m["title"]) for m in played.load(db)], [("manual", "Hades")])

    def test_missing_folder_keeps_the_last_import(self):
        db = sqlite3.connect(":memory:")
        db.executescript(played.SCHEMA)
        db.execute("INSERT INTO played_mark VALUES ('notes', 'x', 'X', 'played', 'PC', 'now')")
        msg = played.import_notes(db, {"played": {"notes_dir": "C:/no/such/folder"}})
        self.assertIn("kept the last import", msg)
        self.assertEqual(len(played.load(db)), 1)

    def test_same_maps_a_note_title(self):
        db = sqlite3.connect(":memory:")
        db.executescript(played.SCHEMA)
        played.mark(db, "Civilization VI", "dropped")
        got = played.load(db, {"played": {"same": {"Civilization VI": "Sid Meier's Civilization VI"}}})
        self.assertEqual(got[0]["title"], "Sid Meier's Civilization VI")


class Resolve(unittest.TestCase):
    key = staticmethod(lambda t: {"hades": "h", "hades 2": "h2"}.get(t.lower()))

    def test_manual_beats_notes_and_unplayed_clears(self):
        got = played.resolve([mark("Hades", "played"), mark("hades", "unplayed", "manual"),
                              mark("Hades 2", "played", "config"), mark("Hades 2", "playing", "manual")], self.key)
        self.assertEqual(got, {"h2": "playing"})

    def test_playing_wins_within_a_source_and_misses_are_reported(self):
        marks = [mark("Hades", "dropped"), mark("Hades", "playing"), mark("Celeste", "played")]
        self.assertEqual(played.resolve(marks, self.key), {"h": "playing"})
        self.assertEqual([m["title"] for m in played.report(marks, self.key)], ["Celeste"])


class OnThePage(unittest.TestCase):
    def setUp(self):
        marks = [mark("Pacific Drive", "played"), mark("Nine Sols", "playing"), mark("Grand Theft Auto 5", "dropped"),
                 mark("Celeste", "played"), mark("Pacific", "played")]  # Pacific: strict, never a prefix match
        self.d = assemble(CFG, parse(TABS, "2026-10-09T08:46:00"), FORECAST, {"games": {}}, TODAY, TODAY,
                          ps_input(), None, marks=marks)
        self.lib = {r["key"]: r for r in self.d["library"]}

    def test_library_rows_carry_the_mark(self):
        self.assertEqual(self.lib["pacific drive"]["mark"], "played")
        self.assertEqual(self.lib["nine sols"]["mark"], "playing")
        self.assertEqual(self.lib["grand theft auto 5"]["mark"], "dropped")
        self.assertEqual(sum("mark" in r for r in self.d["library"]), 3)

    def test_unmatched_marks_are_kept_for_the_cli(self):
        self.assertEqual(sorted(m["title"] for m in self.d["played_unmatched"]), ["Celeste", "Pacific"])

    def test_board_rows_carry_it_and_done_games_never_push(self):
        board = {r["key"]: r for r in self.d["one_service"]["rows"] + self.d["one_service"]["backups"]}
        self.assertEqual(board["pacific drive"]["mark"], "played")
        self.assertIn("pacific drive", self.d["beaten"])
        self.assertNotIn("nine sols", self.d["beaten"])  # playing: still on the radar

    def test_queue_beaten_counts_as_played(self):
        cfg = {**CFG, "queue": {**CFG.get("queue", {}), "beaten": ["Pacific Drive"]}}
        d = assemble(cfg, parse(TABS, "2026-10-09T08:46:00"), FORECAST, {"games": {}}, TODAY, TODAY, ps_input(), None)
        self.assertEqual({r["key"]: r for r in d["library"]}["pacific drive"]["mark"], "played")


if __name__ == "__main__":
    unittest.main()
