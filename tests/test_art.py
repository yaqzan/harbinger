"""Cover art: source order, exact-name matching, caching and the per-run budget (no network)."""

import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from harbinger import art, steam, psn

NOW = datetime(2026, 10, 9, 12, 0)
PNG = b"\x89PNG"


def db():
    d = sqlite3.connect(":memory:")
    for s in (steam.SCHEMA, psn.SCHEMA, art.SCHEMA):
        d.executescript(s)
    return d


class ArtTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(art, "ART_DIR", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        self.db = db()

    def test_owned_steam_game_uses_its_appid_before_any_search(self):
        self.db.execute("INSERT INTO steam_game (appid, name, key, owned, first_seen, last_seen) VALUES (1145360, 'Hades', 'hades', 1, 'x', 'x')")
        with mock.patch.object(art, "steam_art", return_value=(b"x", "jpg")) as got, \
                mock.patch.object(art, "steam_search") as search:
            self.assertEqual(art.resolve(self.db, "hades", "Hades")[0], "steam")
        got.assert_called_once_with(1145360)
        search.assert_not_called()

    def test_playstation_icon_then_searches(self):
        with mock.patch.object(art, "steam_search", return_value=None), \
                mock.patch.object(art, "microsoft_art", return_value=(PNG, "png")):
            self.assertEqual(art.resolve(self.db, "x", "X")[0], "microsoft store")
        with mock.patch.object(art, "steam_search", return_value=None), \
                mock.patch.object(art, "microsoft_art", return_value=None):
            self.assertIsNone(art.resolve(self.db, "x", "X"))

    def test_steam_search_needs_the_exact_title(self):
        body = b'{"items": [{"type": "app", "name": "Hades II", "id": 1}, {"type": "app", "name": "Hades", "id": 2}]}'
        with mock.patch.object(art, "_get", return_value=(body, "application/json")):
            self.assertEqual(art.steam_search("Hades"), 2)
            self.assertIsNone(art.steam_search("Hade"))
            self.assertEqual(art.steam_search("Hades (2020)"), 2)   # year and preview tags are dropped

    def test_fetch_caches_misses_and_respects_the_budget(self):
        cfg = {"art": {"budget": 2, "pause_s": 0}}
        found = [("steam", PNG, "png"), None, ("psn", PNG, "png")]
        with mock.patch.object(art, "resolve", side_effect=found):
            note = art.fetch(self.db, {"a": "A", "b": "B", "c": "C"}, cfg, NOW)
        self.assertEqual(note, "art: 1 found, 1 missing, 1 left for the next run")
        self.assertEqual(list(art.load(self.db)), ["a"])
        # a cached miss is not retried inside retry_days, a cached hit never is
        with mock.patch.object(art, "resolve", return_value=None) as r:
            art.fetch(self.db, {"a": "A", "b": "B"}, cfg, NOW)
        r.assert_not_called()

    def test_disabled_does_nothing(self):
        self.assertEqual(art.fetch(self.db, {"a": "A"}, {"art": {"enabled": False}}, NOW), "art: disabled")

    def test_attach_puts_art_on_rows_by_key(self):
        data = {"confirmed": [{"game": "Hades", "key": "hades"}], "queue": [], "watchlist": [], "owned": [],
                "one_service": {"rows": [{"game": "Nine Sols", "key": ""}]}}
        art.attach(data, {"hades": "/art/aaaaaaaaaaaaaaaa.jpg"})
        self.assertEqual(data["confirmed"][0]["art"], "/art/aaaaaaaaaaaaaaaa.jpg")
        self.assertNotIn("art", data["one_service"]["rows"][0])


if __name__ == "__main__":
    unittest.main()
