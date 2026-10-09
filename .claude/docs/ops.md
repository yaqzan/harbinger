# Ops

Standard machine pattern (GameNight/Arbiter): one port, own tunnel, 5-min watchdog.

- **Server**: `py -3.11 -u -m harbinger serve`, stdlib ThreadingHTTPServer on 127.0.0.1:5006.
  Serves `web/`, `/data.json` (from `harbinger/state/`) and `/api/health`. GET/HEAD only,
  everything no-cache, path traversal refused (tested 2026-10-09).
  `/api/health` answers 200 whenever the server is up (the watchdog restarts on anything else);
  `stale: true` means data.json is over 40 h old, i.e. the scheduled jobs are failing.
- **server.ps1**: `harbinger-api` + `harbinger-tunnel` (alias `harbinger`), added 2026-10-09
  (backup `server.ps1.bak-harbinger`).
- **Tunnel**: `harbinger`, created 2026-10-09. Config `ops/cloudflared-config.yml` is gitignored
  (holds the UUID and hostname); the repo ships `cloudflared-config.example.yml`.
- **Tasks** (`ops/windows/install-tasks.ps1 -Controller C:\Development\server.ps1`):
  - "Harbinger Watchdog" every 5 min (unelevated falls back to schtasks, no at-logon trigger).
  - "Harbinger Ingest" daily 14:46 local (Eastern), after Xbox Wire's usual midday posts. Daily
    since 2026-10-09 (was the 3rd and 18th) so a confirmed leaver pushes within a day. It syncs
    Steam too, so the old "Harbinger Steam" task is gone (the installer deletes it). Costs one
    forecast subagent run (~90 s) a day.
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
