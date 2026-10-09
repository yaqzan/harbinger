"""PlayStation library: PSN import, what counts as owned, discs, and claimed PS Plus games."""

import unittest
from pathlib import Path

from harbinger import psn, sheet, store
from harbinger.build import assemble

from .test_build import CFG, FORECAST, TABS, TODAY
from .test_plus import CFG_PS, ps_input


def bought(eid, name, membership="NONE", preorder=False):
    return {"entitlementId": eid, "name": name, "membership": membership, "isPreOrder": preorder,
            "isActive": True, "isDownloadable": True, "platform": "PS5", "productId": f"P-{eid}", "titleId": f"T-{eid}",
            "conceptId": 1, "image": {"url": "https://image"}}


def played(tid, name, duration, service="none_purchased"):
    return {"titleId": tid, "name": name, "category": "ps5_native_game", "service": service, "playCount": 3,
            "playDuration": duration, "firstPlayedDateTime": "2026-01-01T00:00:00Z",
            "lastPlayedDateTime": "2026-10-01T00:00:00Z", "concept": {"id": 9}, "imageUrl": "https://image"}


def trophies(npid, name, progress, earned, defined):
    return {"npCommunicationId": npid, "trophyTitleName": name, "trophyTitlePlatform": "PS5", "progress": progress,
            "earnedTrophies": {"bronze": earned}, "definedTrophies": {"bronze": defined},
            "lastUpdatedDateTime": "2026-10-01T00:00:00Z"}


RAW = {
    "purchased": [bought("E1", "Evil West"), bought("E2", "Hunt: Showdown 1896", membership="PS_PLUS"),
                  bought("E3", "Some Pre-Order", preorder=True)],
    "played": [played("PPSA1", "Evil West", "PT4H30M"), played("PPSA2", "Far Game", "PT1H", service="ps_plus"),
               played("PPSA3", "Elden Ring", "PT200H", service="other"),          # a disc
               played("PPSA4", "Split Fiction", "PT2H", service="none(purchased)")],
    "trophies": [trophies("NPWR1", "Evil West", 50, 10, 20)],
}


class Import(unittest.TestCase):
    def setUp(self):
        self.db = store.connect(Path(":memory:"))
        psn.save(self.db, RAW, "2026-10-09T06:30:00")

    def test_durations(self):
        self.assertEqual(psn.minutes("PT12H34M56S"), 754)
        self.assertEqual(psn.minutes("P1DT2H"), 1560)
        self.assertIsNone(psn.minutes(None))

    def test_owned_claimed_and_discs(self):
        lib = psn.load(self.db, {"playstation": {"discs": ["Demon's Souls"]}})
        # not the pre-order, not the PS Plus play; the played disc and Sony's "none(purchased)" count
        self.assertEqual(set(lib["games"]), {"evil west", "demon s souls", "elden ring", "split fiction"})
        self.assertEqual(lib["games"]["elden ring"]["where"], "PS disc")
        self.assertEqual(lib["games"]["evil west"], {"name": "Evil West", "where": "PlayStation", "played_h": 4.5,
                                                     "ach_done": 10, "ach_total": 20})
        self.assertEqual(lib["games"]["demon s souls"]["where"], "PS disc")
        self.assertEqual(lib["claimed"], ["Hunt: Showdown 1896"])

    def test_history_only_on_change(self):
        psn.save(self.db, RAW, "2026-10-10T06:30:00")
        more = dict(RAW, played=[played("PPSA1", "Evil West", "PT6H")] + RAW["played"][1:])
        psn.save(self.db, more, "2026-10-11T06:30:00")
        rows = self.db.execute("SELECT sync_id, id, play_minutes FROM psn_history WHERE kind = 'played'"
                               " AND id = 'PPSA1' ORDER BY sync_id").fetchall()
        self.assertEqual(rows, [(1, "PPSA1", 270), (3, "PPSA1", 360)])


class Ownership(unittest.TestCase):
    def setUp(self):
        db = store.connect(Path(":memory:"))
        psn.save(db, RAW, "2026-10-09T06:30:00")
        self.lib = psn.load(db, {"playstation": {"discs": ["Grand Theft Auto V"]}})

    def test_playstation_copy_counts_as_owned_for_game_pass(self):
        d = assemble(CFG, sheet.parse(TABS, "2026-10-09T08:46:00"), FORECAST, {"games": {}}, TODAY, TODAY, None, self.lib)
        ew = [r for r in d["confirmed"] if r["game"] == "Evil West"][0]
        self.assertEqual(ew["verdict"], "Owned on PlayStation")
        self.assertIn("10/20 trophies", ew["progress"])
        self.assertTrue(d["summary"]["takeaway"].startswith("8 games leave Oct 15 and you own 1 of them on PlayStation."))

    def test_one_service_list_skips_owned_and_claimed(self):
        d = assemble(CFG_PS, sheet.parse(TABS, "2026-10-09T08:46:00"), FORECAST, {"games": {}}, TODAY, TODAY,
                     ps_input(), self.lib)
        names = {(r["game"], r["service"].split(" ")[0]) for r in d["one_service"]["rows"]}
        self.assertNotIn(("Evil West", "PS"), names)            # bought on PSN
        self.assertNotIn(("Grand Theft Auto V", "PS"), names)   # on disc
        self.assertNotIn(("Hunt: Showdown 1896", "PS"), names)  # already claimed
        self.assertEqual(d["one_service"]["skipped_claimed"], 1)


if __name__ == "__main__":
    unittest.main()
