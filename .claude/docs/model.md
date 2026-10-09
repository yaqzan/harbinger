# The leave model

Ported from a claude.ai dashboard prototype and its scheduled brief, both retired 2026-10-09. Rules in `harbinger/model.py`,
numbers in `harbinger/config.toml`, assembly in `harbinger/build.py`.

## Inputs

- **Sheet**: u/ABattleVet's "XBOX Game Pass Master List", read through the public CSV export
  (`/gviz/tq?tqx=out:csv&gid=<gid>`). **Use gids, not tab names**: an unknown tab name silently
  returns the first tab. Master List cols: A Game, B System, D Status, E Added, F Removed,
  G Months (fractional, live), K Completion hours, N Owner Notes, R Premium status, S Premium added.
  Dates are month-only; `add = as_of - Months * 30.4375 days` pins the day.
- **Exclusions**: "Xbox Game Studios" tab (Microsoft, Bethesda, Activision Blizzard) and the
  "EA Play" tab, plus Owner Notes markers for EA Play and Retro Classics. Ubisoft+ Classics
  (Owner Notes "Ubisoft games joining with price increase", ~50 games added Oct 1, 2025) are
  listed separately and never scored.
- **Forecast** (`forecast.py`): subagent reads Pure Xbox's monthly "might be leaving" articles and
  the official notice. Output `covers` (months with a forecast), `listed` (with `unlikely` flag),
  `confirmed` (with wave date), `sources`.
- **Titles across sources** go through `sheet.resolve()`: exact, then space-insensitive
  ("CloverPit"), then trailing year dropped ("Keeper (2025)"), then a UNIQUE word prefix
  ("Sopa"). Ambiguous prefixes resolve to nothing on purpose.

## Rules

- Waves: the 15th and the last day of each month. Candidate wave = nearest wave to the 12/18/24/36
  month anniversary, ties to the earlier wave. Notice ~13 days before.
- Odds: base rate by cohort -> odds -> multiply signals -> probability.
  - Forecast listing x1.77 (tuned to ~52% on the prototype's 38% base, ~53% now; spec said "~2.0").
    Pure Xbox files a game by ANNIVERSARY month, which can differ from the wave month (a Nov 3
    anniversary leaves Oct 31), so a listing for either month counts.
  - Flagged unlikely x0.45. Absent from a forecast that covers the month(s) x0.5. A month with no
    forecast yet changes nothing.
  - Premium x0.8; re-added to Premium 2+ months after Ultimate (a fresh deal) x0.6 instead.
    These two values were a judgment call (spec only said "lowers it").
- Bands: Likely >= 45%, Possible 25-44%, Thin < 25%.
- Announced wave: once a wave has verified confirmed leavers, unnamed games on that wave survived
  it and move to their next checkpoint (and into "Passed a checkpoint quietly").
- Play: 9 h/week. Verdict for confirmed games: Doable <= 75% of available hours, Tight <= 100%,
  else Too late for 100%. Start by = wave - ceil(hours/9) weeks - 2 weeks. Urgency: Too late (hours
  don't fit even starting today) / Start now (start-by reached) / Start within 4 wks / Comfortable /
  Hours unknown.
- Steam: an owned game leaves the confirmed verdicts, the watchlist and the KPIs and shows under
  "You own these elsewhere". Remaining hours = hours x (1 - achievement share), else hours - playtime.

## Calibration (shown on the page)

`calibration_rows()` measures leave rates from the sheet: of third-party games that resolved a
cohort, the share removed within +/-1 month of it. As of 2026-10-09 this gives 12-mo 48%
(1032 games), 2025 adds 39%, 18-mo 19%, 24-mo 33%, 36-mo 13%. The prototype's figures
(12-mo 38% over 312 games, 31% for 2025 adds) used a different sample.

**Base rates (decided 2026-10-09, option C):** 12-mo uses the 2025-adds rate (39%) because
recent deals set current contract lengths; 18/24/36 use the all-history measurement (19/33/13%).
Re-measure and update config.toml by hand; the page's calibration table shows when they drift.

## Snapshots

Every run writes `runs` + `scores` rows to `state/harbinger.sqlite`. The watchlist's small
delta compares with the previous INGEST (a Steam or build run re-scores the same inputs, so it
compares with the ingest before the latest one).

## Known gaps

- Games past 36 months have no checkpoint (A Plague Tale: Requiem left at ~48 months).
- Completion hours are the sheet's, unverified. TrueAchievements/HLTB enrichment is a later ticket.
