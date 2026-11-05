"""Elo ratings, power rankings and head-to-head, recomputed from scratch on every export.

Per game: each day, every pair of players who both posted is one match. The winner's
score is 0.6-1.0 depending on margin (scaled by that game's typical within-day spread),
so a blowout counts more than a squeaker without one outlier swinging everything.
Overall: per-game ratings shrunk toward START by sample size, weighted by sqrt(days played).
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from itertools import permutations

START = 1500.0
K, K_PROV = 32.0, 48.0
PROV_N = 5            # game-days before a per-game rating is settled
OVERALL_PROV_N = 10   # total game-days before the overall rating is settled
SHRINK = 5            # pseudo-days pulling each game's rating toward START in the overall
HALF_LIFE = 7.0       # days, for power-ranking form
PRIOR_W = 1.5         # pseudo-days at 0.5 percentile so one great day can't top the list
MIN_RECENT = 3        # game-days in the last RECENT_DAYS to be ranked in power
RECENT_DAYS = 14
UPSET_E = 0.35


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _sigma(rows: list[dict]) -> float:
    """Pooled within-day standard deviation of non-failed scores, floored at 1."""
    by_day = defaultdict(list)
    for r in rows:
        if not r["f"]:
            by_day[r["d"]].append(r["s"])
    ss = dof = 0.0
    for xs in by_day.values():
        if len(xs) > 1:
            m = sum(xs) / len(xs)
            ss += sum((x - m) ** 2 for x in xs)
            dof += len(xs) - 1
    return max(1.0, math.sqrt(ss / dof)) if dof else 1.0


def outcome(a: dict, b: dict, direction: str, sigma: float) -> float:
    """Score in [0, 1] for a vs b. Fails lose to any real score."""
    if a["f"] or b["f"]:
        return 0.5 if a["f"] and b["f"] else (0.0 if a["f"] else 1.0)
    d = a["s"] - b["s"] if direction == "higher" else b["s"] - a["s"]
    if d == 0:
        return 0.5
    return 0.5 + math.copysign(0.1 + 0.4 * min(1.0, abs(d) / (2 * sigma)), d)


def _overall(R: dict, n: dict, pid: str) -> float | None:
    num = den = 0.0
    for (p, g), k in n.items():
        if p == pid and k:
            w = math.sqrt(k)
            num += w * (START + (R[p, g] - START) * k / (k + SHRINK))
            den += w
    return num / den if den else None


def _form(pcts: list[tuple[dt.date, float]], at: dt.date) -> float:
    num, den = PRIOR_W * 0.5, PRIOR_W
    for day, pct in pcts:
        if day <= at:
            w = 0.5 ** ((at - day).days / HALF_LIFE)
            num += w * pct
            den += w
    return num / den


def compute(results: list[dict], games: dict[str, dict]) -> dict:
    days = sorted({r["d"] for r in results})
    if not days:
        return {"days": [], "overall": {}, "games": {}, "power": [], "h2h": {}, "extras": {}}
    by_game_day = defaultdict(list)
    by_game = defaultdict(list)
    seen = set()
    for r in results:
        # Two puzzles of one game can land on the same day; rate only the first so nobody plays themselves.
        if (r["p"], r["g"], r["d"]) in seen:
            continue
        seen.add((r["p"], r["g"], r["d"]))
        by_game_day[r["g"], r["d"]].append(r)
        by_game[r["g"]].append(r)
    sigma = {g: _sigma(rows) for g, rows in by_game.items()}
    players = sorted({r["p"] for r in results})

    R = defaultdict(lambda: START)
    n = defaultdict(int)
    hist_g = defaultdict(list)       # (p, g) -> rating per day (None before first play)
    hist_o = defaultdict(list)       # p -> overall per day
    pcts = defaultdict(list)         # p -> [(date, daily percentile vs field)]
    h2h = defaultdict(lambda: [0, 0, 0])   # (p, opp) -> [w, l, t]
    upsets = []

    for day in days:
        for g, meta in games.items():
            rows = by_game_day.get((g, day), [])
            N = len(rows)
            if N < 2:
                continue
            delta, won = defaultdict(float), defaultdict(float)
            for a, b in permutations(rows, 2):
                S = outcome(a, b, meta["direction"], sigma[g])
                E = 1 / (1 + 10 ** ((R[b["p"], g] - R[a["p"], g]) / 400))
                k = K_PROV if n[a["p"], g] < PROV_N else K
                delta[a["p"]] += k / (N - 1) * (S - E)
                won[a["p"]] += 1.0 if S > 0.5 else 0.5 if S == 0.5 else 0.0
                h2h[a["p"], b["p"]][0 if S > 0.5 else 1 if S < 0.5 else 2] += 1
                if S > 0.5 and E < UPSET_E:
                    upsets.append({"d": day, "g": g, "w": a["p"], "l": b["p"], "e": round(E, 2)})
            # Applied after the loop so every pairing uses start-of-day ratings.
            for p, dlt in delta.items():
                R[p, g] += dlt
                n[p, g] += 1
                pcts[p].append((_date(day), won[p] / (N - 1)))
        for p in players:
            for g in games:
                hist_g[p, g].append(round(R[p, g]) if n[p, g] else None)
            o = _overall(R, n, p)
            hist_o[p].append(round(o) if o is not None else None)

    latest = _date(days[-1])

    def at_or_before(series: list, cutoff: dt.date):
        """Value on the last day <= cutoff; START if the player hadn't started yet."""
        for i in range(len(days) - 1, -1, -1):
            if _date(days[i]) <= cutoff:
                return series[i] if series[i] is not None else round(START)
        return round(START)

    def entry(series: list, k: int, prov_n: int) -> dict:
        r = series[-1]
        return {"r": r, "n": k, "prov": k < prov_n,
                "d7": r - at_or_before(series, latest - dt.timedelta(days=7)), "hist": series}

    out_games = {}
    for g in games:
        rows = {p: entry(hist_g[p, g], n[p, g], PROV_N) for p in players if n[p, g]}
        if rows:
            out_games[g] = rows
    total_n = {p: sum(k for (q, _), k in n.items() if q == p) for p in players}
    overall = {p: entry(hist_o[p], total_n[p], OVERALL_PROV_N) for p in players if hist_o[p][-1] is not None}

    def power_at(at: dt.date) -> dict[str, dict]:
        idx = max(i for i, d in enumerate(days) if _date(d) <= at)
        rows = []
        for p in overall:
            recent = sum(1 for d, _ in pcts[p] if at - dt.timedelta(days=RECENT_DAYS) < d <= at)
            o = hist_o[p][idx]
            if recent < MIN_RECENT or o is None:
                continue
            form = _form(pcts[p], at)
            rows.append({"p": p, "power": round(0.5 * o + 0.5 * (START + 800 * (form - 0.5))), "form": round(form, 3)})
        rows.sort(key=lambda x: -x["power"])
        for i, x in enumerate(rows):
            x["rank"] = i + 1
        return {x["p"]: x for x in rows}

    now = power_at(latest)
    week_ago = latest - dt.timedelta(days=7)
    prev = power_at(week_ago) if _date(days[0]) <= week_ago else {}
    power = [dict(x, prev_rank=prev[p]["rank"] if p in prev else None) for p, x in now.items()]

    two_weeks = latest - dt.timedelta(days=14)
    improved = sorted(({"p": p, "delta": o["r"] - at_or_before(o["hist"], two_weeks)} for p, o in overall.items()),
                      key=lambda x: -x["delta"])
    field = {}
    for p in players:
        xs = [v for _, v in pcts[p]]
        if xs:
            m = sum(xs) / len(xs)
            sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else None
            w = sum(v[0] for (a, _), v in h2h.items() if a == p)
            l = sum(v[1] for (a, _), v in h2h.items() if a == p)
            t = sum(v[2] for (a, _), v in h2h.items() if a == p)
            field[p] = {"pct": round((w + 0.5 * t) / (w + l + t), 3), "sd": round(sd, 3) if sd is not None else None,
                        "days": len(xs)}
    out_h2h = defaultdict(dict)
    for (a, b), v in h2h.items():
        out_h2h[a][b] = v
    upsets.sort(key=lambda u: (u["e"], u["d"]))

    return {
        "days": days,
        "overall": overall,
        "games": out_games,
        "power": power,
        "h2h": dict(out_h2h),
        "extras": {"most_improved": improved, "field": field, "upsets": upsets[:10]},
    }
