# Harbinger

Game Pass exit radar: which Game Pass games are leaving (confirmed) or likely leaving (modelled),
hours to 100%, and the latest day to start. Read-only page, no auth, no input surface.

**Public, plug-and-play repo (github.com/yaqzan/harbinger).** Anyone clones it, adds their own
Steam account and watched games, and runs it. The owner's instance is https://harbinger.yaqzan.dev.

- Personal settings live in `config.local.toml` (gitignored, merged over `harbinger/config.toml`):
  `[steam]` id/key, `[queue]` watched games, `[push]`. A fresh clone watches nothing and is guided
  by `config.local.example.toml`. Steam env vars `STEAM_ID` / `STEAM_API_KEY` win over the file.
- Gitignored local state: `harbinger/state/`, `config.local.toml`, `ops/cloudflared-config.yml`.
- Never commit those, or hardcode a machine path, domain, Steam id or personal game list in
  tracked files. Sibling tools (Pharos) are found next to the repo, never by absolute path.

## Commands

- `py -3.11 -m harbinger ingest [--no-forecast] [--push]`: sheet + forecast subagent + Steam,
  rebuild, snapshot. `--push` sends the Pharos summary (the scheduled task passes it).
- `py -3.11 -m harbinger steam`: Steam progress + rebuild from cached inputs (daily job)
- `py -3.11 -m harbinger build [--today YYYY-MM-DD]`: re-score cached inputs after a config change.
  `show`: print the summary.
- `py -3.11 -m unittest`: tests (model rules, a whole run pinned to Oct 9, 2026, config merge).
  Tests load the shared config only (`load_config(local=None)`).
- `C:\Development\server.ps1 start|status|logs -Service harbinger`: server (:5006) + tunnel
- `ops\windows\install-tasks.ps1 -Controller C:\Development\server.ps1`: watchdog, ingest, Steam tasks

## Invariants

- **Every tunable number lives in `harbinger/config.toml`** (base rates, multipliers, bands,
  hours/week). Code never hardcodes a rate.
- `harbinger/model.py` is pure and fully tested. Change a rule there and in its test together.
- Never show a departure date in the past. A wave whose official list is out ("announced")
  counts as survived for every game it didn't name.
- The forecast is read by a `claude -p` subagent from a prompt FILE (no API key on this box).
  A failed refresh keeps the last good `forecast.json`; it never blanks the page.
- Page copy (web/): no em-dashes, no "X, not Y", plain sentences. Data goes in via textContent only.

## Docs

Model rules, signals and calibration: `.claude/docs/model.md` · hosting, tasks, push:
`.claude/docs/ops.md` · kanban: vault `Engineering Wiki/Projects/Harbinger/`.
