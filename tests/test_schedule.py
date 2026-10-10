"""Which scheduled ingest ticks do the work (harbinger/schedule.py)."""

import unittest
from datetime import date

from harbinger import load_config
from harbinger.model import next_waves
from harbinger.schedule import ingest_due

WINDOW = load_config(local=None)["waves"]["notice_window"]

# Pure Xbox "games are leaving" articles: (published, Eastern date; wave it announced).
OBSERVED = [
    ("2025-07-01", "2025-07-15"), ("2025-07-15", "2025-07-31"), ("2025-08-02", "2025-08-15"),
    ("2025-09-02", "2025-09-15"), ("2025-10-02", "2025-10-15"), ("2025-10-18", "2025-10-31"),
    ("2025-11-02", "2025-11-15"), ("2025-11-17", "2025-11-30"), ("2025-12-02", "2025-12-15"),
    ("2026-02-16", "2026-02-28"), ("2026-03-02", "2026-03-15"), ("2026-04-02", "2026-04-15"),
    ("2026-04-17", "2026-04-30"), ("2026-05-02", "2026-05-15"), ("2026-05-18", "2026-05-31"),
    ("2026-06-16", "2026-06-30"), ("2026-07-02", "2026-07-15"), ("2026-07-18", "2026-07-31"),
    ("2026-08-03", "2026-08-15"), ("2026-09-01", "2026-09-15"), ("2026-09-15", "2026-09-30"),
    ("2026-10-02", "2026-10-15"),
]


def due(today, announced=(), ran=True):
    return ingest_due(today, next_waves(today, 4), set(announced), ran, WINDOW)[0]


class IngestDue(unittest.TestCase):
    def test_first_tick_of_the_day_always_runs(self):
        self.assertTrue(due(date(2026, 10, 9), ran=False))

    def test_quiet_between_windows(self):
        self.assertFalse(due(date(2026, 10, 9)))  # Oct 15 list is in, Oct 31 is 22 days out

    def test_rechecks_until_the_list_lands(self):
        self.assertTrue(due(date(2026, 10, 17)))  # Oct 31 is 14 days out, no list yet
        self.assertFalse(due(date(2026, 10, 17), announced=[date(2026, 10, 31)]))

    def test_every_observed_list_landed_inside_the_window(self):
        for pub, wave in OBSERVED:
            p, w = date.fromisoformat(pub), date.fromisoformat(wave)
            self.assertTrue(due(p), f"{pub} list for {wave} falls outside notice_window {WINDOW}")


if __name__ == "__main__":
    unittest.main()
