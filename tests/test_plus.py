"""PS Plus: tiers, the third-Monday calendar, and the only-on-one-service list."""

import unittest
from datetime import date
from pathlib import Path

from harbinger import model, plus, sheet, store
from harbinger.build import assemble
from harbinger.sheet import FIELDS, norm

from .test_build import CFG, FORECAST, TABS, TODAY

CFG_PS = dict(CFG, playstation=dict(CFG["playstation"], tier="extra"))


def ps(name, tier, status="Active", added="2025-10-21", removed=None, hours=10.0):
    r = {"title": name, "key": norm(name), "stint": 1, **{f: None for f in FIELDS}}
    r.update(system="PS5/PS4", tier=tier, status=status, added=added, removed=removed, completion_h=hours)
    return r


PS_MASTER = [
    ps("Silent Hill 2 (2024)", "Extra", "Leaving Soon", removed="2026-10-19", hours=16.0),
    ps("Hunt: Showdown 1896", "Essential", "Leaving Soon", added="2026-10-06", removed="2026-11-02"),
    ps("Grand Theft Auto V", "Extra", added="2025-11-18", hours=32.0),     # 12-mo checkpoint Nov 16
    ps("Tekken 3", "Premium (Classics)"),                                   # above an Extra tier
    ps("Assassin's Creed Thing", "Extra (Ubisoft+ Classics)"),
    ps("Old Removed", "Extra", "Removed", removed="2025-01-20"),
    ps("Nine Sols", "Extra", added="2025-06-17"),                           # also on Game Pass
    ps("Evil West", "Extra", added="2025-06-17"),                           # leaving Game Pass, safe on PS
    ps("Owned On Steam", "Extra"),
    ps("Quiet Game", "Extra", "Leaving Soon", removed="2026-10-19"),        # on Game Pass, leaving PS
]


def ps_input(tier="extra"):
    return {"games": plus.catalogue({"master": PS_MASTER}, tier), "fetched": "2026-10-09T08:46:00", "tier": tier.title()}


class Calendar(unittest.TestCase):
    def test_third_monday(self):
        self.assertEqual(model.third_monday(2026, 10), date(2026, 10, 19))
        self.assertEqual(model.next_waves(date(2026, 10, 9), 3, "playstation"),
                         [date(2026, 10, 19), date(2026, 11, 16), date(2026, 12, 21)])
        self.assertEqual(model.nearest_wave(date(2026, 11, 1), "playstation"), date(2026, 10, 19))


class Tiers(unittest.TestCase):
    def test_tier_includes_the_ones_below(self):
        names = lambda tier: {g.name for g in plus.catalogue({"master": PS_MASTER}, tier)}
        self.assertIn("Hunt: Showdown 1896", names("extra"))
        self.assertNotIn("Tekken 3", names("extra"))
        self.assertIn("Tekken 3", names("premium"))
        self.assertEqual(names("essential"), {"Hunt: Showdown 1896"})
        self.assertEqual(names("none"), set())
        self.assertNotIn("Old Removed", names("premium"))

    def test_outlooks(self):
        games = {g.name: g for g in plus.catalogue({"master": PS_MASTER}, "extra")}
        out = lambda n: plus.outlook(games[n], TODAY, CFG_PS, plus.announced(list(games.values()), TODAY))
        self.assertEqual((out("Silent Hill 2 (2024)")["state"], out("Silent Hill 2 (2024)")["wave"]),
                         ("confirmed", date(2026, 10, 19)))
        self.assertEqual(out("Hunt: Showdown 1896")["state"], "claim")
        gta = out("Grand Theft Auto V")
        self.assertEqual((gta["wave"], gta["p"]), (date(2026, 11, 16), CFG["playstation"]["base_rates"]["extra"]["12"]))
        self.assertEqual(out("Assassin's Creed Thing")["state"], "not scored")


class OneService(unittest.TestCase):
    def setUp(self):
        steam = {"games": {"owned on steam": {"name": "Owned On Steam", "appid": 1, "played_h": 0,
                                              "ach_done": None, "ach_total": None}}}
        d = assemble(CFG_PS, sheet.parse(TABS, "2026-10-09T08:46:00"), FORECAST, steam, TODAY, TODAY, ps_input())
        self.one = d["one_service"]
        self.rows = {(r["game"], r["service"].split(" ")[0]): r for r in self.one["rows"]}

    def test_steam_and_both_services_are_left_out(self):
        self.assertNotIn(("Owned On Steam", "PS"), self.rows)
        self.assertNotIn(("Nine Sols", "Game"), self.rows)   # safe on PS Plus
        self.assertNotIn(("Nine Sols", "PS"), self.rows)     # counted on the Game Pass side
        self.assertGreaterEqual(self.one["skipped_both"], 1)

    def test_a_copy_that_is_leaving_is_no_backup(self):
        self.assertNotIn(("Evil West", "Game"), self.rows)   # leaving Game Pass, but safe on PS Plus
        self.assertIn(("Evil West", "PS"), self.rows)        # and its PS copy has no Game Pass backup
        self.assertIn(("Quiet Game", "Game"), self.rows)     # its PS copy leaves Oct 19: no backup
        self.assertNotIn(("Quiet Game", "PS"), self.rows)  # safe on Game Pass

    def test_confirmed_first_then_likely_soonest_first(self):
        rows = self.one["rows"]
        order = [r["band"] for r in rows]
        self.assertEqual(order, sorted(order, key=lambda b: {"Confirmed": 0, "Likely": 1, "Possible": 2, "Thin": 3, "": 4}[b]))
        conf = [r["wave"] for r in rows if r["band"] == "Confirmed"]
        self.assertEqual(conf, sorted(conf))
        self.assertEqual(self.rows[("Hunt: Showdown 1896", "PS")]["action"], "Claim by Nov 2")

    def test_no_tier_means_game_pass_only(self):
        d = assemble(CFG, sheet.parse(TABS, "2026-10-09T08:46:00"), FORECAST, {"games": {}}, TODAY, TODAY, None)
        self.assertEqual(d["one_service"]["ps_tier"], "none")
        self.assertTrue(all(r["service"] == "Game Pass" for r in d["one_service"]["rows"]))


class TwoSheets(unittest.TestCase):
    def test_importing_one_service_leaves_the_other_alone(self):
        db = store.connect(Path(":memory:"))
        numbered = lambda rows: [dict(r, row=i + 3) for i, r in enumerate(rows)]
        xb = {"master": numbered(TABS["master"])}
        sheet.import_rows(db, xb, "2026-10-09T08:00:00", service="xbox")
        sheet.import_rows(db, {"master": numbered(PS_MASTER)}, "2026-10-09T08:01:00", service="playstation")
        sheet.import_rows(db, {"master": numbered(PS_MASTER[:2])}, "2026-10-10T08:01:00", service="playstation")
        xbox, fetched = sheet.load_rows(db, "xbox")
        self.assertEqual((len(xbox["master"]), fetched), (len(xb["master"]), "2026-10-09T08:00:00"))
        dropped = db.execute("SELECT COUNT(*) FROM sheet_change WHERE service = 'playstation' AND kind = 'dropped'")
        self.assertEqual(dropped.fetchone()[0], len(PS_MASTER) - 2)


if __name__ == "__main__":
    unittest.main()
