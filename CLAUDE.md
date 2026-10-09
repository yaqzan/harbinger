# Harbinger

Game Pass exit radar (Xbox console Game Pass; PC-only games are out of scope via `[scope]`), plus
PS Plus at the tier in `[playstation] tier`: which games are leaving (confirmed) or likely leaving (modelled),
hours to 100%, and the latest day to start. Read-only page, no auth, no input surface.

**Public, plug-and-play repo (github.com/yaqzan/harbinger).** Anyone clones it, adds their own
Steam account and watched games, and runs it. The owner's instance is https://harbinger.yaqzan.dev.

- Personal settings live in `config.local.toml` (gitignored, merged over `harbinger/config.toml`):
  `[steam]` id/key, `[queue]` watched games, `[push]`. A fresh clone watches nothing and is guided
  by `config.local.example.toml`. Steam env vars `STEAM_ID` / `STEAM_API_KEY` win over the file.
- Gitignored local state: `harbinger/state/` (`harbinger.sqlite` holds the imported sheet, Steam,
  title matches and snapshots), `config.local.toml`, `ops/cloudflared-config.yml`.
- Never commit those, or hardcode a machine path, domain, Steam id or personal game list in
  tracked files. Sibling tools (Pharos) are found next to the repo, never by absolute path.

## Commands

- `py -3.11 -m harbinger ingest [--no-forecast] [--push]`: import sheet + forecast subagent +
  Steam, reconcile titles, rebuild, snapshot (daily task). `--push` alerts on newly confirmed leavers.
- `py -3.11 -m harbinger steam`: Steam import + rebuild from the database
- `py -3.11 -m harbinger build [--today YYYY-MM-DD]`: re-score the database after a config or
  titles.toml change. `show`: print the summary. `titles`: match issues. `changes [--game X]`:
  what the last sheet imports changed.
- `py -3.11 -m unittest`: tests (model rules, a whole run pinned to Oct 9, 2026, config merge).
  Tests load the shared config only (`load_config(local=None)`).
- `C:\Development\server.ps1 start|status|logs -Service harbinger`: server (:5006) + tunnel
- `ops\windows\install-tasks.ps1 -Controller C:\Development\server.ps1`: watchdog + daily ingest

## Invariants

- **Every tunable number lives in `harbinger/config.toml`** (base rates, multipliers, bands,
  hours/week). Code never hardcodes a rate.
- `harbinger/model.py` is pure and fully tested. Change a rule there and in its test together.
- Never show a departure date in the past. A wave whose official list is out ("announced")
  counts as survived for every game it didn't name.
- Build reads the database, never the workbook or the Steam API. A failed import (download, or a
  sheet header that moved) keeps the previous one. Steam matches strict rungs only; title fixes go
  in `harbinger/titles.toml` (shared facts, tracked), never in code.
- The forecast is read by a `claude -p` subagent from a prompt FILE (no API key on this box).
  A failed refresh keeps the last good `forecast.json`; it never blanks the page.
- Page copy (web/): no em-dashes, no "X, not Y", plain sentences. Data goes in via textContent only.

## Docs

Model rules, signals, PS Plus, the one-service list and calibration: `.claude/docs/model.md` · database tables, imports and
title matching: `.claude/docs/data.md` · hosting, tasks, push:
`.claude/docs/ops.md` · kanban: vault `Engineering Wiki/Projects/Harbinger/`.
