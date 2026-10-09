# Data: the database, the imports, title matching

Everything Harbinger knows lives in `harbinger/state/harbinger.sqlite` (gitignored). Build reads
only the database (plus `forecast.json`). Schemas live with their module: `sheet.SCHEMA`,
`steam.SCHEMA`, `titles.SCHEMA`, snapshots in `store.SCHEMA`. `store.connect()` creates them all.

## Sheet import (`sheet.py`, every ingest)

- Downloads the whole public workbook as xlsx (`/export?format=xlsx`, ~1.9 MB, no Google login,
  verified 2026-10-09) and reads it with the stdlib (zipfile + ElementTree, no openpyxl).
  The last one is kept at `state/sheet/latest.xlsx`.
- Tabs are picked by **name** (`sheet.TABS`). Each mapped column's header is checked; a moved
  or renamed header raises `SheetLayoutError` and the previous import stays. Fix the spec in
  `TABS`, never loosen the check.
- Imported: Master List, Leaving Soon, Removed, Likely Leaving (the sheet owner's own list),
  Returning Titles, Retro Classics, Game Pass Premium, Game Pass Essential, Xbox Game Studios,
  EA Play, Upcoming. Skipped: Tiers/PC/xCloud/Series X|S/Xbox (filtered views of the Master List),
  Copy of Removed, Suggestions (reader names), Cross Play (no use yet).
- `sheet_row` = the latest import, one row per game per tab per **stint**: 143 Master List titles
  appear twice (left and came back). Stint 1 is the earliest add. Build's `by_key` uses the
  newest stint, so a returning game never reads as "Gone".
- Dates are ISO `YYYY-MM-DD` (xlsx serials are day-exact), `YYYY-MM` when the sheet only gives a
  month ("June 2026" on Upcoming), else the sheet's raw text. Odd text in a number column is kept.
- `sheet_change` logs what changed against the previous import (added / dropped / changed field
  old -> new), keyed by (tab, key, stint). The first import is a baseline and logs nothing.
  `months`/`essential_months` are live formulas and never logged. Old rows are re-keyed with the
  current `norm()` before diffing, so a matching change never shows up as a sheet change.
- Status values seen: Active, Removed, Leaving Soon, Coming Soon, GwG Temporary, GwG Permanent.

## Steam import (`steam.py`, every ingest and the daily job)

- `steam_game`: every app ever seen, with every GetOwnedGames field (playtime total / 2 weeks /
  per platform / Deck / offline, last played, icon, stats flags). `owned = 0` once it leaves the
  library. Achievements are fetched for played games on the page or still on Game Pass; counts
  are kept from the last fetch, never blanked.
- `steam_achievement`: per achievement (apiname, achieved, unlock time).
- `steam_history`: a row only when a game's playtime or achievement count moves (first sync logs
  everything as the baseline).
- A failed sync keeps the database as it was.

## Title matching (`titles.py`, every run)

`Matcher` resolves a title to a sheet key, rung by rung (`sheet.Index`): exact, compact (no
spaces), year dropped (either side), edition dropped (GOTY, Definitive, Remastered, ...), then for
loose sources a unique prefix that isn't a sequel number, then a typo (similarity >= 0.93). Keys
come from `sheet.norm()`: drops ™/®, folds accents, ø and curly apostrophes, writes roman numerals
as digits.

- **Steam is strict** (no prefix, no fuzzy): a wrong match hides a leaving game as "owned", which
  is worse than a miss. Learned from the first import (2026-10-09): prefix matched "Prince of
  Persia" to The Lost Crown and "Q.U.B.E." to Q.U.B.E. 2.
- Steam tools (public test, beta client, dedicated server, demo...) are never matched.
- `harbinger/titles.toml` (tracked, shared) settles the rest: `[same]` maps a title to a sheet
  title (or a list, for a forecast bundle), `[different]` blocks a match or a suggestion.
- `reconcile()` rebuilds `title_match` (one row per outside title: source, key, rung,
  near-miss candidates) each run. `py -3.11 -m harbinger titles` lists loose matches, near
  misses and outside titles not on the sheet. First import: 127 issues, down to 1 (Superball,
  off the sheet on purpose) after the rules above and 50 corrections.
