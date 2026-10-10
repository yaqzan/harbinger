"""py -3.11 -m harbinger ingest|steam|build|show|titles|changes|serve

ingest   import the sheets (Game Pass, PS Plus), refresh the forecast (claude subagent), sync Steam, rebuild, snapshot
steam    sync Steam and PSN into the database and rebuild from the imported sheets
build    rebuild data.json from the database (after a config.toml or titles.toml change)
show     print the current summary
titles   re-match titles across sources and list the weak matches and near misses
changes  what the last sheet imports changed (--game narrows it)
serve    the public page on 127.0.0.1:5006
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import date, datetime

from . import LIBRARY_FILE, OUTPUT_FILE, STATE_DIR, load_config, store
from . import ratings as ratings_mod
from . import art as art_mod
from . import forecast as fc_mod
from . import plus
from . import psn as psn_mod
from . import sheet as sheet_mod
from . import steam as steam_mod
from . import titles as titles_mod
from .build import alerts_due, arrival_alert, assemble, leaver_alert, new_leavers, queue_alert


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


def _ps(db, cfg: dict) -> dict | None:
    """Your PS Plus tier's catalogue, or None when the tier is "none" or no PS sheet is imported."""
    tier = str(cfg.get("playstation", {}).get("tier", "none")).lower()
    if plus.TIERS.get(tier, 0) == 0:
        return None
    tabs, fetched = sheet_mod.load_rows(db, "playstation")
    if not fetched:
        return None
    games = plus.catalogue(tabs, tier, plus.first_party(cfg), hide_vr=not cfg["playstation"].get("vr", False),
                           vr_only=plus.vr_only(cfg))
    return {"games": games, "fetched": fetched, "tier": tier.title()}


def run(kind: str, *, fetch: bool, refresh_forecast: bool, sync_steam: bool, today: date | None = None) -> dict:
    cfg = load_config()
    STATE_DIR.mkdir(exist_ok=True)
    today = today or date.today()
    notes = []
    db = store.connect()
    if fetch:
        notes.append(sheet_mod.ingest(db, cfg))
        if sheet_mod.sheet_id(cfg, "playstation"):
            notes.append(sheet_mod.ingest(db, cfg, "playstation"))
    sh = sheet_mod.load(db, cfg)
    ps = _ps(db, cfg)
    as_of = datetime.fromisoformat(sh.fetched).date()
    from .model import next_waves
    if refresh_forecast:
        fc, note = fc_mod.refresh(today, next_waves(today, cfg["waves"]["horizon"]))
        notes.append(note)
    else:
        fc = fc_mod.load()
    if sync_steam:
        # Achievements for what the page shows plus every played Steam game still on Game Pass
        draft = assemble(cfg, sh, fc, {"games": {}}, today, as_of)
        keys = _wanted(draft) | {g.key for g in sh.games if g.status in ("Active", "Leaving Soon")}
        match = titles_mod.Matcher((g.key for g in sh.games), cfg.get("titles"), sh.out_of_scope)
        notes.append(steam_mod.sync(db, cfg, lambda name: match.key(name, loose=False) in keys))
        note, outcome = psn_mod.sync(db, cfg)
        if note:
            notes.append(note)
        last = db.execute("SELECT at FROM psn_sync ORDER BY id DESC LIMIT 1").fetchone()
        pushed = psn_mod.alert(outcome, last[0] if last else None,
                               _pharos(cfg) if cfg.get("push", {}).get("enabled", True) else None)
        if pushed:
            notes.append(pushed)
    notes.append(titles_mod.reconcile(db, sh, fc, cfg, ps["games"] if ps else ()))
    arrived = store.arrivals(db, cfg["alerts"]["arrival_days"]) if kind == "ingest" and cfg["alerts"]["arrivals"] else []
    data = assemble(cfg, sh, fc, steam_mod.load(db), today, as_of, ps, psn_mod.load(db, cfg), arrived)
    if sync_steam:  # network lookups only on ingest and steam; build shows what is already cached
        notes.append(art_mod.fetch(db, art_mod.wanted(data), cfg))
    art_mod.attach(data, art_mod.load(db))
    if sync_steam:
        notes.append(ratings_mod.fetch(db, ratings_mod.wanted(data["library"]), cfg))
    ratings_mod.attach(data["library"], ratings_mod.load(db, ratings_mod.settings(cfg)["min_reviews"]))
    base_at, base = store.baseline(db, kind)
    _apply_deltas(data, base_at, base)
    # what the push alerts on: verified leavers the previous ingest didn't have
    data["new_confirmed"] = new_leavers(data["confirmed"], store.confirmed_keys(db), data["beaten"]) if kind == "ingest" else []
    # queued games whose heads-up or start push is due (marked sent only once Pharos delivers it)
    data["queue_alerts"] = (alerts_due(data["queue"], today, cfg, store.alerts_sent(db),
                                       {r["key"] for r in data["new_confirmed"]}) if kind == "ingest" else [])
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
    # the library is its own file: the leaving page doesn't need to download it
    lib = data.pop("library")
    for path, body, indent in ((LIBRARY_FILE, {"generated_at": data["generated_at"], "ps_tier": data["one_service"]["ps_tier"],
                                               "rows": lib}, None), (OUTPUT_FILE, data, 1)):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, indent=indent, separators=(",", ":") if indent is None else None), encoding="utf-8")
        tmp.replace(path)
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
    """Alert the phone via Pharos: newly confirmed leavers, queued games to start soon, and new
    Game Pass Premium / PS Plus arrivals (one push each). Quiet when there's none."""
    p = cfg.get("push", {})
    if not p.get("enabled", True):
        return "push disabled in config"
    new, due, arrived = data.get("new_confirmed", []), data.get("queue_alerts", []), data.get("arrivals", [])
    if not new and not due and not arrived:
        return "push: nothing new"
    pharos = _pharos(cfg)
    if pharos is None:
        return "push skipped: Pharos not found"
    today = date.fromisoformat(data["today"])
    link = {"url": p["url"], "url_title": "Open the radar"} if p.get("url") else {}
    out = []
    if new:
        result = pharos.send(*leaver_alert(new, today), source="harbinger", channel="digest", **link)
        out.append(f"leavers {result.status}")
    if due:
        result = pharos.send(*queue_alert(due, today), source="harbinger", channel="digest", **link)
        if pharos.delivered(result.status):  # sent or muted: latch, so a mute doesn't pile up retries
            store.mark_alerts(store.connect(), due)
        out.append(f"queue {result.status}")
    if arrived:
        result = pharos.send(*arrival_alert(arrived), source="harbinger", channel="digest", **link)
        if pharos.delivered(result.status):
            store.mark_arrivals(store.connect(), arrived)
        out.append(f"arrivals {result.status}")
    return "push: " + ", ".join(out)


def _changes(game: str | None, imports: int = 5) -> int:
    db = store.connect()
    q = ("SELECT i.fetched_at, c.service || ' ' || c.tab, c.title, c.kind, c.field, c.old, c.new FROM sheet_change c"
         " JOIN sheet_import i ON i.id = c.import_id WHERE c.import_id IN"
         " (SELECT id FROM sheet_import ORDER BY id DESC LIMIT ?)")
    args: list = [imports]
    if game:
        q += " AND c.key = ?"
        args.append(sheet_mod.norm(game))
    rows = db.execute(q + " ORDER BY c.import_id DESC, c.tab, c.title", args).fetchall()
    if not rows:
        print("no sheet changes recorded" + (f" for {game}" if game else ""))
    for at, tab, title, kind, fld, old, new in rows:
        what = f"{fld}: {old!r} -> {new!r}" if kind == "changed" else kind
        print(f"{at[:10]}  {tab:<26} {title}  {what}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harbinger", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["ingest", "steam", "build", "show", "titles", "changes", "serve"])
    ap.add_argument("--game", help="changes: only this title")
    ap.add_argument("--no-forecast", action="store_true", help="ingest: keep the last forecast")
    ap.add_argument("--push", action="store_true", help="ingest: push newly confirmed leavers and queued games to start via Pharos (optional, see config.local.example.toml)")
    ap.add_argument("--today", type=date.fromisoformat, help="score as of this date (testing)")
    a = ap.parse_args(argv)
    if a.command == "serve":
        from .serve import serve
        serve()
        return 0
    if a.command == "titles":
        cfg = load_config()
        db = store.connect()
        ps = _ps(db, cfg)
        print(titles_mod.reconcile(db, sheet_mod.load(db, cfg), fc_mod.load(), cfg, ps["games"] if ps else ()))
        titles_mod.print_report(db)
        return 0
    if a.command == "changes":
        return _changes(a.game)
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
