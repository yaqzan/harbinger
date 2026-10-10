"""The library list (one row per game across Game Pass, PS Plus, Steam, PlayStation) and Steam ratings."""

import sqlite3
import unittest
from datetime import date, datetime
from unittest import mock

from harbinger import art, ratings
from harbinger.build import assemble
from harbinger.sheet import norm, parse

from .test_build import CFG, FORECAST, TABS, TODAY
from .test_plus import ps_input


def lib(steam=None, psn=None, scores=None):
    d = assemble(CFG, parse(TABS, "2026-10-09T08:46:00"), FORECAST, steam or {"games": {}}, TODAY, TODAY,
                 ps_input(), psn, scores=scores)
    return {r["key"]: r for r in d["library"]}


class Overlaps(unittest.TestCase):
    def setUp(self):
        self.steam = {"games": {
            "nine sols": {"name": "Nine Sols", "appid": 11, "played_h": 3.0, "ach_done": 1, "ach_total": 2},
            "stardew valley": {"name": "Stardew Valley", "appid": 22, "played_h": 40.0, "ach_done": 5, "ach_total": 9}}}
        self.psn = {"games": {"bloodborne": {"name": "Bloodborne", "where": "PlayStation", "played_h": 2.0},
                              "hunt showdown 1896": {"name": "Hunt: Showdown 1896", "where": "PS Plus claim", "played_h": 0}}}
        self.rows = lib(self.steam, self.psn)

    def test_game_pass_game_also_on_ps_plus_is_one_row(self):
        r = self.rows["nine sols"]
        self.assertEqual((r["gp"], r["ps"], r["steam"], r["psn"]), (1, "Extra", 1, 0))
        self.assertEqual(r["appid"], 11)
        self.assertEqual(r["played"], 3.0)

    def test_ps_only_and_gp_only(self):
        gta = self.rows[norm("Grand Theft Auto V")]
        self.assertEqual((gta["gp"], gta["ps"]), (0, "Extra"))
        self.assertEqual((self.rows["forecast game"]["gp"], self.rows["forecast game"]["ps"]), (1, ""))

    def test_a_game_on_no_service_is_its_own_row(self):
        r = self.rows["stardew valley"]
        self.assertEqual((r["gp"], r["ps"], r["steam"]), (0, "", 1))
        r = self.rows["bloodborne"]
        self.assertEqual((r["steam"], r["psn"]), (0, 1))

    def test_a_ps_plus_claim_is_membership_not_ownership(self):
        r = self.rows["hunt showdown 1896"]
        self.assertEqual((r["ps"], r["psn"]), ("Essential", 0))

    def test_leave_dates_ride_on_the_service_that_loses_it(self):
        self.assertEqual(self.rows["pacific drive"]["gp_leaves"][1], "Confirmed")
        self.assertEqual(self.rows["silent hill 2 2024"]["ps_leaves"][0], "2026-10-19")

    def test_pc_only_and_removed_games_are_not_on_game_pass(self):
        self.assertEqual(self.rows.get("frostpunk 2", {"gp": 0})["gp"], 0)


class SheetScores(unittest.TestCase):
    def test_a_score_the_catalogue_row_lacks_comes_from_any_sheet_row(self):
        rows = lib(scores={norm("Grand Theft Auto V"): {"mc": 97.0, "us": 8.9}, "forecast game": {"mc": 70.0}})
        gta = rows[norm("Grand Theft Auto V")]
        self.assertEqual((gta["mc"], gta["us"]), (97.0, 8.9))
        self.assertEqual(rows["forecast game"]["mc"], 70.0)


NOW = datetime(2026, 10, 9, 12, 0)


class Ratings(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(ratings.SCHEMA)
        self.cfg = {"ratings": {"budget": 2, "pause_s": 0}}

    def test_owned_appid_skips_the_search_and_budget_caps_the_run(self):
        wanted = [("a", "A", 1, False), ("b", "B", None, False), ("c", "C", None, False)]
        with mock.patch.object(art, "steam_search", return_value=7) as s, \
                mock.patch.object(ratings, "summary", return_value=(90, 100)):
            note = ratings.fetch(self.db, wanted, self.cfg, NOW)
        self.assertEqual(note, "ratings: 2 rated, 0 not on Steam, 1 left for the next run")
        s.assert_called_once_with("B")
        self.assertEqual(ratings.load(self.db)["a"], {"appid": 1, "mc": None, "pct": 90, "n": 100})

    def test_no_steam_app_is_cached_and_not_retried_inside_retry_days(self):
        with mock.patch.object(art, "steam_search", return_value=None), mock.patch.object(ratings, "summary") as sm:
            ratings.fetch(self.db, [("x", "X", None, False)], self.cfg, NOW)
            ratings.fetch(self.db, [("x", "X", None, False)], self.cfg, NOW)
        sm.assert_not_called()
        self.assertEqual(ratings.load(self.db), {})

    def test_throttled_summary_stops_the_run_and_keeps_the_rest(self):
        with mock.patch.object(ratings, "summary", return_value=None):
            note = ratings.fetch(self.db, [("a", "A", 1, False), ("b", "B", 2, False)], self.cfg, NOW)
        self.assertEqual(note, "ratings: 0 rated, 0 not on Steam, Steam stopped answering, 2 left for the next run")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM steam_rating").fetchone()[0], 0)

    def test_few_reviews_show_no_score(self):
        self.db.execute("INSERT INTO steam_rating (key, name, appid, positive, total, checked_at) VALUES ('a', 'A', 1, 4, 5, '2026-10-09T00:00:00')")
        rows = [{"key": "a", "game": "A"}]
        ratings.attach(rows, ratings.load(self.db))
        self.assertNotIn("rating", rows[0])
        self.assertEqual(rows[0]["appid"], 1)
        ratings.attach(rows, ratings.load(self.db, 3))
        self.assertEqual((rows[0]["rating"], rows[0]["reviews"]), (80, 5))

    def test_leaving_games_are_asked_first_then_owned(self):
        rows = [{"key": "c", "game": "C", "steam": 0}, {"key": "b", "game": "B", "steam": 1, "appid": 5},
                {"key": "a", "game": "A", "steam": 0, "gp_leaves": ["2026-10-15", "Confirmed", 1.0]}]
        self.assertEqual([w[0] for w in ratings.wanted(rows)], ["a", "b", "c"])

    def test_metacritic_is_asked_only_for_games_without_one_and_filled_in_by_attach(self):
        with mock.patch.object(ratings, "summary", return_value=(9, 10)),                 mock.patch.object(ratings, "metacritic", return_value=81) as m:
            ratings.fetch(self.db, [("a", "A", 1, True), ("b", "B", 2, False)], self.cfg, NOW)
        m.assert_called_once_with(1)
        rows = [{"key": "a", "game": "A"}, {"key": "b", "game": "B", "mc": 50.0}]
        ratings.attach(rows, ratings.load(self.db))
        self.assertEqual((rows[0]["mc"], rows[1]["mc"]), (81.0, 50.0))

    def test_a_cached_game_is_asked_for_metacritic_once(self):
        self.db.execute("INSERT INTO steam_rating (key, name, appid, positive, total, checked_at)"
                        " VALUES ('a', 'A', 1, 9, 10, '2026-10-09T00:00:00')")
        with mock.patch.object(ratings, "summary") as sm, mock.patch.object(ratings, "metacritic", return_value=None) as m:
            ratings.fetch(self.db, [("a", "A", 1, True)], self.cfg, NOW)
            ratings.fetch(self.db, [("a", "A", 1, True)], self.cfg, NOW)
        sm.assert_not_called()
        m.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
