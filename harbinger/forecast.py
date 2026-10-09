"""The Pure Xbox leaving forecast and the official leaving notice.

Both are prose articles, so a Claude Code subagent reads them (no API key on this
machine: `claude -p` rides the subscription, pointed at a prompt FILE). It writes
forecast.json; we validate it and keep the last good one if a run fails.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import date, datetime

from . import STATE_DIR
from .sheet import norm, resolve

FORECAST_FILE = STATE_DIR / "forecast.json"
RUNS_DIR = STATE_DIR / "forecast-runs"

PROMPT = """\
You are collecting evidence for a Game Pass "leaving soon" tracker. Today is {today}.
Do web research, then write ONE file and nothing else.

Find, for these months: {months}

1. The newest OFFICIAL "leaving Game Pass" notice (Xbox Wire, or Pure Xbox / Insider
   Gaming reporting it). Removals happen on the 15th and the last day of a month, and
   the notice usually lands about 13 days before. List every game it names, with its
   leave date.
2. Pure Xbox's monthly forecast article of games likely to leave Game Pass in each of
   those months (titles like "Xbox Game Pass Games Likely Leaving In <Month> <Year>").
   List every game it names. If the article flags a game as unlikely to actually leave
   (for example "probably staying", "deal extended", "may not go"), mark it unlikely.

Rules:
- Only report what an article actually says. Never infer or pad a list.
- A month counts as "covered" only if you found that month's Pure Xbox forecast.
- Use the game titles as the article writes them.
- Note each article you used in "sources".

Write this JSON to the file {out_path} (UTF-8, no comments):

{{
  "checked_at": "<ISO timestamp>",
  "covers": ["YYYY-MM", ...],
  "listed": [{{"game": "...", "month": "YYYY-MM", "unlikely": false, "note": "short reason or empty"}}],
  "confirmed": [{{"game": "...", "wave": "YYYY-MM-DD", "source": "Xbox Wire | Pure Xbox | Insider Gaming"}}],
  "sources": [{{"title": "...", "url": "...", "published": "YYYY-MM-DD"}}]
}}

If you find nothing for a section, write an empty list. Do not create or edit any other file.
"""


def months_for(waves: list[date]) -> list[str]:
    return sorted({f"{w.year:04d}-{w.month:02d}" for w in waves})


def find_claude() -> str:
    for name in ("claude", "claude.exe", "claude.cmd"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("claude CLI not found on PATH")


def validate(data: dict) -> dict:
    for key in ("covers", "listed", "confirmed", "sources"):
        if not isinstance(data.get(key), list):
            raise ValueError(f"forecast.json: '{key}' missing or not a list")
    for item in data["listed"]:
        datetime.strptime(item["month"], "%Y-%m")
        item["game"] = str(item["game"]).strip()
        item["unlikely"] = bool(item.get("unlikely"))
    for item in data["confirmed"]:
        date.fromisoformat(item["wave"])
        item["game"] = str(item["game"]).strip()
    return data


def refresh(today: date, waves: list[date], timeout: int = 900) -> tuple[dict, str]:
    """Run the subagent. Returns (forecast, status note). Keeps the old file on failure."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workdir = RUNS_DIR / stamp
    workdir.mkdir(parents=True, exist_ok=True)
    out_path = workdir / "forecast.json"
    prompt_path = workdir / "prompt.md"
    prompt_path.write_text(PROMPT.format(today=today.isoformat(), months=", ".join(months_for(waves)),
                                         out_path=out_path), encoding="utf-8")
    cmd = [find_claude(), "-p", f'Read the file "{prompt_path}" and follow its instructions exactly.',
           "--allowedTools", "Read,Write,WebSearch,WebFetch", "--permission-mode", "acceptEdits"]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        (workdir / "agent-output.txt").write_text(
            (proc.stdout or "") + "\n--- stderr ---\n" + (proc.stderr or ""), encoding="utf-8")
        data = validate(json.loads(out_path.read_text(encoding="utf-8")))
    except Exception as e:  # noqa: BLE001 -- any failure keeps the last good forecast
        return load(), f"forecast refresh failed ({type(e).__name__}: {e}); kept the previous one"
    FORECAST_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data, f"forecast refreshed in {time.time() - t0:.0f}s"


def load() -> dict:
    if FORECAST_FILE.exists():
        return json.loads(FORECAST_FILE.read_text(encoding="utf-8"))
    return {"checked_at": None, "covers": [], "listed": [], "confirmed": [], "sources": []}


def for_model(data: dict, keys=()) -> dict:
    """The shape model.signals() reads, with titles resolved to sheet keys."""
    listed = {}
    for i in data.get("listed", []):
        key = resolve(i["game"], keys) or norm(i["game"])
        listed[key] = {"month": i["month"], "unlikely": i.get("unlikely", False)}
    return {"covers": set(data.get("covers", [])), "listed": listed}
