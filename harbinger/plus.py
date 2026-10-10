"""PS Plus: what your tier can play, what is confirmed to leave, and the odds the rest go.

Reads the imported PS Plus sheet (`sheet_row` where service = 'playstation'). Your tier is
`[playstation] tier` (none | essential | extra | premium; each includes the ones below it).
Pure functions: rows in, dicts out.

- Extra and Premium games leave on a wave: the third Monday of the month. A Leaving Soon game
  has its exact date on the sheet. The rest are scored like Game Pass: base rate by anniversary
  cohort ([playstation.base_rates.<family>], measured from the sheet), no forecast signals.
- Essential monthly games are claim-to-keep: the date is a claim deadline, not a play deadline.
- Ubisoft+ Classics (Extra) are not scored, like on Game Pass.
- Sony first-party games (titles.toml [first_party] playstation) use their own base rates
  ([playstation.base_rates.sony]): they almost never leave at an anniversary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from . import model
from .sheet import norm

TIERS = {"none": 0, "essential": 1, "extra": 2, "premium": 3}
CAL = "playstation"


def family(tier: str | None) -> str | None:
    """'Extra (Ubisoft+ Classics)' -> 'extra'. Discontinued tiers (PS Now, old PS Plus) -> None."""
    t = (tier or "").lower()
    for f in ("essential", "extra", "premium"):
        if t.startswith(f):
            return f
    return None


def first_party(cfg: dict) -> set[str]:
    """Sony's own games, as sheet keys (titles.toml [first_party] playstation)."""
    return {norm(t) for t in cfg.get("titles", {}).get("first_party", {}).get("playstation", [])}


def vr_only(cfg: dict) -> set[str]:
    """VR-only games outside the Premium (VR) sub-tier (titles.toml [vr_only] playstation)."""
    return {norm(t) for t in cfg.get("titles", {}).get("vr_only", {}).get("playstation", [])}


def kind(tier: str | None) -> str | None:
    """Which base-rate table a tier uses: extra, premium (Classics/Remasters/VR), streaming,
    ubisoft (never scored), essential (claim-to-keep)."""
    t = (tier or "").lower()
    f = family(tier)
    if f == "extra":
        return "ubisoft" if "ubisoft" in t else "extra"
    if f == "premium":
        return "streaming" if "streaming" in t else "premium"
    return f


def _iso(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _f(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


@dataclass
class PsGame:
    name: str
    key: str
    system: str
    tier: str
    kind: str
    status: str
    added: date | None
    removed: date | None
    hours: float | None
    metacritic: float | None = None
    user_score: float | None = None  # the sheet's PlayStation user score, 0..10
    genre: str = ""
    release: str = ""


def catalogue(tabs: dict[str, list[dict]], your_tier: str, first_party=frozenset(),
              hide_vr: bool = False, vr_only=frozenset()) -> list[PsGame]:
    """Master List games on the service now (Active or Leaving Soon) that your tier includes.
    A game with several stints counts once, as its newest stint. Keys in `first_party` (Sony's
    own games) on Extra or Premium get kind "sony". `hide_vr` drops VR-only games: the Premium
    (VR) sub-tier and the keys in `vr_only`; games with an optional VR mode stay."""
    rank = TIERS.get((your_tier or "none").lower(), 0)
    newest: dict[str, dict] = {}
    for r in tabs.get("master", []):
        if r.get("status") not in ("Active", "Leaving Soon"):
            continue
        if hide_vr and ("(vr)" in (r.get("tier") or "").lower() or norm(r["title"]) in vr_only):
            continue
        f = family(r.get("tier"))
        if not f or TIERS[f] > rank:
            continue
        if r["key"] not in newest or str(r.get("added") or "") > str(newest[r["key"]].get("added") or ""):
            newest[r["key"]] = r
    def kind_of(r):
        k = kind(r.get("tier"))
        return "sony" if k in ("extra", "premium") and norm(r["title"]) in first_party else k

    return [PsGame(name=r["title"], key=norm(r["title"]), system=r.get("system") or "", tier=r.get("tier") or "",
                   kind=kind_of(r), status=r["status"], added=_iso(r.get("added")),
                   removed=_iso(r.get("removed")), hours=r.get("completion_h") if isinstance(r.get("completion_h"), float) else None,
                   metacritic=_f(r.get("metacritic")), user_score=_f(r.get("user_score")), genre=r.get("genre") or "",
                   release=str(r.get("release") or ""))
            for r in newest.values()]


def announced(games: list[PsGame], today: date) -> set[date]:
    """Waves whose leaving list is out: unnamed games on them survived."""
    return {g.removed for g in games if g.status == "Leaving Soon" and g.removed and g.removed >= today}


def outlook(g: PsGame, today: date, cfg: dict, waves_out: set[date]) -> dict:
    """When this game could leave and how likely: state confirmed | claim | scored | not scored | none left."""
    ps = cfg["playstation"]
    dpm = cfg["sheet"]["days_per_month"]
    if g.status == "Leaving Soon" and g.removed and g.removed >= today:
        state = "claim" if g.kind == "essential" else "confirmed"
        return {"state": state, "wave": g.removed, "p": 1.0, "band": "Confirmed",
                "why": "Claim it to keep it" if state == "claim" else "On the PS Plus sheet's Leaving Soon tab"}
    if g.kind == "ubisoft":
        return {"state": "not scored", "wave": None, "p": None, "band": "", "why": "Ubisoft+ Classics bundle"}
    if g.kind == "essential" or g.added is None:
        return {"state": "not scored", "wave": None, "p": None, "band": "", "why": "No add date"}
    nxt = model.next_checkpoint(g.added, today, ps["cohorts"], dpm, frozenset(waves_out), cal=CAL)
    if not nxt:
        return {"state": "none left", "wave": None, "p": None, "band": "",
                "why": f"Past {ps['cohorts'][-1]} months, no checkpoint left in the model"}
    n, wave = nxt
    p = ps["base_rates"][g.kind][str(n)]
    anniv = model.anniversary(g.added, n, dpm)
    rate = ("Sony game: these leave mostly before a new entry or remaster goes on sale" if g.kind == "sony"
            else f"{g.tier} base rate")
    return {"state": "scored", "wave": wave, "n": n, "p": p, "band": model.band(p, cfg["bands"]),
            "why": f"{n}-month anniversary {anniv:%b} {anniv.day}; {rate}"}
