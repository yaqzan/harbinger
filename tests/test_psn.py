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
                  bought("E3", "Some Pre-Order", preorder=True), bought("E4", "Spotify"), bought("E5", "YouTube"),
                  bought("E6", "Kena: Bridge of Spirits Soundtrack"), bought("E7", "NBA LIVE 16 DEMO"),
                  bought("E8", "Call of Duty: Black Ops III Multiplayer Beta")],
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
                                                     "ach_done": 10, "ach_total": 20, "share": 0.5, "hard": ""})
        self.assertEqual(lib["games"]["demon s souls"]["where"], "PS disc")
        self.assertEqual(lib["claimed"], ["Hunt: Showdown 1896"])

    def test_apps_and_non_games_never_land(self):
        names = {n for (n,) in self.db.execute("SELECT name FROM psn_game")}
        self.assertFalse(names & {"Spotify", "YouTube", "Kena: Bridge of Spirits Soundtrack", "NBA LIVE 16 DEMO",
                                  "Call of Duty: Black Ops III Multiplayer Beta"})
        self.assertTrue(psn.is_game("Alphabet Soup"))                # "beta" inside a word is fine
        self.assertTrue(psn.is_game("Demon's Souls"))

    def test_trophy_detail_and_hard_flag(self):
        trophies = [{"trophyId": 1, "trophyName": "Start", "trophyType": "bronze", "earned": True,
                     "earnedDateTime": "2026-05-07T17:25:46Z", "trophyEarnedRate": "63.9", "trophyRare": 3},
                    {"trophyId": 2, "trophyName": "Flawless", "trophyType": "gold", "earned": False,
                     "trophyEarnedRate": "0.8", "trophyRare": 0},
                    {"trophyId": 3, "trophyName": "Online 1000", "trophyType": "gold", "earned": False,
                     "trophyEarnedRate": "1.5", "trophyRare": 0}]
        psn.save_detail(self.db, "NPWR1", trophies, "2026-10-01T00:00:00Z")
        row = self.db.execute("SELECT name, earned, earned_at, rate FROM psn_trophy_detail WHERE trophy_id = 1").fetchone()
        self.assertEqual(row, ("Start", 1, "2026-05-07T17:25:46Z", 63.9))
        lib = psn.load(self.db, {"playstation": {"hard_trophy_rate": 2.0}})
        self.assertEqual(lib["games"]["evil west"]["hard"], "2 trophies left that fewer than 2% of players have")
        # fetched for this list version: not fetched again until the list changes
        todo = self.db.execute("SELECT COUNT(*) FROM psn_trophy WHERE detail_for IS NULL"
                               " OR detail_for != COALESCE(last_updated, '')").fetchone()[0]
        self.assertEqual(todo, 0)

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
        backups = {r["game"]: r["backup"] for r in d["one_service"]["backups"] if r["service"].startswith("PS")}
        self.assertEqual(backups.get("Grand Theft Auto V"), "Owned on PlayStation")

    def test_played_ps_plus_game_shows_progress_and_fewer_hours(self):
        lib = dict(self.lib, playing={"grand theft auto v": {"name": "Grand Theft Auto V", "played_h": 8.0,
                                                              "share": 0.25, "hard": "", "ach_done": 10, "ach_total": 70}})
        lib["games"] = {}  # not owned: played through PS Plus
        d = assemble(CFG_PS, sheet.parse(TABS, "2026-10-09T08:46:00"), FORECAST, {"games": {}}, TODAY, TODAY,
                     ps_input(), lib)
        gta = [r for r in d["one_service"]["rows"] if r["game"] == "Grand Theft Auto V"][0]
        self.assertEqual(gta["hours"], 24.0)   # 32 h to 100%, a quarter of the trophies done
        self.assertEqual(gta["progress"], "8 h played, 25% of trophies")

    def test_a_finished_game_drops_off(self):
        lib = dict(self.lib, playing={"grand theft auto v": {"name": "Grand Theft Auto V", "played_h": 90.0,
                                                              "share": 1.0, "hard": "", "ach_done": 70, "ach_total": 70}})
        lib["games"] = {}
        d = assemble(CFG_PS, sheet.parse(TABS, "2026-10-09T08:46:00"), FORECAST, {"games": {}}, TODAY, TODAY,
                     ps_input(), lib)
        self.assertNotIn("Grand Theft Auto V", [r["game"] for r in d["one_service"]["rows"]])
        self.assertEqual(d["one_service"]["skipped_finished"], 1)


class FakePharos:
    def __init__(self):
        self.sent = []

    def send(self, title, message, **kw):
        self.sent.append((title, message, kw["channel"]))
        return type("R", (), {"status": "sent"})()

    delivered = staticmethod(lambda status: status == "sent")
    ago = staticmethod(lambda when, now=None: f"{(now - when).days} days ago")
    span = staticmethod(lambda secs: f"{round(secs / 86400)} days")


class ExpiryAlert(unittest.TestCase):
    def setUp(self):
        import tempfile
        from unittest import mock
        self.dir = tempfile.TemporaryDirectory()
        patch = mock.patch.object(psn, "ALERT_FILE", Path(self.dir.name) / "psn_alert.json")
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.dir.cleanup)
        self.ph = FakePharos()

    def test_once_on_expiry_quiet_after_once_on_recovery(self):
        from datetime import datetime
        day = lambda d: datetime(2026, 12, d, 6, 30)
        last = "2026-12-01T06:30:00"
        self.assertEqual(psn.alert("auth", last, self.ph, day(2)), "PSN alert sent")
        self.assertIsNone(psn.alert("auth", last, self.ph, day(3)))      # latched: no daily repeats
        self.assertIsNone(psn.alert("error", last, self.ph, day(4)))     # a network blip never pushes
        self.assertEqual(psn.alert("ok", last, self.ph, day(5)), "PSN recovery sent")
        self.assertIsNone(psn.alert("ok", last, self.ph, day(6)))
        self.assertEqual(self.ph.sent, [
            ("❌ PlayStation sign-in expired", "library last synced 1 days ago · needs a new sign-in token", "ops"),
            ("✅ PlayStation sign-in back", "Library syncing again · expired for 3 days", "ops")])

    def test_no_push_when_never_alerted(self):
        self.assertIsNone(psn.alert("ok", None, self.ph))
        self.assertEqual(self.ph.sent, [])


if __name__ == "__main__":
    unittest.main()
