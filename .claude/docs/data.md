# Data: the database, the imports, title matching

Everything Harbinger knows lives in `harbinger/state/harbinger.sqlite` (gitignored). Build reads
only the database (plus `forecast.json`). Schemas live with their module: `sheet.SCHEMA`,
`steam.SCHEMA`, `titles.SCHEMA`, snapshots in `store.SCHEMA`. `store.connect()` creates them all.

## Sheet import (`sheet.py`, every ingest)

Two sheets by the same author, same layout, one `service` column apart: `xbox` (Game Pass,
`[sheet] id`) and `playstation` (PS Plus, `[playstation] sheet_id`, added 2026-10-09). Each import
replaces only its own service's rows. PS tabs imported: Master List, Leaving Soon, Removed,
Likely Leaving (the rest are filtered views); its Tier column (Essential / Extra / Extra
(Ubisoft+ Classics) / Premium (Classics|Streaming Only|Remasters|VR) / discontinued PS Now and
old PS Plus) and User score, Streaming, Local Multiplayer land in `tier`, `user_score`,
`streaming`, `local_multiplayer`. The sheet tables from before (no `service` column) were dropped
and re-imported on 2026-10-09 (`sheet.migrate`), so the change log starts again there.

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
- The database imports PC rows too; `sheet.parse()` applies `[scope]` when build loads it.
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

## PlayStation library (`psn.py`, every ingest and the daily job)

- Stdlib port of psn-api's calls (auth flow, client id and the purchased-games GraphQL hash
  copied from its source 2026-10-09): NPSSO -> access code -> tokens, cached in
  `state/psn_tokens.json`. The refresh token lasts ~10 days and refreshing does not extend it
  (measured 2026-10-09), so the code re-signs in with the NPSSO by itself every ~10 days. Only the
  NPSSO (`PSN_NPSSO` env var or `[playstation] npsso`, ~2 months, unverified) needs the owner; no
  code can renew it. No NPSSO and no cached token = PSN skipped quietly.
- Expiry alert (`psn.alert`): a refused sign-in pushes once on Pharos `ops` ("PlayStation sign-in
  expired"), latched in `state/psn_alert.json`; the first good sync after pushes the recovery with
  how long it was down. Network/API errors never push.
- Media apps (`psn.MEDIA_APPS`: Spotify, YouTube, Crunchyroll, Media Player, ...) and non-games
  (soundtrack, demo, beta, playtest) are never imported (8 on the owner's account, 2026-10-09).
- `psn_trophy_detail`: every trophy (name, grade, earned + date, rarity % of players, Sony's
  rarity tier). Fetched only for lists whose `last_updated` moved since `psn_trophy.detail_for`
  (up to 120 lists a run, 2 calls each, 0.2 s apart). First fetch: 90 lists, 4,164 trophies, 94 s.
- `psn_game`: purchased (membership NONE = bought, PS_PLUS = claimed through PS Plus) and played
  (playtime, service none / none_purchased / ps_plus). `psn_trophy`: progress and counts per
  trophy list. `psn_history`: playtime / progress moves.
- Owned = bought and not a pre-order, or played with service `none(purchased)` (what Sony sends;
  psn-api documents `none_purchased`), or played with service `other` (discs and bundled games:
  Demon's Souls on disc arrived this way, 2026-10-09), or listed under `[playstation] discs`
  (an unplayed disc is invisible to the API). A PS_PLUS entry is a monthly claim, and counts as owned
  (`where` "PS Plus claim"), when the PS Plus sheet lists it as Essential or old monthly PS Plus
  (any status: the window closes), or lists it nowhere under Extra/Premium (a title the sheet
  spells differently: God of War vs "God of War (2018)", Tomb Raider I-III). An Extra/Premium add
  the sheet knows, still there or lapsed, stays unowned. Only while `[playstation] tier` is set.
  Crash 4, Evil West and Nine Sols showed as unowned until 2026-10-09. A failed sync keeps the last library.

## Cover art (`art.py`, ingest and steam; build only reads the cache)

- `game_art` (one row per sheet key) + files in `state/art/` (name = sha1(key)[:16], shrunk to
  `[art] max_px` when Pillow is installed, else kept as downloaded). Served at `/art/<file>`.
- Source order, every name match exact on `norm()` after dropping "(2020)" / "(Game Preview)":
  Steam library appid, PSN `image_url`, the appid `ratings.py` already found (`steam_rating`), Steam
  store search, Microsoft Store autosuggest; last, the two searches again minus an edition suffix
  (`sheet.strip_edition`; a sequel number is never touched). Steam
  art is `library_600x900.jpg`, else `header.jpg`, else the hashed `header_image` from appdetails
  (newer apps). A sheet title a store spells differently goes in `titles.toml` `[art]`.
- `[art] budget` caps new lookups per run (first fill takes a few daily runs); a miss is retried
  after `retry_days`. `build` never touches the network, it only attaches what is on disk.
- Rows get an `art` path; the board draws it as the row's poster, the Library as its tile (`cover` in `web/harbinger.js`),
  a titled placeholder when missing. `wanted` asks soonest exit first, backups included.

## Library page (`library.py`, `ratings.py`; `/library`)

- `library.rows()` merges everything into one row per game: Game Pass console (Active / Leaving
  Soon), your PS Plus tier's catalogue, Steam owned, PlayStation owned (bought or disc). Flags
  `gp`, `ps` (tier text; "Claimed" = a monthly claim the catalogue lacks), `steam`, `psn`. Same game
  across places is joined with the strict matchers (`cx.match`, `side.pm`), like everywhere else.
  A PS Plus claim is membership, so it sets `ps`, not `psn`. Rows also carry the sheets' `mc`
  (Metacritic), `us` (PlayStation user score), hours, genre, release year, played hours, and
  `gp_leaves` / `ps_leaves` = [wave, band, p] from the one-service list.
- Written to `state/library.json` (compact, with the `play` settings), not into `data.json`: the leaving page doesn't load it. `library.js` repeats the board's halo rules and logo paths from `harbinger.js` (colour = hours you have / needed, glow = odds, solid ring = confirmed, grey = you have it elsewhere); change them in both.
  `assemble()` returns it as `data["library"]`; `run()` pops it out and writes the file.
- `library.annotate()` copies a game's scores, genre and year onto its `one_service` rows (they
  carry `lib`, the library key), so the leaving page's detail sheet shows them without loading
  `library.json`. Ratings fetch order: games that can leave, then your Steam games, then the rest.
- The page's Venn is three sets (Game Pass, PS Plus, Steam); region id = gp*4 + ps*2 + steam, and
  region 0 (outside every circle) is the PlayStation-only purchases. Any mix of regions can be picked.
- **Steam reviews** (`ratings.py`, table `steam_rating`, one row per library key): appid from your
  Steam library, else exact-title Steam store search (same strict rule as art); then the public
  appreviews summary. Owned games first. `[ratings] budget` per ingest, `refresh_days`, a game with
  no Steam app retried after `retry_days`; HTTP trouble ends the run and keeps what's cached.
  Under `min_reviews` (10) a game shows no score. First fill takes a few daily runs.
- **Where each score comes from** (a game's own catalogue row first, then the next): Metacritic =
  Game Pass sheet, PS Plus sheet, any other sheet row for the title (`sheet.scores`: removed games,
  other tiers, Games with Gold), then Steam's store copy (`appdetails` filters=metacritic, only asked
  for games still without one, cached in `steam_rating.metacritic`). PlayStation user score = the PS
  sheet's User score, any row. Steam reviews = appreviews. Nothing else is scraped.
- Cover art for the library comes through the same `art.wanted()` list, after the leaving games, so
  at 150 a run the library waits weeks for a first fill. The 2026-10-10 backfill ran `steam` once with
  the budget lifted (patch `art.settings`): 1,747 coverless library games down to 165, mostly old
  Atari/Antstream titles no store carries. Do the same after a big library jump.

## Title matching (`titles.py`, every run)

`Matcher` resolves a title to a sheet key, rung by rung (`sheet.Index`): exact, compact (no
spaces), year dropped (either side), edition dropped (GOTY, Definitive, Remastered, ...), then for
loose sources a unique prefix that isn't a sequel number, then a typo (similarity >= 0.93). Keys
come from `sheet.norm()`: drops ™/®, folds accents, ø and curly apostrophes, writes roman numerals
as digits.

- **Steam is strict** (no prefix, no fuzzy): a wrong match hides a leaving game as "owned", which
  is worse than a miss. Learned from the first import (2026-10-09): prefix matched "Prince of
  Persia" to The Lost Crown and "Q.U.B.E." to Q.U.B.E. 2.
- Titles that resolve to a PC-only sheet game get method `pc only` (not an issue). The Matcher
  indexes those keys so they can be turned away instead of falling through to a similar console
  title. Scoping out PC took Steam from 477 to 430 matches (47 were PC-only Game Pass games).
- PSN purchases and discs (sources `psn`, `disc`) are matched strictly against both catalogues.
- **Preferred editions** (owner, 2026-10-09; `sheet.PREFERRED`: Remastered, Director's Cut). When a
  title fits several editions the preferred one wins ("Horizon Zero Dawn" -> Remastered), so its
  sheet hours are used. A strict source's plain copy doesn't own a preferred edition (Ghost of
  Tsushima disc, Steam Death Stranding), so the better version stays on the radar; the report
  doesn't list those as near misses. Where a Steam copy already is that edition, alias it in
  `[same]` (Wasteland 2, Cities: Skylines). Changed 7 matches when added.
- **Queue lookup** (`build._find`) falls back past the Matcher (word prefix either way, then a
  close spelling) but never across a sequel number and never to a `[different]` title. Before
  2026-10-09 "The Talos Principle 2" fell back to the 2014 original. An audit of all 771 matches
  then found no other sequel mixups; a year that is the title ("Car Mechanic Simulator 2021") is
  settled in `[different]`.
- Steam tools (public test, beta client, dedicated server, demo...) are never matched.
- `harbinger/titles.toml` (tracked, shared) settles the rest: `[same]` maps a title to a sheet
  title (or a list, for a forecast bundle), `[different]` blocks a match or a suggestion.
  `[first_party] playstation` lists Sony's own PS Plus games (model.md, PS Plus).
- `title_match.target` is the catalogue matched against: `xbox`, or `playstation` (your PS Plus
  tier's games, from Steam and from the Game Pass games). Cross-service matching is strict like
  Steam ("BLACK" prefix-matched Black Desert). An alias aimed at the other catalogue falls
  through and isn't reported missing. Game Pass games absent from PS Plus are normal, not issues.
- `reconcile()` rebuilds `title_match` (one row per outside title: source, key, rung,
  near-miss candidates) each run. `py -3.11 -m harbinger titles` lists loose matches, near
  misses and outside titles not on the sheet. First import: 127 issues, down to 1 (Superball,
  off the sheet on purpose) after the rules above and 50 corrections.
