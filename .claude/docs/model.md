# The leave model

Ported from a claude.ai dashboard prototype and its scheduled brief, both retired 2026-10-09. Rules in `harbinger/model.py`,
numbers in `harbinger/config.toml`, assembly in `harbinger/build.py`.

## Inputs

- **Sheet**: u/ABattleVet's "XBOX Game Pass Master List", imported into `harbinger.sqlite` each
  ingest (see `data.md`). Master List cols: A Game, B System, D Status, E Added, F Removed,
  G Months (fractional, live), K Completion hours, N Owner Notes, R Premium status, S Premium added.
  The import has day-level dates (the old CSV export only showed the month); the model still pins
  the add day as `as_of - Months * 30.4375 days`, now from full-precision Months.
- **Scope: Xbox console Game Pass only** (owner, 2026-10-09). `[scope] skip_systems = ["PC"]`
  drops sheet rows whose System is exactly "PC" (PC Game Pass only) from the model, matching and
  page; "Xbox / PC" stays. A title with a PC row and a console row keeps the console row. A
  forecast or watched title that only exists as PC is turned away ("PC only"), never matched to a
  lookalike. Removing PC moved the measured rates by a point at most (12-mo 47%, 2025 adds 40%).
- **Exclusions**: "Xbox Game Studios" tab (Microsoft, Bethesda, Activision Blizzard) and the
  "EA Play" tab, plus Owner Notes markers for EA Play and Retro Classics. Ubisoft+ Classics
  (Owner Notes "Ubisoft games joining with price increase", ~50 games added Oct 1, 2025) are
  listed separately and never scored.
- **Forecast** (`forecast.py`): subagent reads Pure Xbox's monthly "might be leaving" articles and
  the official notice. Output `covers` (months with a forecast), `listed` (with `unlikely` flag),
  `confirmed` (with wave date), `sources`.
- **Titles across sources** go through `titles.Matcher` (rules and corrections in `data.md`).

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
- Confirmed means a trusted outlet named it (`[waves] trusted_sources`: Xbox Wire, Pure Xbox) or it's
  on the sheet's Leaving Soon tab. Anything only another outlet reports (Insider Gaming's Superball,
  2026-10-09) shows tagged unverified and stays out of the counts. The subagent once labelled an
  Insider Gaming report as confirmed, so this is enforced in code, not only in the prompt.
- Announced wave: once a wave has verified confirmed leavers, unnamed games on that wave survived
  it and move to their next checkpoint (and into "Passed a checkpoint quietly").
- Play: 9 h/week. Verdict for confirmed games: Doable <= 75% of available hours, Tight <= 100%,
  else Too late for 100%. Start by = wave - ceil(hours/9) weeks - 2 weeks. Urgency: Too late (hours
  don't fit even starting today) / Start now (start-by reached) / Start within 4 wks / Comfortable /
  Hours unknown.
- Queue push stage (`queue_stage`): heads-up from `[alerts] lead_days` before start-by, start from
  start-by on. Unknown hours count as 0. Each queued game is judged alone; nothing sequences the
  queue yet, so overlapping windows aren't flagged (Play plan ticket).
- Owned anywhere (Steam, PSN purchase, PS disc; `Context.owned`, Steam wins a tie) works like
  Steam ownership below; the verdict says where ("Owned on PlayStation"). PlayStation progress uses
  Sony's progress % (weighted by grade), not trophy counts. "N trophies left that fewer than X% of
  players have" (`[playstation] hard_trophy_rate`, 2%) flags a hard 100%.
- PS Plus games you play without owning: their trophy progress / playtime shrink their hours on
  the one-service list; every trophy earned drops them off it ("finished").
- Steam: an owned game leaves the confirmed verdicts, the watchlist and the KPIs and shows under
  "You own these elsewhere". Remaining hours = hours x (1 - achievement share), else hours - playtime.

## PS Plus (`plus.py`, since 2026-10-09)

- Tier from `[playstation] tier` (none | essential | extra | premium; each includes the ones
  below). The owner is on Extra (config.local.toml). "none" leaves PlayStation off.
- Waves: the third Monday of the month (308 of 351 removals since 2024; `model.month_waves(cal=
  "playstation")`). Leaving Soon rows carry the exact date. Same cohorts; announced-wave rule too.
- Base rates per tier family, measured 2026-10-09 like Game Pass option C: Extra 35/5/16/2%
  (12-mo from 2024+ adds; all history 24%), Premium Classics/Remasters/VR 5/1/1/0%, Streaming
  Only 0. No forecast signals. Ubisoft+ Classics not scored.
- Essential monthly games are claim-to-keep: "Claim by <date>", sorted with the confirmed.

## Only on one service (`build.one_service_rows`)

Games playable through exactly one subscription (Game Pass console, PS Plus at your tier) that
you don't own on Steam. A game on both services drops out when the other copy is a backup; a
copy that is itself leaving (Leaving Soon / confirmed) is no backup, so then it stays. Shown
once, on the Game Pass side, when both are safe. Order: Confirmed and claims, Likely, Possible,
Thin, unscored; soonest first in each. Game Pass odds reach any distance ahead here (the
watchlist stops at the horizon).

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
