# Ops

Standard machine pattern (GameNight/Arbiter): one port, own tunnel, 5-min watchdog.

- **Server**: `py -3.11 -u -m harbinger serve`, stdlib ThreadingHTTPServer on 127.0.0.1:5006.
  Serves `web/` (`/library` is `library.html`), `/data.json` and `/library.json` (from `harbinger/state/`), `/art/<file>` and `/api/health`. GET/HEAD only,
  everything no-cache, path traversal refused (tested 2026-10-09).
  `/api/health` answers 200 whenever the server is up (the watchdog restarts on anything else);
  `stale: true` means data.json is over 40 h old, i.e. the scheduled jobs are failing.
  web/ and data.json are read per request, but a change to `serve.py` (a new route) needs
  `server.ps1 restart -Service harbinger`: the covers 404'd for hours on 2026-10-09 until it did.
  Cloudflare turns the server's `no-cache` on a 404 (and on web/ files) into `max-age=14400`, so a
  404 sticks in browsers for 4 h; hard refresh doesn't clear images. Fix = change the URL: bump
  `ART_V` in `web/harbinger.js` for covers, `?v=` in `index.html` for the JS/CSS.
- **server.ps1**: `harbinger-api` + `harbinger-tunnel` (alias `harbinger`), added 2026-10-09
  (backup `server.ps1.bak-harbinger`).
- **Tunnel**: `harbinger`, created 2026-10-09. Config `ops/cloudflared-config.yml` is gitignored
  (holds the UUID and hostname); the repo ships `cloudflared-config.example.yml`.
- **Tasks** (`ops/windows/install-tasks.ps1 -Controller C:\Development\server.ps1`):
  - "Harbinger Watchdog" every 5 min (unelevated falls back to schtasks, no at-logon trigger).
  - "Harbinger Ingest" fires at 06:30, 09:30, 12:30, 15:30, 18:30 local with `--if-due`
    (`harbinger/schedule.py`): the first tick each day always runs; later ticks run only while a
    wave is inside `[waves] notice_window` without its list. Once the list is in, they go quiet.
    It syncs Steam too, so the old "Harbinger Steam" task is gone (the installer deletes it).
    Each run that works costs one forecast subagent call (~90 s).
    **Why these times:** the official list goes up in the Xbox app ("Leaving soon") and Xbox Wire,
    and Pure Xbox writes it up. Pure Xbox's 22 "games are leaving" articles from Jul 2025 to Oct 2026
    landed 12-16 days before the wave (15 of 22 at exactly 13) on any weekday, the 1st-3rd or
    15th-18th, between 05:15 and 17:00 Eastern: most at 05:15-07:45, a few around 09:30-10:00 and
    12:30, weekends into the afternoon. The dataset lives in `tests/test_schedule.py`; add new
    lists there, and the test fails if the window stops covering them.
  - Jobs run `ops/windows/run-job.ps1`; logs in `ops/windows/logs/{ingest,steam}.log`.
- **Push** (`ingest --push`), three kinds, one push each, quiet otherwise:
  - New arrivals (owner, 2026-10-09): rows added to the Game Pass Premium tab, or to the PS Plus
    master list at Extra/Premium within your tier (Essential monthly games, PC-only, owned and
    beaten stay quiet). Read from `sheet_change` 'added' rows of imports in the last
    `[alerts] arrival_days` (7), so a manual ingest without `--push` doesn't swallow them; sent
    (service, key, stint) latch in `arrival_alert` on `pharos.delivered()`. First import of a
    sheet is a baseline (no changes). `store.arrivals` + `build.new_arrivals` + `arrival_alert`;
    `[alerts] arrivals = false` turns it off.
  - New leavers: verified leavers the previous ingest didn't list (owned excluded; no previous
    ingest = no push). `build.new_leavers` + `leaver_alert`, baseline `store.confirmed_keys`.
  - Queue (owner, 2026-10-09): each queued, unowned game (Game Pass or PS Plus) confirmed or modelled at >= `[alerts] min_p`
    (0.25, the Possible band) gets a heads-up `lead_days` (14) before its start-by date and a
    "start now" on it. `build.alerts_due` + `queue_alert`; sent (game, wave, stage) live in the
    `queue_alert` table, latched on `pharos.delivered()` (sent or muted), so a dry run or a failed
    send retries next day. A new wave is a new key; a game in today's leaver push is skipped.
  - `[queue] beaten` (finished or 100%'d) never pushes, either kind. Owned games are already quiet.
  Via Pharos
  (`source="harbinger"`, channel `digest`, own Pushover app with the raven icon), linking to
  `[push] url` from config.local.toml. Pharos is found
  installed, at `[push] dir`, or as a `Pharos` folder next to the repo; missing = no push, no error.
  A failed job pages through Pharos (`run-job.ps1 -PharosModule`, default the sibling folder).
- **Icon**: 8-bit raven (owner-picked 2026-10-09). `ops/icon.py` holds the pixel grid and writes
  `web/icon.svg`, `web/apple-touch-icon.png` and `web/icon-512.png`; edit the grid and rerun, never
  hand-edit the outputs. Pharos builds its 128px push icon from `icon-512.png` (`icons/build_icons.py`).
- **Forecast subagent**: `claude -p` with Read/Write/WebSearch/WebFetch, prompt and output under
  `harbinger/state/forecast-runs/<stamp>/` (plus `agent-output.txt`). ~90 s.
- **PSN**: `PSN_NPSSO` env var (registry too), else `[playstation] npsso` in config.local.toml.
  Expires about every two months (it is a browser session; nothing can extend it): Pharos `ops`
  pushes "PlayStation sign-in expired" once, and "back" once a new one works. The page header's
  "PSN synced" age also grows. Get a new one from
  https://ca.account.sony.com/api/v1/ssocookie while signed in at playstation.com.
- **Steam**: `STEAM_API_KEY` / `STEAM_ID` env vars (read from the registry too, so `setx` works
  without a new shell), else `[steam]` in config.local.toml. Profile game details must be public.
  This machine uses the env vars.
