"""The leave model: removal waves, anniversaries, odds, bands and play-time verdicts.

Pure functions over dates and numbers. No I/O, so every rule here is unit-tested
(tests/test_model.py). Numbers come from config.toml, passed in as `cfg`.
"""

from __future__ import annotations

import calendar
import math
from datetime import date, timedelta

# ── removal waves ─────────────────────────────────────────────────────────
# Game Pass ("xbox"): the 15th and the last day of each month.
# PS Plus ("playstation"): the third Monday of each month (308 of 351 removals since 2024).


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    m = year * 12 + (month - 1) + delta
    return m // 12, m % 12 + 1


def third_monday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(7 - first.weekday()) % 7 + 14)


def month_waves(year: int, month: int, cal: str = "xbox") -> list[date]:
    if cal == "playstation":
        return [third_monday(year, month)]
    return [date(year, month, 15), month_end(year, month)]


def waves_near(d: date, cal: str = "xbox") -> list[date]:
    """Every wave of last month, this month and next month, sorted."""
    out = []
    for delta in (-1, 0, 1):
        y, m = _shift_month(d.year, d.month, delta)
        out += month_waves(y, m, cal)
    return sorted(out)


def nearest_wave(d: date, cal: str = "xbox") -> date:
    """The wave closest to `d`. A tie goes to the earlier wave."""
    return min(waves_near(d, cal), key=lambda w: (abs((w - d).days), w))


def next_waves(today: date, n: int, cal: str = "xbox") -> list[date]:
    """The next `n` waves on or after `today`."""
    out: list[date] = []
    y, m = today.year, today.month
    while len(out) < n:
        for w in month_waves(y, m, cal):
            if w >= today and len(out) < n:
                out.append(w)
        y, m = _shift_month(y, m, 1)
    return out


def first_wave_in_month(year: int, month: int, today: date, cal: str = "xbox") -> date | None:
    """The first wave of that month that hasn't happened yet (None if all passed)."""
    for w in month_waves(year, month, cal):
        if w >= today:
            return w
    return None


def notice_date(wave: date, notice_days: int) -> date:
    return wave - timedelta(days=notice_days)


# ── anniversaries ─────────────────────────────────────────────────────────


def add_date(as_of: date, months_on_service: float, days_per_month: float) -> date:
    """The sheet's dates are month-only; its Months column pins the day."""
    return as_of - timedelta(days=round(months_on_service * days_per_month))


def anniversary(added: date, months: int, days_per_month: float) -> date:
    return added + timedelta(days=round(months * days_per_month))


def checkpoints(added: date, cohorts, days_per_month: float, cal: str = "xbox") -> list[tuple[int, date]]:
    """(cohort months, candidate wave) for every anniversary, oldest first."""
    return [(n, nearest_wave(anniversary(added, n, days_per_month), cal)) for n in cohorts]


def next_checkpoint(added: date, today: date, cohorts, days_per_month: float, announced=frozenset(),
                    cal: str = "xbox"):
    """The first checkpoint still open, or None. Never a past date.

    A wave in `announced` already has its official leaving list: a game it didn't
    name survived that checkpoint, so it moves on to the next one.
    """
    for n, wave in checkpoints(added, cohorts, days_per_month, cal):
        if wave >= today and wave not in announced:
            return n, wave
    return None


def last_checkpoint(added: date, today: date, cohorts, days_per_month: float, announced=frozenset(),
                    cal: str = "xbox"):
    """The most recent checkpoint already survived (wave passed or announced without it)."""
    passed = [(n, w) for n, w in checkpoints(added, cohorts, days_per_month, cal) if w < today or w in announced]
    return passed[-1] if passed else None


# ── odds ──────────────────────────────────────────────────────────────────


def to_odds(p: float) -> float:
    return p / (1 - p)


def to_prob(odds: float) -> float:
    return odds / (1 + odds)


def leave_probability(base: float, multipliers) -> float:
    """Base rate converted to odds, multiplied by each signal, converted back."""
    odds = to_odds(base)
    for m in multipliers:
        odds *= m
    return to_prob(odds)


def band(p: float, bands_cfg: dict) -> str:
    if p >= bands_cfg["likely"]:
        return "Likely"
    if p >= bands_cfg["possible"]:
        return "Possible"
    return "Thin"


def signals(cohort: int, wave: date, game: str, forecast: dict, premium: dict, cfg: dict,
            anniv: date | None = None):
    """The multipliers that apply, each with a short reason for the Why column.

    Pure Xbox files a game under its anniversary month, which can differ from its wave
    month (a Nov 3 anniversary goes on Oct 31), so a listing for either month counts.

    forecast: {"covers": {"YYYY-MM", ...}, "listed": {norm_name: {"month", "unlikely"}}}
    premium:  {"on": bool, "readd": bool}
    """
    mult = cfg["multipliers"]
    out = []
    months = {f"{d.year:04d}-{d.month:02d}" for d in (wave, anniv) if d}
    hit = forecast.get("listed", {}).get(game)
    if hit and hit.get("month") in months:
        if hit.get("unlikely"):
            out.append((mult["forecast_unlikely"], "forecast lists it, flagged unlikely"))
        else:
            out.append((mult["forecast_listed"], "on the Pure Xbox forecast"))
    elif months <= set(forecast.get("covers", ())):
        out.append((mult["forecast_absent"], "not on that month's forecast"))
    if premium.get("readd"):
        out.append((mult["premium_readd"], "re-added to Premium"))
    elif premium.get("on"):
        out.append((mult["on_premium"], "also in Premium"))
    return out


# ── play time ─────────────────────────────────────────────────────────────


def hours_available(today: date, wave: date, hours_per_week: float) -> float:
    return max(0, (wave - today).days) / 7 * hours_per_week


def verdict(hours: float | None, available: float, play_cfg: dict) -> str:
    if hours is None:
        return "Hours unknown"
    if hours <= available * play_cfg["doable_share"]:
        return "Doable"
    if hours <= available:
        return "Tight"
    return "Too late for 100%"


def start_by(wave: date, hours: float, play_cfg: dict) -> date:
    weeks = math.ceil(hours / play_cfg["hours_per_week"]) + play_cfg["buffer_weeks"]
    return wave - timedelta(weeks=weeks)


def urgency(today: date, wave: date, hours: float | None, play_cfg: dict) -> str:
    if hours is None:
        return "Hours unknown"
    if hours > hours_available(today, wave, play_cfg["hours_per_week"]):
        return "Too late"
    sb = start_by(wave, hours, play_cfg)
    if sb <= today:
        return "Start now"
    if sb <= today + timedelta(weeks=play_cfg["soon_weeks"]):
        return "Start within 4 wks"
    return "Comfortable"


def queue_stage(today: date, wave: date, hours: float | None, play_cfg: dict, lead_days: int) -> str | None:
    """Which push a queued game is due: "heads_up" from lead_days before its start-by date,
    "start" from the start-by date on, None before that. Unknown hours count as 0 (start-by is
    then just the buffer before the wave)."""
    sb = start_by(wave, hours or 0, play_cfg)
    if today >= sb:
        return "start"
    if today >= sb - timedelta(days=lead_days):
        return "heads_up"
    return None


def remaining_hours(hours: float | None, played_h: float | None, ach_share: float | None):
    """Hours left to 100%, using real progress when there is any.

    Achievement share is the better signal (it tracks 100%); playtime is the fallback.
    """
    if hours is None:
        return None
    if ach_share is not None:
        return round(hours * (1 - ach_share), 1)
    if played_h:
        return round(max(0.0, hours - played_h), 1)
    return hours
