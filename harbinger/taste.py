"""For you: a 1-5 guess at the stars you'd give a game, learned from the stars in your own notes.

Each review score (Metacritic `mc`, PlayStation user score `us`, Steam % positive `rating`) is put
on one scale (standard deviations from the library's average for that score), then blended with
`[taste] weights`; a game missing a score uses the weights of the ones it has. A straight line is
fitted on the games you rated:

    stars = a + b * blend + c * ln(hours to 100%)

and every game with at least one review score gets `taste` (one decimal, 1 to 5). Hours past
`[taste] hours_cap` count as the cap (a 600-hour live game is not 15x better than a 40-hour one); a
game with no hours uses the average of the games you rated. Refitted on every build, so it follows your
ratings as they grow; under `[taste] min_rated` rated games there is no score at all.

Why length: on the owner's 208 rated games (2026-10-11) review scores alone barely beat guessing
your average (Spearman ~0.15), and longer games were rated higher (~0.23). Together they cut the
leave-one-out error from 0.72 to 0.67 stars.
"""

from __future__ import annotations

import math

SOURCES = ("mc", "us", "rating")
DEFAULTS = {"enabled": True, "min_rated": 30, "hours_cap": 40, "weights": {"mc": 0.3, "us": 0.6, "rating": 0.1}}


def settings(cfg: dict) -> dict:
    f = {**DEFAULTS, **cfg.get("taste", {})}
    f["weights"] = {**DEFAULTS["weights"], **f.get("weights", {})}
    return f


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def spread(rows: list[dict]) -> dict[str, tuple[float, float]]:
    """{source: (mean, sd)} over every row that has the score."""
    out = {}
    for s in SOURCES:
        v = [x for r in rows if (x := _num(r.get(s))) is not None]
        if len(v) >= 2:
            m = sum(v) / len(v)
            sd = math.sqrt(sum((x - m) ** 2 for x in v) / len(v))
            if sd > 0:
                out[s] = (m, sd)
    return out


def blend(row: dict, weights: dict[str, float], sp: dict) -> float | None:
    have = [(weights[s], (x - sp[s][0]) / sp[s][1]) for s in SOURCES
            if s in sp and weights.get(s, 0) > 0 and (x := _num(row.get(s))) is not None]
    if not have:
        return None
    return sum(w * z for w, z in have) / sum(w for w, _ in have)


def _hours(row: dict, cap: float) -> float | None:
    h = _num(row.get("hours"))
    return math.log(min(h, cap)) if h and h > 0 else None


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None when the system is singular."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-9:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit(rows: list[dict], cfg: dict) -> dict | None:
    """{coef: [a, b, c], hours: neutral ln hours, rated: n, spread} from the rows carrying `stars`
    and a blend; None when off or too few."""
    s = settings(cfg)
    if not s["enabled"]:
        return None
    sp = spread(rows)
    train = [(b, _hours(r, s["hours_cap"]), r["stars"]) for r in rows
             if r.get("stars") and (b := blend(r, s["weights"], sp)) is not None]
    if len(train) < s["min_rated"]:
        return None
    logs = [h for _, h, _ in train if h is not None]
    neutral = sum(logs) / len(logs) if logs else 0.0
    xs = [(1.0, b, h if h is not None else neutral) for b, h, _ in train]
    ys = [y for *_, y in train]
    ata = [[sum(x[i] * x[j] for x in xs) for j in range(3)] for i in range(3)]
    aty = [sum(x[i] * y for x, y in zip(xs, ys)) for i in range(3)]
    if not logs or len(set(logs)) < 2:  # no length to learn from: blend only
        coef = _solve([r[:2] for r in ata[:2]], aty[:2])
        coef = coef + [0.0] if coef else None
    else:
        coef = _solve(ata, aty)
    if not coef:
        return None
    return {"coef": coef, "hours": neutral, "cap": s["hours_cap"], "rated": len(train), "spread": sp, "weights": s["weights"]}


def predict(row: dict, model: dict) -> float | None:
    b = blend(row, model["weights"], model["spread"])
    if b is None:
        return None
    h = _hours(row, model["cap"])
    a, kb, kh = model["coef"]
    return round(min(5.0, max(1.0, a + kb * b + kh * (h if h is not None else model["hours"]))), 1)


def attach(rows: list[dict], cfg: dict) -> dict | None:
    """Set `taste` on every row with a review score; returns the page's summary ({rated}) or None.
    Your own `stars` are dropped from the rows here: they train the fit but are never published."""
    model = fit(rows, cfg)
    for r in rows:
        r.pop("stars", None)
        if model and (p := predict(r, model)) is not None:
            r["taste"] = p
    return {"rated": model["rated"]} if model else None
