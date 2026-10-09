import unittest
from datetime import date

from harbinger import load_config, model

CFG = load_config(local=None)
DPM = CFG["sheet"]["days_per_month"]
PLAY = CFG["play"]


class Waves(unittest.TestCase):
    def test_waves_are_15th_and_month_end(self):
        self.assertEqual(model.next_waves(date(2026, 10, 9), 4),
                         [date(2026, 10, 15), date(2026, 10, 31), date(2026, 11, 15), date(2026, 11, 30)])

    def test_wave_day_counts_as_upcoming(self):
        self.assertEqual(model.next_waves(date(2026, 10, 15), 1), [date(2026, 10, 15)])

    def test_february_end(self):
        self.assertIn(date(2027, 2, 28), model.next_waves(date(2027, 2, 16), 2))

    def test_nearest_wave(self):
        self.assertEqual(model.nearest_wave(date(2026, 10, 17)), date(2026, 10, 15))
        self.assertEqual(model.nearest_wave(date(2026, 10, 25)), date(2026, 10, 31))
        self.assertEqual(model.nearest_wave(date(2026, 11, 2)), date(2026, 10, 31))

    def test_tie_goes_to_earlier_wave(self):
        # Oct 23 is 8 days after Oct 15 and 8 days before Oct 31
        self.assertEqual(model.nearest_wave(date(2026, 10, 23)), date(2026, 10, 15))

    def test_notice_is_13_days_before(self):
        self.assertEqual(model.notice_date(date(2026, 10, 15), 13), date(2026, 10, 2))


class Anniversaries(unittest.TestCase):
    def test_add_date_from_months(self):
        # Pacific Drive: 11.73 months on service on Oct 9, 2026
        self.assertEqual(model.add_date(date(2026, 10, 9), 11.73, DPM), date(2025, 10, 17))

    def test_pacific_drive_12_month_wave(self):
        added = model.add_date(date(2026, 10, 9), 11.73, DPM)
        self.assertEqual(model.next_checkpoint(added, date(2026, 10, 9), [12, 18, 24, 36], DPM),
                         (12, date(2026, 10, 15)))

    def test_never_a_past_wave(self):
        added = date(2025, 9, 1)  # 12-month wave was Aug 31, 2026
        n, wave = model.next_checkpoint(added, date(2026, 10, 9), [12, 18, 24, 36], DPM)
        self.assertEqual(n, 18)
        self.assertGreaterEqual(wave, date(2026, 10, 9))

    def test_announced_wave_counts_as_survived(self):
        added = model.add_date(date(2026, 10, 9), 11.73, DPM)
        announced = {date(2026, 10, 15)}
        n, wave = model.next_checkpoint(added, date(2026, 10, 9), [12, 18, 24, 36], DPM, announced)
        self.assertEqual(n, 18)
        self.assertEqual(model.last_checkpoint(added, date(2026, 10, 9), [12, 18, 24, 36], DPM, announced)[0], 12)

    def test_past_36_months_has_no_checkpoint(self):
        self.assertIsNone(model.next_checkpoint(date(2022, 1, 1), date(2026, 10, 9), [12, 18, 24, 36], DPM))


class Odds(unittest.TestCase):
    def test_no_signals_returns_base(self):
        self.assertAlmostEqual(model.leave_probability(0.38, []), 0.38)

    def test_forecast_listed_12_month_is_about_53(self):
        p = model.leave_probability(CFG["base_rates"]["12"], [CFG["multipliers"]["forecast_listed"]])
        self.assertAlmostEqual(p, 0.53, delta=0.01)

    def test_bands(self):
        b = CFG["bands"]
        self.assertEqual(model.band(0.45, b), "Likely")
        self.assertEqual(model.band(0.44, b), "Possible")
        self.assertEqual(model.band(0.25, b), "Possible")
        self.assertEqual(model.band(0.249, b), "Thin")

    def test_signals(self):
        fc = {"covers": {"2026-10"}, "listed": {"a": {"month": "2026-10", "unlikely": False},
                                                "b": {"month": "2026-10", "unlikely": True}}}
        wave = date(2026, 10, 31)
        no_prem = {"on": False, "readd": False}
        self.assertEqual([m for m, _ in model.signals(12, wave, "a", fc, no_prem, CFG)], [CFG["multipliers"]["forecast_listed"]])
        self.assertEqual([m for m, _ in model.signals(12, wave, "b", fc, no_prem, CFG)], [CFG["multipliers"]["forecast_unlikely"]])
        self.assertEqual([m for m, _ in model.signals(12, wave, "c", fc, no_prem, CFG)], [CFG["multipliers"]["forecast_absent"]])
        # a month with no forecast yet changes nothing
        self.assertEqual(model.signals(12, date(2026, 11, 15), "c", fc, no_prem, CFG), [])
        prem = [m for m, _ in model.signals(12, date(2026, 11, 15), "c", fc, {"on": True, "readd": True}, CFG)]
        self.assertEqual(prem, [CFG["multipliers"]["premium_readd"]])


    def test_forecast_counts_for_anniversary_month(self):
        # Nov 3 anniversary -> Oct 31 wave; Pure Xbox lists it under November
        fc = {"covers": {"2026-10", "2026-11"}, "listed": {"a": {"month": "2026-11", "unlikely": False}}}
        sig = model.signals(12, date(2026, 10, 31), "a", fc, {"on": False, "readd": False}, CFG, date(2026, 11, 3))
        self.assertEqual([m for m, _ in sig], [CFG["multipliers"]["forecast_listed"]])


class Resolve(unittest.TestCase):
    KEYS = ["clover pit", "keeper 2025", "sopa tale of the stolen potato", "total chaos 2025",
            "halo infinite", "halo wars 2"]

    def test_variants(self):
        from harbinger.sheet import resolve
        self.assertEqual(resolve("CloverPit", self.KEYS), "clover pit")
        self.assertEqual(resolve("Keeper", self.KEYS), "keeper 2025")
        self.assertEqual(resolve("Sopa", self.KEYS), "sopa tale of the stolen potato")
        self.assertEqual(resolve("Total Chaos", self.KEYS), "total chaos 2025")

    def test_ambiguous_prefix_is_none(self):
        from harbinger.sheet import resolve
        self.assertIsNone(resolve("Halo", self.KEYS))


class Play(unittest.TestCase):
    TODAY, WAVE = date(2026, 10, 9), date(2026, 10, 15)

    def test_hours_available(self):
        self.assertAlmostEqual(model.hours_available(self.TODAY, self.WAVE, 9), 7.714, places=2)

    def test_verdicts_for_oct_15(self):
        avail = model.hours_available(self.TODAY, self.WAVE, 9)
        got = {h: model.verdict(h, avail, PLAY) for h in (2, 6, 7, 11, 26)}
        self.assertEqual(got, {2: "Doable", 6: "Tight", 7: "Tight", 11: "Too late for 100%", 26: "Too late for 100%"})
        self.assertEqual(model.verdict(None, avail, PLAY), "Hours unknown")

    def test_start_by(self):
        # 20 h -> 3 weeks of play + 2 buffer
        self.assertEqual(model.start_by(date(2026, 11, 30), 20, PLAY), date(2026, 10, 26))

    def test_urgency(self):
        today = self.TODAY
        self.assertEqual(model.urgency(today, date(2026, 10, 15), 20, PLAY), "Too late")
        self.assertEqual(model.urgency(today, date(2026, 10, 31), 11, PLAY), "Start now")
        self.assertEqual(model.urgency(today, date(2026, 11, 30), 20, PLAY), "Start within 4 wks")
        self.assertEqual(model.urgency(today, date(2027, 3, 31), 20, PLAY), "Comfortable")
        self.assertEqual(model.urgency(today, date(2026, 10, 31), None, PLAY), "Hours unknown")

    def test_queue_stage(self):
        # 20 h before Nov 30: start by Oct 26, so the 14-day heads-up opens Oct 12
        wave = date(2026, 11, 30)
        stage = lambda d, h=20: model.queue_stage(d, wave, h, PLAY, 14)
        self.assertIsNone(stage(date(2026, 10, 11)))
        self.assertEqual(stage(date(2026, 10, 12)), "heads_up")
        self.assertEqual(stage(date(2026, 10, 25)), "heads_up")
        self.assertEqual(stage(date(2026, 10, 26)), "start")
        self.assertEqual(stage(date(2026, 12, 1)), "start")
        # unknown hours: start-by is the 2-week buffer alone (Nov 16), heads-up from Nov 2
        self.assertIsNone(stage(date(2026, 11, 1), None))
        self.assertEqual(stage(date(2026, 11, 2), None), "heads_up")

    def test_remaining_hours(self):
        self.assertEqual(model.remaining_hours(20, 5, None), 15)
        self.assertEqual(model.remaining_hours(20, 5, 0.5), 10)
        self.assertEqual(model.remaining_hours(20, 30, None), 0)
        self.assertIsNone(model.remaining_hours(None, 5, 0.5))


if __name__ == "__main__":
    unittest.main()
