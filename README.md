# Harbinger

A Game Pass exit radar. It reads u/ABattleVet's Game Pass Master List, Pure Xbox's monthly
"might be leaving" forecasts and your Steam library, then tells you which games are leaving or
likely to leave, how long each takes to finish, and the latest day you can start.

## How it works

- Removals land on the 15th and the last day of each month, near a game's 12, 18, 24 or 36
  month anniversary. Each game gets odds from how often games have left at that anniversary,
  adjusted for the Pure Xbox forecast and Premium membership. Details: `.claude/docs/model.md`.
- A Claude Code subagent reads the forecast articles (`claude -p`, so it runs on a Claude
  subscription with no API key). Without Claude Code installed, run ingest with `--no-forecast`.
- Games you own on Steam or PlayStation, or can keep playing on the other service, stay on the
  page dimmed, with the alternative named. Your playtime and achievements shrink the hours left.
- Two tabs: the Board, every leaving game in order of the last day to start it, and the Library,
  everything you can play across the services and your own libraries.

## Set up

Python 3.11, standard library only.

1. Copy `config.local.example.toml` to `config.local.toml` (gitignored) and fill in:
   - `[steam]`: your SteamID64 or profile name, and a Steam Web API key from
     https://steamcommunity.com/dev/apikey. Or set `STEAM_ID` / `STEAM_API_KEY` in the environment.
     Your Steam profile's "Game details" privacy setting must be Public.
   - `[playstation]`: your PS Plus tier (`essential`, `extra` or `premium`), to add PS Plus to the
     page and see which games you can only play through one subscription. Leave it `none` if
     you don't have PS Plus.
   - `[queue]`: the Game Pass games you're playing or plan to play. The example file explains
     what counts as a watched game.
2. Run it:
   ```
   py -3.11 -m harbinger ingest      # import the sheet and Steam, score, write harbinger/state/data.json
   py -3.11 -m harbinger titles      # Steam games that didn't match the sheet cleanly
   py -3.11 -m harbinger serve       # http://127.0.0.1:5006
   py -3.11 -m unittest
   ```
3. Optional, Windows: `ops\windows\install-tasks.ps1` schedules the ingest (3rd and 18th),
   a daily Steam sync and a watchdog for the server. `ops\cloudflared-config.example.yml` shows
   how to publish the page through a Cloudflare tunnel.
4. Optional: phone summaries after each ingest go through
   [Pharos](https://github.com/yaqzan/pharos) if it's installed or cloned next to this repo.

Your data stays local: everything a run produces lives in `harbinger/state/` (gitignored), mostly
in `harbinger.sqlite` (the imported sheet with its change history, your Steam library and
achievements, title matches, score snapshots), and
the Steam key is never written into the page data. If you publish the page, though, the data it
serves shows your Game Pass watchlist and which of those games you own on Steam.

Shared model numbers live in `harbinger/config.toml`; anything in your `config.local.toml`
overrides them. Title fixes between Steam and the sheet ("PAYDAY 2" is the sheet's "Payday 2:
Crimewave Edition") live in `harbinger/titles.toml`; add yours there, and a pull request helps
everyone.
