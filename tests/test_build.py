"""A whole run pinned to Oct 9, 2026: the sanity check for the first real output."""

import unittest
from datetime import date, datetime
from pathlib import Path

from harbinger import load_config
from harbinger import store
from harbinger.build import alerts_due, assemble, leaver_alert, new_leavers, queue_alert
from harbinger.sheet import FIELDS, norm, parse

CFG = load_config(local=None)
CFG["queue"] = {"gone": ["Frostpunk 2"], "tracking": ["Nine Sols"]}
TODAY = date(2026, 10, 9)
def ym(s):
    return datetime.strptime(s, "%b %Y").strftime("%Y-%m") if s else None


def row(name, status, added, months, hours, removed="", notes="", prem="", prem_added=""):
    """A sheet_row as the import stores it ('Oct 2025' -> '2025-10')."""
    r = {"title": name, "key": norm(name), "stint": 1, **{f: None for f in FIELDS}}
    r.update(system="Xbox / PC", status=status, added=ym(added), removed=ym(removed), months=months,
             completion_h=hours, owner_notes=notes or None, premium_status=prem or None, premium_added=ym(prem_added))
    return r


def title(name):
    return {"title": name, "key": norm(name)}


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
    "master": LEAVING + ACTIVE,
    "leaving_soon": LEAVING,
    "removed": [ACTIVE[-1]],
    "premium": [],
    "first_party": [title("Halo Something")],
    "ea_play": [],
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


class NewLeaverPush(unittest.TestCase):
    def setUp(self):
        self.d = run()
        self.keys = {r["key"] for r in self.d["confirmed"] if r["verified"]}

    def test_only_games_the_last_ingest_did_not_have(self):
        new = new_leavers(self.d["confirmed"], self.keys - {norm("Pacific Drive")})
        self.assertEqual([r["game"] for r in new], ["Pacific Drive"])
        self.assertEqual(new_leavers(self.d["confirmed"], self.keys), [])

    def test_first_ingest_and_unverified_and_owned_stay_quiet(self):
        self.assertEqual(new_leavers(self.d["confirmed"], None), [])
        names = [r["game"] for r in new_leavers(self.d["confirmed"], set())]
        self.assertNotIn("Superball", names)  # only an untrusted outlet reported it
        steam = {"games": {"evil west": {"name": "Evil West", "appid": 2, "played_h": 0,
                                         "ach_done": None, "ach_total": None}}}
        self.assertNotIn("Evil West", [r["game"] for r in new_leavers(run(steam)["confirmed"], set())])

    def test_alert_text(self):
        one = [r for r in self.d["confirmed"] if r["game"] == "Donut County"]
        self.assertEqual(leaver_alert(one, TODAY), ("Donut County confirmed leaving in 6 days",
                                                    "Donut County 2 h, doable"))
        title, body = leaver_alert(new_leavers(self.d["confirmed"], set()), TODAY)
        self.assertEqual(title, "8 games confirmed leaving in 6 days")
        self.assertTrue(body.endswith("+4 more"))
        self.assertNotIn("—", title + body)

    def test_store_reads_the_last_ingest(self):
        db = store.connect(Path(":memory:"))
        self.assertIsNone(store.confirmed_keys(db))
        store.record(db, "ingest", "2026-10-09", "", [{"game": "Evil West", "key": "evil west", "list": "confirmed"},
                                                       {"game": "Far Game", "key": "far game", "list": "watchlist"}])
        store.record(db, "steam", "2026-10-09", "", [{"game": "Donut County", "key": "donut county", "list": "confirmed"}])
        self.assertEqual(store.confirmed_keys(db), {"evil west"})



class QueuePush(unittest.TestCase):
    """Nine Sols (queued): 25 h before its 24-month wave Nov 15 at 33%, so start by Oct 11 and
    the 14-day heads-up opens Sep 27."""

    def setUp(self):
        self.q = run()["queue"]

    def due(self, day, sent=(), skip=frozenset(), cfg=CFG):
        return [(r["game"], r["stage"]) for r in alerts_due(self.q, day, cfg, set(sent), skip)]

    def test_heads_up_two_weeks_before_start_by_then_start(self):
        self.assertEqual(self.due(date(2026, 9, 26)), [])
        self.assertEqual(self.due(date(2026, 9, 27)), [("Nine Sols", "heads_up")])
        self.assertEqual(self.due(date(2026, 10, 11)), [("Nine Sols", "start")])

    def test_each_stage_fires_once(self):
        sent = {("nine sols", "2026-11-15", "heads_up")}
        self.assertEqual(self.due(TODAY, sent), [])
        self.assertEqual(self.due(date(2026, 10, 11), sent), [("Nine Sols", "start")])
        self.assertEqual(self.due(date(2026, 10, 12), sent | {("nine sols", "2026-11-15", "start")}), [])

    def test_store_remembers_what_was_sent(self):
        db = store.connect(Path(":memory:"))
        self.assertEqual(store.alerts_sent(db), set())
        store.mark_alerts(db, alerts_due(self.q, TODAY, CFG, set()))
        self.assertEqual(store.alerts_sent(db), {("nine sols", "2026-11-15", "heads_up")})
        self.assertEqual(alerts_due(self.q, TODAY, CFG, store.alerts_sent(db)), [])

    def test_quiet_when_owned_unlikely_or_already_in_the_leaver_push(self):
        steam = {"games": {"nine sols": {"name": "Nine Sols", "appid": 3, "played_h": 0,
                                         "ach_done": None, "ach_total": None}}}
        self.assertEqual(alerts_due(run(steam)["queue"], TODAY, CFG, set()), [])
        strict = {**CFG, "alerts": {**CFG["alerts"], "min_p": 0.45}}
        self.assertEqual(self.due(TODAY, cfg=strict), [])
        self.assertEqual(self.due(TODAY, skip={"nine sols"}), [])

    def test_confirmed_queued_game(self):
        cfg = {**CFG, "queue": {"gone": [], "tracking": ["Nine Sols", "Pacific Drive"]}}
        q = assemble(cfg, parse(TABS, "2026-10-09T08:46:00"), FORECAST, {"games": {}}, TODAY, TODAY)["queue"]
        due = alerts_due(q, TODAY, cfg, set())
        self.assertEqual([(r["game"], r["stage"]) for r in due], [("Pacific Drive", "start"), ("Nine Sols", "heads_up")])
        self.assertEqual(queue_alert(due[:1], TODAY),
                         ("Start Pacific Drive now", "20 h, too long to finish · leaves Oct 15"))
        self.assertEqual(queue_alert(due, TODAY),
                         ("2 queued games to start soon", "Pacific Drive now · Nine Sols in 2 days"))

    def test_beaten_games_never_push(self):
        cfg = {**CFG, "queue": {**CFG["queue"], "beaten": ["Nine Sols", "Pacific Drive"]}}
        d = assemble(cfg, parse(TABS, "2026-10-09T08:46:00"), FORECAST, {"games": {}}, TODAY, TODAY)
        self.assertEqual(alerts_due(d["queue"], TODAY, cfg, set()), [])
        self.assertIn("beaten", {r["game"]: r for r in d["queue"]}["Nine Sols"]["note"])
        names = [r["game"] for r in new_leavers(d["confirmed"], set(), d["beaten"])]
        self.assertNotIn("Pacific Drive", names)
        self.assertIn("Evil West", names)

    def test_queue_lookup_skips_the_original_for_a_sequel(self):
        tabs = dict(TABS, master=TABS["master"] + [
            row("The Talos Principle", "Removed", "Nov 2019", 12.1, 16, "Nov 2020"),
            row("The Talos Principle 2: Road to Elysium", "Active", "Jan 2026", 8.4, 20)])
        cfg = {**CFG, "titles": {}, "queue": {"gone": [], "tracking": ["The Talos Principle 2"]}}
        q = lambda c: assemble(c, parse(tabs, "2026-10-09T08:46:00"), FORECAST, {"games": {}}, TODAY, TODAY)["queue"][0]
        self.assertEqual(q(cfg)["game"], "The Talos Principle 2: Road to Elysium")
        # ruled out in titles.toml: the fallback must not grab the 2014 original instead (2026-10-09 bug)
        blocked = {**cfg, "titles": {"different": {"The Talos Principle 2": ["The Talos Principle 2: Road to Elysium"]}}}
        self.assertEqual(q(blocked)["state"], "Not found")

    def test_alert_text(self):
        title, body = queue_alert(alerts_due(self.q, TODAY, CFG, set()), TODAY)
        self.assertEqual((title, body), ("Start Nine Sols in 2 days", "25 h · 33% it leaves Nov 15"))
        self.assertNotIn("—", title + body)

if __name__ == "__main__":
    unittest.main()


class Config(unittest.TestCase):
    def test_fresh_clone_watches_nothing(self):
        cfg = load_config(local=None)
        self.assertEqual(cfg["queue"], {"gone": [], "tracking": [], "beaten": []})
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
