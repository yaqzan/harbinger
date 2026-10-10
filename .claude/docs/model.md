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
- Queue across services (`build.queue_rows`, 2026-10-09): a name is looked up on Game Pass, then
  your PS Plus tier (`PsSide`, shared with the one-service list). A game on both follows the copy
  that is safe for longer: a next wave under `[alerts] min_p` counts as none in sight (Indika's 5%
  Extra copy covers its 34% Game Pass wave), and none in sight beats any date. PS rows use
  `plus.outlook` (third-Monday waves, PS base rates), trophies for hours left; every trophy
  earned counts as beaten. Essential claim deadlines show but never push.
- Owned anywhere (Steam, PSN purchase, PS disc; `Context.owned`, Steam wins a tie) works like
  Steam ownership below; the verdict says where ("Owned on PlayStation"). PlayStation progress uses
  Sony's progress % (weighted by grade), not trophy counts. "N trophies left that fewer than X% of
  players have" (`[playstation] hard_trophy_rate`, 2%) flags a hard 100%.
- PS Plus games you play without owning: their trophy progress / playtime shrink their hours on
  the one-service list; every trophy earned drops them off it ("finished").
- Steam: an owned game leaves the confirmed verdicts, the watchlist and the summary counts, and
  shows dimmed on the page ("Owned on Steam"). Remaining hours = hours x (1 - achievement share), else hours - playtime.

## PS Plus (`plus.py`, since 2026-10-09)

- Tier from `[playstation] tier` (none | essential | extra | premium; each includes the ones
  below). The owner is on Extra (config.local.toml). "none" leaves PlayStation off.
- VR-only games are hidden unless `[playstation] vr = true` (owner, 2026-10-09): the Premium (VR)
  sub-tier plus titles.toml `[vr_only] playstation` (3 Ubisoft+ games on Extra). The sheet tags
  VR-optional games "PS4/PSVR" too (Tetris Effect, Rise of the Tomb Raider), so the system
  column can't decide it; those stay. Hidden games are out of everything PS (catalogue level).
- Waves: the third Monday of the month (308 of 351 removals since 2024; `model.month_waves(cal=
  "playstation")`). Leaving Soon rows carry the exact date. Same cohorts; announced-wave rule too.
- Base rates per tier family, measured 2026-10-09 like Game Pass option C: Extra 35/5/17/3%
  third-party (12-mo from 2024+ adds; all history 25%), Premium Classics/Remasters/VR 5/1/1/0%
  (doesn't reproduce: see the Premium ticket), Streaming Only 0. No forecast signals. Ubisoft+
  Classics not scored.
- **Sony first-party** (owner, 2026-10-09): titles.toml `[first_party] playstation` (108 titles, by
  hand: the sheet has no studio column) get kind "sony", rates 1/2/0/0% (110 games: 1 of 100
  left at 12 mo, 2 of 96 at 18, none later; third-party Extra loses 52% overall, Sony 13%).
  The few removals were flagships pulled before a new entry or edition sold (Spider-Man GOTY
  May 2023, HZD Complete May 2024, Forbidden West Sep 2024), back as the newer edition ~2 years
  on. The row says so instead of a number. Moved HZD Remastered 35% -> 1% (its push went).
  A new Sony game on Extra needs a line in the list, else it's scored as third-party.
- Essential monthly games are claim-to-keep: "Claim by <date>", sorted with the confirmed.

## Only on one service (`build.one_service_rows`)

Games playable through exactly one subscription (Game Pass console, PS Plus at your tier) that
you don't own on Steam. A game on both services drops out when the other copy is a backup; a
copy that is itself leaving (Leaving Soon / confirmed) is no backup, so then it stays. Shown
once, on the Game Pass side, when both are safe. Order: Confirmed and claims, Likely, Possible,
Thin, unscored; soonest first in each. Game Pass odds reach any distance ahead here (the
watchlist stops at the horizon).

`backups` holds the games left out above that still have an exit date, with `backup` saying
where you'd keep playing: "Owned on Steam / PlayStation / PS disc / PS Plus claim", "Also on PS Plus Extra",
"Claimed", "Every trophy earned". The page shows them dimmed (owner, 2026-10-09: an exit you
are covered for should stay visible, greyed, with the alternative named).
`places` lists every library or service you can still play it on (`xbox`, `playstation`, `steam`;
Steam and PSN ownership tracked separately in `Context.owned_on` / `PsSide.owned_on`); the page draws
them as mini logo circles (Simple Icons paths, CC0) in the cover's corner, one per place.

## The page (`web/`, redesigned 2026-10-09)

Two tabs, **Board** (`index.html`) and **Library** (`library.html`). The Shelf view (a column of
cover art per exit date) was dropped 2026-10-10 by the owner; git history has it (before this note).
The Board draws one list (`one_service.rows` + `backups`, plus unverified reports from `confirmed`)
as a metro line (owner's pick 2026-10-10: rows grouped by the last day to start (2026-10-10:
Won't fit, then Start now, then each start-by date; claims on their claim date. The page opens
scrolled to Start now with a "↑ N won't fit" pill at the top edge (`landOnStart`, once per load; the
pill scrolls up). Games with no hours stay off the board (owner, 2026-10-10); research them into
`titles.toml` `[hours]`) on a
vertical line, so a short game due soon and a long one due later sit where they compete for time; each row is a poster carrying the halo, stacked end to end with room for the ring, then
title + platform logo on the first line; the second line leads with the ratings (2026-10-10):
Metacritic (Metacritic's green/yellow/red square) and the audience score (Rotten Tomatoes style: a
navy pill with the Steam logo and the review % in Steam's colours, blue 70%+ / tan 40-69 / rust
below; else the PS logo and the PS user score on the same scale x10), then genre and year. The
remark carries when and how sure: "Leaves Oct 31 · 53% likely" / "· confirmed" (the start-by
group already says how soon), one fit bar of hours needed vs hours left before it leaves, and the remark). Filters: service, odds band (Likely and up by
default), how far ahead (8 weeks by default), two switches for the dimmed games (games you own; games on both services), off by default
(owner, 2026-10-10) and animated: hiding shrinks them out and slides the rest together, showing the
reverse (FLIP over `data-k` keys in `animatedDraw`; skipped under reduced motion). A tile or row opens a detail
sheet. Days left, hours you have, start-by and the fit bar are computed in the browser against
the viewer's today with `data.play` (the `[play]` table), mirroring `model.hours_available`,
`verdict`, `start_by` and `urgency`; change a rule there and in `web/harbinger.js` together.
The cue (owner, 2026-10-10): a halo whose brightness follows the leave odds (full at 60%+), a
solid ring once confirmed (dashed if only reported). Its colour is fit, not odds, from s = hours you have /
hours needed: green at s >= 1.5, a gradient to pure yellow at 1.0 (just enough), then to red at s <= 0.5;
grey for unknown hours and backups. On the board the halo sits on the poster; the stop on the line is a plain fit-colour dot (a
glowing dot couldn't show confirmed vs likely). Remark text takes the fit colour. Every row carries logos: the service it leaves for a live row, where you
have it for a backup. The fit bar uses the same colour; the odds badge is plain and only on modelled
games (2026-10-10: no "Confirmed" badge, no "Owned on" ribbon over the cover; the ring and the logos say it).
Top of the page (owner, 2026-10-10): one **Confirmed exits** panel, the next 3 confirmed date +
service groups side by side with how many you'd lose and how many still fit, plus
`summary.next_notice`. The old day countdown went first, then the "Start soon" list (same day:
the board's Start now group says the same thing); its "In your queue" tag moved onto the board's
facts line. Sync times live under "Runs and sources". `summary.takeaway` is still
built for the CLI and pushes.

**Phones (2026-10-10).** Owner: opening the app must land on the board / the tiles, no scrolling.
Under 640px both pages keep only search + a **Filters** button above the content (`.fbtn`, badge =
filters changed from the default; `.fmore` holds the rest and is `display: contents` on wider screens).
The Board's Confirmed exits become a row of pills (date, service, "lose N"); the panel title, notice
and Updated line hide; the legend shows only with the filters open. The Library hides its title,
meta and Venn; the region chips scroll on one line. First content at 215px (Board) / 182px
(Library) on a 390x844 phone, was 700 / 934. The Board's date heads its group and each row folds to
the poster beside title, facts, then hours and remark (under 380px: "6 of 12 h" and no "Leaves"); tables with `class="stack"` become one block per row, labelled
from `data-label` (copied from the header by the JS that fills them); the detail dialog docks to
the bottom as a sheet. Touch screens (`pointer: coarse`) at any width get 44px controls and
16px inputs (iOS zooms in on anything smaller). Hover effects sit behind `@media (hover: hover)`.
Browser floor is iOS Safari 15.4 / Chrome 105 (`<dialog>`, `:has`); `color-mix()` has a plain
fallback before it. `py -3.11 ops/mobile_check.py [--shots DIR]` is the gate: it loads every
state at 320/360/390/430 px upright and 844 px on its side and fails on sideways scroll, small
inputs or targets, and script errors. Run it after any `web/` change.

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
