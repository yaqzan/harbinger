"""When a scheduled ingest actually runs. Task Scheduler fires `ingest --if-due` several times a
day; this decides which of those ticks do the work.

Microsoft's leaving lists land in a window before each wave (`[waves] notice_window`, measured
from Pure Xbox's publish times), at any hour from early morning to late afternoon Eastern. So:
the first tick of a day always runs, and later ticks run only while a wave sits in its notice
window without its list yet. Once the list is in, the rest of that window goes quiet.
"""

from __future__ import annotations

from datetime import date


def ingest_due(today: date, waves: list[date], announced: set[date], ran_today: bool,
               window: list[int]) -> tuple[bool, str]:
    if not ran_today:
        return True, "first run today"
    lo, hi = window
    for w in waves:
        if lo <= (w - today).days <= hi and w not in announced:
            return True, f"waiting on the {w:%b} {w.day} leaving list"
    return False, "not due: already ran today and no leaving list is expected"
