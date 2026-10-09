"""A whole run pinned to Oct 9, 2026: the sanity check for the first real output."""

import csv
import io
import unittest
from datetime import date

from harbinger import load_config
from harbinger.build import assemble
from harbinger.sheet import parse

CFG = load_config(local=None)
CFG["queue"] = {"gone": ["Frostpunk 2"], "tracking": ["Nine Sols"]}
TODAY = date(2026, 10, 9)
HEAD = [["Complete Game Pass Master List", "", ""], ["Game", "System", "xCloud", "Status"]]


def row(name, status, added, months, hours, removed="", notes="", prem="", prem_added=""):
    r = [""] * 22
    r[0], r[1], r[3], r[4], r[5], r[6] = name, "Xbox / PC", status, added, removed, str(months)
    r[10], r[13], r[17], r[18] = ("" if hours is None else str(hours)), notes, prem, prem_added
    return r


def to_csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()


LEAVING = [
    row("Nova Roma (Game Preview)", "Leaving Soon", "Mar 2026", 6.63, 7, "Oct 2026"),
    row("Pacific Drive", "Leaving Soon", "Oct 2025", 11.73, 20, "Oct 2026"),
    row("Evil West", "Leaving Soon", "Oct 2025", 11.80, 11, "Oct 2026"),
    row("The Casting of Frank Stone", "Leaving Soon", "Oct 2025", 12.03, 6, "Oct 2026"),
    row("Clair Obscur: Expedition 33", "Leaving Soon", "Apr 2025", 17.70, 26, "Oct 2026"),
    row("Crime Scene Cleaner", "Leaving Soon", "Apr 2025", 17.93, 13, "Oct 2026"),
    row("Donut County", "Leaving Soon", "Oct 2024", 23.93, 2, "Oct 2026"),
    row("A Plague Tale: Requiem", "Leaving Soon", "Oct 2022", 47.90, 15, "Oct 2026"),
]
ACTIVE = [
    row("Forecast Game", "Active", "Nov 2025", 11.2, 10),        # 12-mo wave Oct 31, on the forecast
    row("Quiet Game", "Active", "Oct 2025", 11.4, 10),           # Oct 28 anniversary, Oct 31 wave, missing from the forecast
    row("Far Game", "Active", "Nov 2025", 10.7, 40),             # 12-mo wave Nov 15, no forecast for Nov
    row("Halo Something", "Active", "Nov 2025", 11.2, 10),       # first-party
    row("Assassin's Creed Thing", "Active", "Oct 2025", 12.27, 30, notes="Ubisoft games joining with price increase"),
    row("Survivor Game", "Active", "Oct 2025", 11.8, 8),         # 12-mo wave Oct 15, not named
    row("Nine Sols", "Active", "Nov 2024", 22.7, 25),
    row("Frostpunk 2", "Removed", "Sep 2024", 24.0, 20, "Sep 2026"),
]
TABS = {
    "master": to_csv(HEAD + LEAVING + ACTIVE),
    "leaving_soon": to_csv(HEAD + LEAVING),
    "removed": to_csv(HEAD + [ACTIVE[-1]]),
    "premium": to_csv(HEAD),
    "first_party": to_csv([["Published or Developed by Subsidiary"], ["Halo Something"]]),
    "ea_play": to_csv([["Games"]]),
}
FORECAST = {"checked_at": "2026-10-09T08:46:00", "covers": ["2026-10"], "sources": [], "confirmed": [],
            "listed": [{"game": "Forecast Game", "month": "2026-10", "unlikely": False}]}


def run(steam=None):
    sheet = parse(TABS, "2026-10-09T08:46:00")
    return assemble(CFG, sheet, FORECAST, steam or {"games": {}}, TODAY, TODAY)


class SanityCheck(unittest.TestCase):
    def setUp(self):
        self.d = run()
        self.watch = {r["game"]: r for r in self.d["watchlist"]}

    def test_summary_matches_expectation(self):
        s = self.d["summary"]
        self.assertEqual(s["confirmed_count"], 8)
        self.assertEqual(s["finishable_count"], 3)
        self.assertEqual(s["hours_available"], 7.7)
        self.assertEqual(s["days_to_next_wave"], 6)
        self.assertEqual(s["next_notice"], "Oct 18")
        for name in ("Donut County", "The Casting of Frank Stone", "Nova Roma"):
            self.assertIn(name, s["takeaway"])
        self.assertNotIn("—", s["takeaway"])

    def test_finishable_are_the_three_short_ones(self):
        fin = sorted(r["game"] for r in self.d["confirmed"] if r["verdict"] in ("Doable", "Tight"))
        self.assertEqual(fin, ["Donut County", "Nova Roma (Game Preview)", "The Casting of Frank Stone"])

    def test_superball_is_shown_but_unverified_and_uncounted(self):
        sb = [r for r in self.d["confirmed"] if r["game"] == "Superball"]
        self.assertEqual(len(sb), 1)
        self.assertFalse(sb[0]["verified"])

    def test_no_past_dates(self):
        for r in self.d["confirmed"] + self.d["watchlist"]:
            self.assertGreaterEqual(r["wave"], TODAY.isoformat())

    def test_forecast_listed_is_likely(self):
        self.assertEqual(self.watch["Forecast Game"]["band"], "Likely")
        self.assertAlmostEqual(self.watch["Forecast Game"]["p"], 0.53, delta=0.01)
        self.assertEqual(self.watch["Quiet Game"]["band"], "Thin")
        self.assertAlmostEqual(self.watch["Far Game"]["p"], CFG["base_rates"]["12"], delta=0.001)

    def test_exclusions(self):
        self.assertNotIn("Halo Something", self.watch)
        self.assertNotIn("Assassin's Creed Thing", self.watch)
        self.assertEqual([r["game"] for r in self.d["ubisoft"]], ["Assassin's Creed Thing"])

    def test_unnamed_game_on_announced_wave_survives(self):
        self.assertNotIn("Survivor Game", self.watch)
        self.assertIn("Survivor Game", [r["game"] for r in self.d["survivors"]])

    def test_queue(self):
        q = {r["game"]: r for r in self.d["queue"]}
        self.assertTrue(q["Frostpunk 2"]["state"].startswith("Gone"))
        self.assertTrue(q["Nine Sols"]["next_check"].startswith("24 mo"))

    def test_chart_counts(self):
        oct15 = self.d["waves"][0]
        self.assertEqual((oct15["label"], oct15["Confirmed"]), ("Oct 15", 8))


class SteamOwnership(unittest.TestCase):
    def test_owned_game_leaves_the_urgent_lists(self):
        steam = {"games": {"forecast game": {"name": "Forecast Game", "appid": 1, "played_h": 4,
                                             "ach_done": 5, "ach_total": 10},
                           "evil west": {"name": "Evil West", "appid": 2, "played_h": 0,
                                         "ach_done": None, "ach_total": None}}}
        d = run(steam)
        self.assertNotIn("Forecast Game", [r["game"] for r in d["watchlist"]])
        owned = {r["game"]: r for r in d["owned"]}
        self.assertEqual(owned["Forecast Game"]["hours"], 5.0)  # 10 h * half the achievements left
        ew = [r for r in d["confirmed"] if r["game"] == "Evil West"][0]
        self.assertEqual(ew["verdict"], "Owned on Steam")
        self.assertEqual(d["summary"]["confirmed_count"], 8)
        self.assertTrue(d["summary"]["takeaway"].startswith("8 games leave Oct 15 and you own 1 of them on Steam."))


if __name__ == "__main__":
    unittest.main()


class Config(unittest.TestCase):
    def test_fresh_clone_watches_nothing(self):
        cfg = load_config(local=None)
        self.assertEqual(cfg["queue"], {"gone": [], "tracking": []})
        self.assertNotIn("steam", cfg)

    def test_local_file_merges_over_shared(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            local = Path(d) / "config.local.toml"
            local.write_text("\n".join(['[queue]', 'tracking = ["Nine Sols"]', '[play]', 'hours_per_week = 12']),
                             encoding="utf-8")
            cfg = load_config(local=local)
        self.assertEqual(cfg["queue"]["tracking"], ["Nine Sols"])
        self.assertEqual(cfg["queue"]["gone"], [])
        self.assertEqual(cfg["play"]["hours_per_week"], 12)
        self.assertEqual(cfg["play"]["buffer_weeks"], 2)


class TrustedSources(unittest.TestCase):
    def test_untrusted_outlet_cannot_confirm(self):
        fc = dict(FORECAST, confirmed=[{"game": "Superball", "wave": "2026-10-15", "source": "Insider Gaming"},
                                       {"game": "Quiet Game", "wave": "2026-10-31", "source": "Xbox Wire"}])
        d = assemble(CFG, parse(TABS, "2026-10-09T08:46:00"), fc, {"games": {}}, TODAY, TODAY)
        conf = {r["game"]: r for r in d["confirmed"]}
        self.assertFalse(conf["Superball"]["verified"])
        self.assertTrue(conf["Quiet Game"]["verified"])
        self.assertEqual(d["summary"]["confirmed_count"], 9)  # 8 + Quiet Game, not Superball
