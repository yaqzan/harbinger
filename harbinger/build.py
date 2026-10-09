"""Turn the sheets, the forecast and your libraries (Steam, PlayStation) into the page's data.json.

`assemble()` is pure (inputs in, dict out) so tests can pin a whole run to a fixed day.
"""

from __future__ import annotations

import difflib
from datetime import date

from . import model, plus
from .forecast import for_model
from .sheet import Game, Sheet, norm
from .titles import Matcher, ps_matcher

BANDS = ("Confirmed", "Likely", "Possible", "Thin")
FINISHABLE = ("Doable", "Tight")


def fmt(d: date | None, today: date | None = None) -> str:
    if d is None:
        return ""
    s = f"{d:%b} {d.day}"
    return s if today and d.year == today.year else f"{s}, {d.year}"


def _join(names: list[str]) -> str:
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


class Context:
    def __init__(self, cfg: dict, sheet: Sheet, forecast: dict, steam: dict, today: date, as_of: date,
                 psn: dict | None = None):
        self.cfg, self.sheet, self.today, self.as_of = cfg, sheet, today, as_of
        self.match = Matcher((g.key for g in sheet.games), cfg.get("titles"), sheet.out_of_scope)
        self.forecast_raw, self.fc = forecast, for_model(forecast, match=lambda n: self.match.match_all(n)[0])
        # Games you own, by sheet key ("CloverPit" -> "clover pit"): Steam first, then PlayStation
        # (bought or on disc). rec["where"] says which.
        self.owned: dict[str, dict] = {}
        for lib, where in ((steam, "Steam"), (psn or {}, "PlayStation")):
            for k, r in lib.get("games", {}).items():
                key = self.match.key(r.get("name") or k, loose=False) or k
                self.owned.setdefault(key, {"where": where, **r})
        self.claimed = list((psn or {}).get("claimed", []))  # PS Plus games claimed into the library
        self.playing = (psn or {}).get("playing", {})          # every PS game you've played, owned or not
        self.dpm = cfg["sheet"]["days_per_month"]
        self.cohorts = cfg["waves"]["cohorts"]
        self.play = cfg["play"]
        self.waves = model.next_waves(today, cfg["waves"]["horizon"])
        # A game back for a second stint has a row per stint: the newest one speaks for it.
        self.by_key = {}
        for g in sorted(sheet.games, key=lambda g: (g.added_month or date.min, g.status == "Active")):
            self.by_key[g.key] = g
        self.announced: set[date] = set()  # waves whose official list is out; set by assemble()

    # ── per-game facts ────────────────────────────────────────────────

    def pc_only(self, name: str) -> bool:
        """Out of scope: on the sheet only as a PC Game Pass game ([scope] in config.toml)."""
        return self.match.match(name)[1] == "pc only"

    def excluded(self, g: Game) -> str | None:
        ex = self.cfg["exclude"]
        if g.key in self.sheet.first_party:
            return "first-party"
        if g.key in self.sheet.ea_play or ex["ea_note"] in g.notes:
            return "EA Play"
        if ex["retro_note"] in g.notes:
            return "Retro Classics"
        return None

    def is_ubisoft(self, g: Game) -> bool:
        return self.cfg["exclude"]["ubisoft_note"] in g.notes

    def added(self, g: Game) -> date | None:
        return None if g.months is None else model.add_date(self.as_of, g.months, self.dpm)

    def premium(self, g: Game) -> dict:
        on = g.premium_status in ("Active", "Leaving Soon") or g.key in self.sheet.premium
        readd = False
        if on and g.premium_added and g.added_month:
            gap = (g.premium_added.year - g.added_month.year) * 12 + g.premium_added.month - g.added_month.month
            readd = gap >= self.cfg["multipliers"]["premium_readd_gap_months"] and g.premium_added.year > 2024
        return {"on": on, "readd": readd}

    def progress(self, key: str, hours: float | None) -> dict:
        s = self.owned.get(key)
        if not s:
            return {"owned": False, "where": "", "hours": hours, "progress": ""}
        share = s.get("share")  # Sony's grade-weighted trophy progress, when PlayStation has it
        if share is None and s.get("ach_total"):
            share = s["ach_done"] / s["ach_total"]
        left = model.remaining_hours(hours, s.get("played_h"), share)
        bits = [f"{s['played_h']:g} h played"] if s.get("played_h") else []
        if share is not None:
            bits.append(f"{s['ach_done']}/{s['ach_total']} {'trophies' if s['where'] != 'Steam' else 'achievements'}")
        if s.get("hard"):
            bits.append(s["hard"])
        return {"owned": True, "where": s["where"], "hours": left,
                "progress": ", ".join([f"owned on {s['where']}"] + bits) if s["where"] != "Steam"
                else ", ".join(bits) or "not started"}

    def score(self, g: Game, n: int, wave: date) -> tuple[float, list[str]]:
        anniv = model.anniversary(self.added(g), n, self.dpm)
        sig = model.signals(n, wave, g.key, self.fc, self.premium(g), self.cfg, anniv)
        p = model.leave_probability(self.cfg["base_rates"][str(n)], [m for m, _ in sig])
        return p, [why for _, why in sig]


def confirmed_rows(cx: Context) -> list[dict]:
    today = cx.today
    fc_dates = {key: (date.fromisoformat(c["wave"]), c.get("source", ""))
                for c in cx.forecast_raw.get("confirmed", []) if not cx.pc_only(c["game"])
                for key in (cx.match.match_all(c["game"])[0] or [norm(c["game"])])}
    entries: dict[str, dict] = {}
    for g in cx.sheet.leaving:
        if g.key in fc_dates:
            wave, src = fc_dates[g.key]
        elif g.removed_month:
            wave, src = model.first_wave_in_month(g.removed_month.year, g.removed_month.month, today), "sheet"
        else:
            wave, src = None, "sheet"
        entries[g.key] = {"g": g, "name": g.name, "wave": wave, "source": src, "verified": True}
    trusted = {t.lower() for t in cx.cfg["waves"].get("trusted_sources", [])}
    for key, (wave, src) in fc_dates.items():
        if key not in entries:
            g = cx.by_key.get(key)
            ok = any(t in src.lower() for t in trusted)
            entries[key] = {"g": g, "name": g.name if g else key.title(), "wave": wave,
                            "source": src if ok else f"{src} only; not on the sheet", "verified": ok}
    for m in cx.cfg.get("manual_confirmed", []):
        key = norm(m["game"])
        if key not in entries and not cx.pc_only(m["game"]):
            entries[key] = {"g": cx.by_key.get(key), "name": m["game"], "wave": date.fromisoformat(m["wave"]),
                            "source": m["source"], "verified": False}
    rows = []
    for key, e in entries.items():
        wave = e["wave"]
        if wave is None or wave < today:
            continue  # never show a departure date in the past
        g = e["g"]
        sheet_hours = g.hours if g else None
        prog = cx.progress(key, sheet_hours)
        avail = model.hours_available(today, wave, cx.play["hours_per_week"])
        verdict = f"Owned on {prog['where']}" if prog["owned"] else model.verdict(prog["hours"], avail, cx.play)
        if not e["verified"]:
            note = f"Unverified: {e['source']}"
        else:
            note = f"Confirmed by {e['source']}" if e["source"] != "sheet" else "On the sheet's Leaving Soon tab"
        rows.append({
            "game": e["name"], "key": key, "wave": wave.isoformat(), "wave_label": fmt(wave, today),
            "hours": prog["hours"], "verdict": verdict, "platform": g.system if g else "",
            "note": note, "verified": e["verified"], "owned": prog["owned"], "progress": prog["progress"],
        })
    rows.sort(key=lambda r: (r["wave"], r["hours"] if r["hours"] is not None else 999))
    return rows


def scored_rows(cx: Context, confirmed_keys: set[str]):
    """Watchlist (next checkpoint inside the horizon), survivors, owned, Ubisoft."""
    today, last_wave = cx.today, cx.waves[-1]
    watch, survivors, ubisoft = [], [], []
    for g in cx.sheet.games:
        if g.status != "Active" or g.key in confirmed_keys or g.months is None:
            continue
        if cx.excluded(g):
            continue
        added = cx.added(g)
        nxt = model.next_checkpoint(added, today, cx.cohorts, cx.dpm, cx.announced)
        if cx.is_ubisoft(g):
            ubisoft.append({"game": g.name, "checkpoint": f"{nxt[0]} mo · {fmt(nxt[1], today)}" if nxt else "none left",
                            "hours": g.hours})
            continue
        last = model.last_checkpoint(added, today, cx.cohorts, cx.dpm, cx.announced)
        if last and (today - last[1]).days <= 45:
            near = "none left in the model"
            if nxt:
                p, _ = cx.score(g, *nxt)
                near = f"{model.band(p, cx.cfg['bands'])} at {nxt[0]} mo ({fmt(nxt[1], today)})"
            survivors.append({"game": g.name, "checkpoint": f"{last[0]} mo · {fmt(last[1], today)}",
                              "near_term": near, "why": "Not named in that wave's leaving notice"})
        if not nxt or nxt[1] > last_wave:
            continue
        n, wave = nxt
        p, reasons = cx.score(g, n, wave)
        prog = cx.progress(g.key, g.hours)
        hours = prog["hours"]
        prem = cx.premium(g)
        anniv = model.anniversary(added, n, cx.dpm)
        sb = model.start_by(wave, hours, cx.play) if hours is not None else None
        watch.append({
            "game": g.name, "key": g.key, "wave": wave.isoformat(), "wave_label": fmt(wave, today),
            "notice": fmt(model.notice_date(wave, cx.cfg["waves"]["notice_days"]), today),
            "cohort": n, "p": round(p, 3), "evidence": f"{round(p * 100)}%",
            "band": model.band(p, cx.cfg["bands"]), "hours": hours,
            "start_by": fmt(sb, today) if sb else "", "start_by_iso": sb.isoformat() if sb else "",
            "urgency": "Owned elsewhere" if prog["owned"] else model.urgency(today, wave, hours, cx.play),
            "tier": "Ultimate + Premium" if prem["on"] else "Ultimate",
            "why": "; ".join([f"{n}-month anniversary {fmt(anniv, today)}"] + reasons),
            "owned": prog["owned"], "progress": prog["progress"],
        })
    watch.sort(key=lambda r: (-r["p"], r["wave"]))
    survivors.sort(key=lambda r: r["game"].lower())
    ubisoft.sort(key=lambda r: r["game"].lower())
    return watch, survivors, ubisoft


def _find(cx: Context, name: str) -> Game | None:
    key = cx.match.key(name) or norm(name)
    if key in cx.by_key:
        return cx.by_key[key]
    pref = [g for g in cx.sheet.games if g.key.startswith(key) or key.startswith(g.key)]
    if pref:
        return min(pref, key=lambda g: abs(len(g.key) - len(key)))
    close = difflib.get_close_matches(key, list(cx.by_key), n=1, cutoff=0.85)
    return cx.by_key[close[0]] if close else None


def queue_rows(cx: Context, confirmed: list[dict]) -> list[dict]:
    today = cx.today
    conf = {r["key"]: r for r in confirmed}
    rows = []
    q = cx.cfg.get("queue", {})
    for name in q.get("gone", []) + q.get("tracking", []):
        g = None if cx.pc_only(name) else _find(cx, name)
        # wave/p/hours/start_by/owned: what the queue push reads (alerts_due)
        row = {"game": g.name if g else name, "key": g.key if g else norm(name), "state": "", "next_check": "",
               "odds": "", "note": "", "wave": "", "p": None, "hours": None, "start_by": "", "owned": False}
        if g is None and cx.pc_only(name):
            row.update(state="PC only", note="Not tracked: console Game Pass only")
        elif g is None:
            row.update(state="Not on the sheet", note="Check the title in config.toml")
        elif g.key in conf:
            c = conf[g.key]
            row.update(state=f"Leaving {c['wave_label']}", next_check=c["wave_label"], odds="Confirmed", note=c["verdict"],
                       wave=c["wave"], p=1.0 if c["verified"] else None, hours=c["hours"], owned=c["owned"])
            if c["hours"] is not None and not c["owned"]:
                row["start_by"] = model.start_by(date.fromisoformat(c["wave"]), c["hours"], cx.play).isoformat()
        elif g.status == "Removed":
            row.update(state=f"Gone ({g.removed_month:%b %Y})" if g.removed_month else "Gone")
        elif g.status != "Active":
            row.update(state=g.status)
        else:
            why = cx.excluded(g)
            nxt = model.next_checkpoint(cx.added(g), today, cx.cohorts, cx.dpm, cx.announced)
            if why:
                row.update(state="Active", odds="Not scored", note=f"{why}: assumed to stay")
            elif cx.is_ubisoft(g):
                row.update(state="Active", odds="Not scored", note="Ubisoft+ Classics bundle")
            elif nxt:
                p, _ = cx.score(g, *nxt)
                prog = cx.progress(g.key, g.hours)
                row.update(state="Active", next_check=f"{nxt[0]} mo · {fmt(nxt[1], today)}",
                           odds=f"{round(p * 100)}% ({model.band(p, cx.cfg['bands'])})",
                           wave=nxt[1].isoformat(), p=round(p, 3), hours=prog["hours"], owned=prog["owned"])
                if prog["hours"] is not None and not prog["owned"]:
                    sb = model.start_by(nxt[1], prog["hours"], cx.play)
                    row["start_by"] = sb.isoformat()
                    row["note"] = f"{model.urgency(today, nxt[1], prog['hours'], cx.play)}, start by {fmt(sb, today)}"
            else:
                row.update(state="Active", next_check="past 36 mo", note="No anniversary left in the model")
            if name in q.get("gone", []):
                row["note"] = (row["note"] + "; " if row["note"] else "") + "back on the service?"
        if g is not None and g.key in cx.owned:
            row["note"] = (row["note"] + "; " if row["note"] else "") + f"you own it on {cx.owned[g.key]['where']}"
        rows.append(row)
    return rows


def calibration_rows(cx: Context) -> list[dict]:
    pool = [g for g in cx.sheet.games if g.months is not None and g.status in ("Active", "Removed", "Leaving Soon")
            and not cx.excluded(g) and not cx.is_ubisoft(g)]

    def rate(n: int, games):
        left = sum(1 for g in games if g.status != "Active" and n - 1 <= g.months < n + 1)
        stayed = sum(1 for g in games if g.months >= n + 1)
        total = left + stayed
        return (left / total if total else 0.0), total

    rows = []
    for n in cx.cohorts:
        r, total = rate(n, pool)
        rows.append({"measure": f"{n}-month leave rate", "value": f"{round(r * 100)}%", "n": f"{total} games",
                     "source": f"Measured from the sheet; the model uses {round(cx.cfg['base_rates'][str(n)] * 100)}%"})
    r25, t25 = rate(12, [g for g in pool if g.added_month and g.added_month.year == 2025])
    rows.insert(1, {"measure": "12-month leave rate, 2025 adds", "value": f"{round(r25 * 100)}%",
                    "n": f"{t25} games", "source": "Measured from the sheet"})
    rows.append({"measure": "Typical notice", "value": f"{cx.cfg['waves']['notice_days']} days",
                 "n": "", "source": "Before each wave (Xbox Wire)"})
    return rows


def wave_rows(cx: Context, confirmed: list[dict], watch: list[dict]) -> list[dict]:
    out = []
    for w in cx.waves:
        iso = w.isoformat()
        games = {b: [] for b in BANDS}
        for r in confirmed:
            if r["wave"] == iso and r["verified"]:
                games["Confirmed"].append(r["game"])
        for r in watch:
            if r["wave"] == iso and not r["owned"]:
                games[r["band"]].append(r["game"])
        out.append({"wave": iso, "label": fmt(w, cx.today), **{b: len(v) for b, v in games.items()}, "games": games})
    return out


def summary(cx: Context, confirmed: list[dict], watch: list[dict]) -> dict:
    today, play = cx.today, cx.play
    nxt = cx.waves[0]
    hours = model.hours_available(today, nxt, play["hours_per_week"])
    real = [r for r in confirmed if r["verified"]]
    live = [r for r in real if not r["owned"]]
    finishable = [r for r in live if r["verdict"] in FINISHABLE]
    likely = [r for r in watch if r["band"] == "Likely" and not r["owned"]]
    notices = [model.notice_date(w, cx.cfg["waves"]["notice_days"]) for w in cx.waves]
    next_notice = min((d for d in notices if d >= today), default=None)
    if real:
        first = min(r["wave"] for r in real)
        on_first = [r for r in live if r["wave"] == first]
        fin_first = [r["game"] for r in on_first if r["verdict"] in FINISHABLE]
        when = fmt(date.fromisoformat(first), today)
        avail = model.hours_available(today, date.fromisoformat(first), play["hours_per_week"])
        total = sum(1 for r in real if r["wave"] == first)
        owned = total - len(on_first)
        lead = f"{total} games leave {when}"
        if owned:
            where = {r["verdict"].removeprefix("Owned on ") for r in real if r["owned"]}
            lead += f" and you own {owned} of them" + (f" on {where.pop()}" if len(where) == 1 else "")
        rest = "the rest" if owned else "them"
        if not on_first:
            take = lead + "."
        elif not fin_first:
            take = f"{lead}. None of {rest} fits in the {avail:.1f} hours you have before then."
        elif len(fin_first) == len(on_first):
            take = f"{lead}. All of {rest} still fit in your {avail:.1f} hours."
        else:
            take = (f"{lead}. With {avail:.1f} playable hours before then, "
                    f"only {_join(fin_first)} can still be finished.")
    else:
        take = "Nothing is confirmed to leave yet."
    if likely:
        take += f" {len(likely)} more look likely to go over the next {len(cx.waves)} waves."
    return {
        "takeaway": take,
        "next_wave": fmt(nxt, today), "days_to_next_wave": (nxt - today).days,
        "hours_available": round(hours, 1), "confirmed_count": len(real),
        "finishable_count": len(finishable), "likely_count": len(likely),
        "next_notice": fmt(next_notice, today) if next_notice else "",
    }


# ── only on one service ─────────────────────────────────────────────

ORDER = {"Confirmed": 0, "Likely": 1, "Possible": 2, "Thin": 3, "": 4}


def xbox_outlook(cx: Context, g: Game) -> dict:
    """When a Game Pass game could leave and how likely, any distance ahead (the watchlist
    stops at the horizon)."""
    why = cx.excluded(g)
    if why:
        return {"state": "not scored", "wave": None, "p": None, "band": "", "why": f"{why}: assumed to stay"}
    if cx.is_ubisoft(g):
        return {"state": "not scored", "wave": None, "p": None, "band": "", "why": "Ubisoft+ Classics bundle"}
    if g.months is None:
        return {"state": "not scored", "wave": None, "p": None, "band": "", "why": "No add date"}
    added = cx.added(g)
    nxt = model.next_checkpoint(added, cx.today, cx.cohorts, cx.dpm, cx.announced)
    if not nxt:
        return {"state": "none left", "wave": None, "p": None, "band": "",
                "why": f"Past {cx.cohorts[-1]} months, no checkpoint left in the model"}
    n, wave = nxt
    p, reasons = cx.score(g, n, wave)
    anniv = model.anniversary(added, n, cx.dpm)
    return {"state": "scored", "wave": wave, "n": n, "p": p, "band": model.band(p, cx.cfg["bands"]),
            "why": "; ".join([f"{n}-month anniversary {fmt(anniv, cx.today)}"] + reasons)}


def one_service_rows(cx: Context, confirmed: list[dict], ps: dict | None) -> dict:
    """Games you can play on exactly one service (Game Pass console, or PS Plus at your tier)
    and don't own (Steam, PlayStation, disc). Confirmed leavers and claim deadlines first, then Likely,
    Possible and Thin, each soonest first."""
    today, play = cx.today, cx.play
    ps_games = ps["games"] if ps else []
    pm = ps_matcher(ps_games, cx.cfg) if ps_games else None
    on_xbox = {g.key: g for g in cx.by_key.values() if g.status in ("Active", "Leaving Soon")}
    conf = {r["key"]: r for r in confirmed if r["verified"]}
    # The same game on both services. A copy that is itself leaving is no backup, so then
    # both copies stay on the list.
    ps_leaving = {g.key for g in ps_games if g.status == "Leaving Soon"}
    both = {k: pk for k, pk in ((g.key, pm.key(g.name, loose=False)) for g in on_xbox.values()) if pk} if pm else {}
    xbox_backup = {k for k, pk in both.items() if pk not in ps_leaving}   # Game Pass games safe on PS Plus
    ps_backup = {pk for k, pk in both.items() if k not in conf}           # PS Plus games safe on Game Pass
    owned_ps = {pm.key(r.get("name") or "", loose=False) for r in cx.owned.values()} if pm else set()
    claimed_ps = {pm.key(n, loose=False) for n in cx.claimed} if pm else set()
    rows = []

    playing_ps = {}
    if pm:
        for r in cx.playing.values():
            k = pm.key(r["name"], loose=False)
            if k:
                playing_ps.setdefault(k, r)

    def add(game, service, out, hours, platform, progress=""):
        wave = out["wave"]
        if out["state"] == "claim":
            act = f"Claim by {fmt(wave, today)}"
        elif wave:
            act = model.urgency(today, wave, hours, play)
        else:
            act = ""
        rows.append({
            "game": game, "service": service, "platform": platform, "state": out["state"],
            "wave": wave.isoformat() if wave else "", "leaves": fmt(wave, today) if wave else "",
            "p": round(out["p"], 3) if out["p"] is not None else None,
            "odds": "Confirmed" if out["band"] == "Confirmed" else
                    (f"{round(out['p'] * 100)}%" if out["p"] is not None else ""),
            "band": out["band"], "hours": hours, "action": act, "why": out["why"], "progress": progress,
        })

    skipped = {"owned": 0, "both": 0, "claimed": 0, "finished": 0}
    for key, g in on_xbox.items():
        if key in cx.owned:
            skipped["owned"] += 1
            continue
        if key in xbox_backup:
            skipped["both"] += 1
            continue
        if key in conf:
            c = conf[key]
            out = {"state": "confirmed", "wave": date.fromisoformat(c["wave"]), "p": 1.0, "band": "Confirmed",
                   "why": c["note"]}
        else:
            out = xbox_outlook(cx, g)
        add(g.name, "Game Pass", out, g.hours, g.system)
    waves_out = plus.announced(ps_games, today)
    for g in ps_games:
        if g.key in owned_ps:
            skipped["owned"] += 1
            continue
        if g.kind == "essential" and g.key in claimed_ps:
            skipped["claimed"] += 1
            continue  # already claimed: yours while you subscribe
        if g.key in ps_backup:
            continue  # counted once, on the Game Pass side
        hours, progress = g.hours, ""
        r = playing_ps.get(g.key)
        if r and (r.get("share") or 0) >= 1:
            skipped["finished"] += 1
            continue  # every trophy earned: nothing left to lose
        if r and (r.get("played_h") or r.get("share")):
            hours = model.remaining_hours(g.hours, r.get("played_h"), r.get("share"))
            bits = [f"{r['played_h']:g} h played"] if r.get("played_h") else []
            if r.get("share") is not None:
                bits.append(f"{round(r['share'] * 100)}% of trophies")
            if r.get("hard"):
                bits.append(r["hard"])
            progress = ", ".join(bits)
        add(g.name, f"PS Plus {g.tier}", plus.outlook(g, today, cx.cfg, waves_out), hours, g.system, progress)
    rows.sort(key=lambda r: (ORDER[r["band"]], r["wave"] or "9999", -(r["p"] or 0), r["game"].lower()))
    tier = ps["tier"] if ps else "none"
    return {"rows": rows, "ps_tier": tier, "skipped_owned": skipped["owned"], "skipped_both": skipped["both"],
            "skipped_claimed": skipped["claimed"], "skipped_finished": skipped["finished"]}


def new_leavers(confirmed: list[dict], before: set[str] | None) -> list[dict]:
    """Verified leavers you don't own that the previous ingest didn't list: what the push alerts on.
    No previous ingest (None) alerts on nothing, so a first run doesn't flood the phone."""
    if before is None:
        return []
    return [r for r in confirmed if r["verified"] and not r["owned"] and r["key"] not in before]


def _in_days(n: int) -> str:
    return "today" if n <= 0 else "tomorrow" if n == 1 else f"in {n} days"


def leaver_alert(rows: list[dict], today: date, show: int = 4) -> tuple[str, str]:
    """Push title and body for newly confirmed leavers (Pharos style: short, relative times)."""
    days = sorted({(date.fromisoformat(r["wave"]) - today).days for r in rows})
    when = _in_days(days[0]) if len(days) == 1 else "starting " + _in_days(days[0])
    who = rows[0]["game"] if len(rows) == 1 else f"{len(rows)} games"
    items = [f"{r['game']} {r['hours']:g} h, {r['verdict'].lower()}" if r["hours"] is not None
             else f"{r['game']} hours unknown" for r in rows[:show]]
    if len(rows) > show:
        items.append(f"+{len(rows) - show} more")
    return f"{who} confirmed leaving {when}", " · ".join(items)


def alerts_due(queue: list[dict], today: date, cfg: dict, sent: set[tuple[str, str, str]],
               skip: set[str] = frozenset()) -> list[dict]:
    """Queued games with a push due that hasn't gone out: each game's current stage only
    (model.queue_stage), keyed (game, wave, stage) so it fires once. Owned games, modelled odds
    under [alerts] min_p and games in `skip` (already in today's leaver push) stay quiet."""
    a, seen, due = cfg["alerts"], set(), []
    for r in queue:
        if not r["wave"] or r["owned"] or r["p"] is None or r["p"] < a["min_p"] or r["key"] in skip | seen:
            continue
        seen.add(r["key"])
        wave = date.fromisoformat(r["wave"])
        stage = model.queue_stage(today, wave, r["hours"], cfg["play"], a["lead_days"])
        if stage and (r["key"], r["wave"], stage) not in sent:
            fits = r["hours"] is None or r["hours"] <= model.hours_available(today, wave, cfg["play"]["hours_per_week"])
            sb = model.start_by(wave, r["hours"] or 0, cfg["play"])
            due.append({**r, "stage": stage, "start_on": sb.isoformat(), "fits": fits})
    due.sort(key=lambda r: r["start_on"])
    return due


def queue_alert(rows: list[dict], today: date, show: int = 4) -> tuple[str, str]:
    """Push title and body for queued games to start (Pharos style: short, relative times)."""
    def when(r):
        return "now" if r["stage"] == "start" else _in_days((date.fromisoformat(r["start_on"]) - today).days)

    if len(rows) == 1:
        r = rows[0]
        wave = fmt(date.fromisoformat(r["wave"]), today)
        leaves = f"leaves {wave}" if r["p"] == 1.0 else f"{round(r['p'] * 100)}% it leaves {wave}"
        hours = "hours unknown" if r["hours"] is None else f"{r['hours']:g} h" + ("" if r["fits"] else ", too long to finish")
        return f"Start {r['game']} {when(r)}", f"{hours} · {leaves}"
    now = sum(r["stage"] == "start" for r in rows)
    title = f"{len(rows)} queued games to start " + ("now" if now == len(rows) else "soon")
    items = [f"{r['game']} {when(r)}" for r in rows[:show]]
    if len(rows) > show:
        items.append(f"+{len(rows) - show} more")
    return title, " · ".join(items)


def assemble(cfg: dict, sheet: Sheet, forecast: dict, steam: dict, today: date, as_of: date,
             ps: dict | None = None, psn: dict | None = None) -> dict:
    cx = Context(cfg, sheet, forecast, steam, today, as_of, psn)
    confirmed = confirmed_rows(cx)
    cx.announced = {date.fromisoformat(r["wave"]) for r in confirmed if r["verified"]}
    watch_all, survivors, ubisoft = scored_rows(cx, {r["key"] for r in confirmed})
    watch = [r for r in watch_all if not r["owned"]]
    owned = ([{"game": r["game"], "where": f"Leaving {r['wave_label']}", "hours": r["hours"], "progress": r["progress"]}
              for r in confirmed if r["owned"]] +
             [{"game": r["game"], "where": f"{r['band']} · {r['wave_label']}", "hours": r["hours"], "progress": r["progress"]}
              for r in watch_all if r["owned"]])
    return {
        "today": today.isoformat(),
        "summary": summary(cx, confirmed, watch_all),
        "confirmed": confirmed,
        "waves": wave_rows(cx, confirmed, watch_all),
        "watchlist": watch,
        "owned": owned,
        "queue": queue_rows(cx, confirmed),
        "survivors": survivors,
        "ubisoft": ubisoft,
        "calibration": calibration_rows(cx),
        "one_service": one_service_rows(cx, confirmed, ps),
        "sources": {
            "sheet_fetched": sheet.fetched,
            "forecast_checked": forecast.get("checked_at"),
            "forecast_covers": forecast.get("covers", []),
            "forecast_sources": forecast.get("sources", []),
            "steam_synced": steam.get("synced_at"),
            "ps_sheet_fetched": ps["fetched"] if ps else None,
            "psn_synced": psn.get("synced_at") if psn else None,
        },
    }
