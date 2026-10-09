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
  - "Harbinger Ingest" 3rd and 18th at 08:46 local (Eastern). Registered from XML because
    `schtasks /sc monthly` takes one day only. The dates dodge weekend postings on the 1st/15th.
  - "Harbinger Steam" daily 06:30.
  - Jobs run `ops/windows/run-job.ps1`; logs in `ops/windows/logs/{ingest,steam}.log`.
- **Push**: ingest sends one line via Pharos (`source="harbinger"`, channel `digest`, added to
  Pharos policy.json 2026-10-09), linking to `[push] url` from config.local.toml. Pharos is found
  installed, at `[push] dir`, or as a `Pharos` folder next to the repo; missing = no push, no error.
  A failed job pages through Pharos (`run-job.ps1 -PharosModule`, default the sibling folder).
- **Icon**: 8-bit raven (owner-picked 2026-10-09). `ops/icon.py` holds the pixel grid and writes
  `web/icon.svg`, `web/apple-touch-icon.png` and `web/icon-512.png`; edit the grid and rerun, never
  hand-edit the outputs. Pharos builds its 128px push icon from `icon-512.png` (`icons/build_icons.py`).
- **Forecast subagent**: `claude -p` with Read/Write/WebSearch/WebFetch, prompt and output under
  `harbinger/state/forecast-runs/<stamp>/` (plus `agent-output.txt`). ~90 s.
- **Steam**: `STEAM_API_KEY` / `STEAM_ID` env vars (read from the registry too, so `setx` works
  without a new shell), else `[steam]` in config.local.toml. Profile game details must be public.
  This machine uses the env vars.
