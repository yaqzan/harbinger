"""py -3.11 -m harbinger ingest|steam|build|show|serve

ingest  fetch the sheet, refresh the forecast (claude subagent), sync Steam, rebuild, snapshot
steam   sync Steam progress and rebuild from the cached sheet and forecast (the daily job)
build   rebuild data.json from cached inputs (after a config.toml change)
show    print the current summary
serve   the public page on 127.0.0.1:5006
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import date, datetime

from . import OUTPUT_FILE, STATE_DIR, load_config, store
from . import forecast as fc_mod
from . import sheet as sheet_mod
from . import steam as steam_mod
from .build import assemble

FETCHED_FILE = sheet_mod.SHEET_DIR / "fetched.txt"


def _sheet(fetch: bool, cfg: dict) -> sheet_mod.Sheet:
    if fetch:
        tabs = sheet_mod.fetch(cfg)
        FETCHED_FILE.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    else:
        tabs = sheet_mod.load_cached()
    return sheet_mod.parse(tabs, FETCHED_FILE.read_text(encoding="utf-8").strip())


def _wanted(data: dict) -> set[str]:
    return {r["key"] for r in data["confirmed"] + data["watchlist"]} | {sheet_mod.norm(r["game"]) for r in data["queue"]}


def _apply_deltas(data: dict, base_at: str | None, base: dict) -> None:
    data["sources"]["baseline"] = base_at
    for r in data["watchlist"]:
        prev = base.get(r["key"])
        if not base_at:
            r["delta"] = None
        elif prev is None or prev[1] != r["wave"]:
            r["delta"] = "new"
        else:
            r["delta"] = round((r["p"] - prev[0]) * 100)


def run(kind: str, *, fetch: bool, refresh_forecast: bool, sync_steam: bool, today: date | None = None) -> dict:
    cfg = load_config()
    STATE_DIR.mkdir(exist_ok=True)
    today = today or date.today()
    notes = []
    sh = _sheet(fetch, cfg)
    as_of = datetime.fromisoformat(sh.fetched).date()
    from .model import next_waves
    if refresh_forecast:
        fc, note = fc_mod.refresh(today, next_waves(today, cfg["waves"]["horizon"]))
        notes.append(note)
    else:
        fc = fc_mod.load()
    st = steam_mod.load()
    if sync_steam:
        draft = assemble(cfg, sh, fc, {"games": {}}, today, as_of)
        st, note = steam_mod.sync(_wanted(draft), cfg)
        notes.append(note)
    data = assemble(cfg, sh, fc, st, today, as_of)
    db = store.connect()
    base_at, base = store.baseline(db, kind)
    _apply_deltas(data, base_at, base)
    rows = ([{"game": r["game"], "key": r["key"], "list": "confirmed", "wave": r["wave"], "hours": r["hours"],
              "owned": int(r["owned"])} for r in data["confirmed"] if r["verified"]] +
            [{"game": r["game"], "key": r["key"], "list": "watchlist", "wave": r["wave"], "cohort": r["cohort"],
              "p": r["p"], "band": r["band"], "hours": r["hours"], "urgency": r["urgency"], "owned": int(r["owned"])}
             for r in data["watchlist"]])
    store.record(db, kind, as_of.isoformat(), "; ".join(notes), rows)
    data["history"] = store.history(db)
    data["generated_at"] = datetime.now().isoformat(timespec="seconds")
    data["notes"] = notes
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(OUTPUT_FILE)
    return data


def _pharos(cfg: dict):
    """Pharos if it's installed or sits next to this repo; None means no pushes."""
    try:
        import pharos
        return pharos
    except ImportError:
        pass
    from . import ROOT
    where = cfg.get("push", {}).get("dir") or str(ROOT.parent / "Pharos")
    if (Path(where) / "pharos").is_dir():
        sys.path.insert(0, where)
        import pharos
        return pharos
    return None


def push(data: dict, cfg: dict) -> str:
    """One-line summary to the phone via Pharos (no project name, no commands)."""
    p = cfg.get("push", {})
    if not p.get("enabled", True):
        return "push disabled in config"
    pharos = _pharos(cfg)
    if pharos is None:
        return "push skipped: Pharos not found"
    s = data["summary"]
    starts = [r["game"] for r in data["watchlist"] if r["urgency"] == "Start now"][:3]
    if s["confirmed_count"]:
        title = f"{s['finishable_count']} of {s['confirmed_count']} Game Pass leavers still finishable"
    else:
        title = "No Game Pass leavers confirmed"
    body = [f"{s['likely_count']} likely next", f"{s['hours_available']:g} h before {s['next_wave']}"]
    if starts:
        body.append("start now: " + ", ".join(starts))
    link = {"url": p["url"], "url_title": "Open the radar"} if p.get("url") else {}
    result = pharos.send(title, " · ".join(body), source="harbinger", channel="digest", **link)
    return f"push: {getattr(result, 'status', result)}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harbinger", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["ingest", "steam", "build", "show", "serve"])
    ap.add_argument("--no-forecast", action="store_true", help="ingest: keep the last forecast")
    ap.add_argument("--push", action="store_true", help="ingest: send the Pharos summary (optional, see config.local.example.toml)")
    ap.add_argument("--today", type=date.fromisoformat, help="score as of this date (testing)")
    a = ap.parse_args(argv)
    if a.command == "serve":
        from .serve import serve
        serve()
        return 0
    if a.command == "show":
        if not OUTPUT_FILE.exists():
            print("no data.json yet")
            return 1
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    elif a.command == "ingest":
        data = run("ingest", fetch=True, refresh_forecast=not a.no_forecast, sync_steam=True, today=a.today)
    elif a.command == "steam":
        data = run("steam", fetch=False, refresh_forecast=False, sync_steam=True, today=a.today)
    else:
        data = run("build", fetch=False, refresh_forecast=False, sync_steam=False, today=a.today)
    s = data["summary"]
    print(s["takeaway"])
    print(f"next wave {s['next_wave']} in {s['days_to_next_wave']}d · {s['hours_available']} h · "
          f"confirmed {s['confirmed_count']} · finishable {s['finishable_count']} · likely {s['likely_count']} · "
          f"next notice {s['next_notice']}")
    for n in data.get("notes", []):
        print(" -", n)
    if a.command == "ingest" and a.push:
        print(" -", push(data, load_config()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
