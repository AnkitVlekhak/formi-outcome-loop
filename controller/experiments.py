"""Variant experiments on welcome message and voice (C6) with promotion,
holdout and decay rollback (C7).

Design
------
* welcome_message and voice are randomised independently per call, so they run
  as a factorial: each dimension's arms are compared marginalising over the other.
  They are heard only after pickup, so the metric is engagement (engaged/connected);
  pickup is checked as a guardrail anyway.
* Exploration: incumbent keeps the bulk; each challenger starts at 10% (sized so
  a -10% arm costs <1% expected engagement — the "harmful change" line).
* Daily looks (<= ~8 per experiment). Winner: z >= 2.9 one-sided vs incumbent,
  >= 400 connected per arm, >= 2 days, last day not reversing, pickup guardrail ok.
  Bonferroni over 8 looks x 3 challengers bounds the family-wise false-winner
  rate at ~4.5% (verified by an A/A eval in tests).
* Harm stop: z <= -1.5 with >= 300 connected removes the arm.
* Promotion keeps a 10% holdout on the old incumbent, so decay is measurable.
* Decay: winner's own engagement now vs during the experiment (high power),
  confirmed by the holdout (difference-in-differences) so global drift (e.g. a
  prompt change hitting every arm) does not trigger a rollback.
"""
from __future__ import annotations

import numpy as np

from . import cells, stats

CHALLENGER_SHARE = 0.10
RAMP_SHARE = 0.20
MAX_CHALLENGERS = 3
HOLDOUT = 0.10
Z_WIN = 2.9
Z_WIN_COHORT = 3.2
Z_HARM = -1.5
Z_PROTECT = -1.64
N_MIN = 400
N_HARM = 300
MIN_DAYS = 2
Z_PICKUP_GUARD = -2.33
Z_DECAY = -3.0


def explore_alloc(arms, incumbent, dropped) -> dict:
    ch = [a for a in arms if a != incumbent and a not in dropped][:MAX_CHALLENGERS]
    out = {a: CHALLENGER_SHARE for a in ch}
    out[incumbent] = 1 - sum(out.values())
    return {a: round(w, 4) for a, w in out.items()}


def _tot(acc, mask=None, days=None):
    a = acc if days is None else acc[days]
    if days is not None and isinstance(days, int):
        a = a[None]
    if mask is not None:
        a = a[:, :, mask, :]
    return a.sum(axis=(0, 2))  # [arms, 3]


def arm_stats(acc, arms, incumbent, mask=None, days_running=None):
    T = _tot(acc, mask, slice(0, days_running) if days_running else None)
    i = arms.index(incumbent)
    out = {}
    for k, a in enumerate(arms):
        dials, conn, eng = (int(x) for x in T[k])
        rec = {"dials": dials, "conn": conn, "eng": eng, "eng_rate": round(eng / conn, 4) if conn else None,
               "pickup": round(conn / dials, 4) if dials else None}
        if a != incumbent:
            rec["z"] = round(stats.two_prop_z(eng, conn, T[i][2], T[i][1]), 3)
            rec["z_pickup"] = round(stats.two_prop_z(conn, dials, T[i][1], T[i][0]), 3)
            d, se = stats.diff_se(eng, conn, T[i][2], T[i][1])
            rec["lift_abs"], rec["se"] = round(d, 4), round(se, 4)
        out[a] = rec
    return out


def _recent_ok(acc, arms, a, incumbent, mask, day):
    if day < 0:
        return True
    T = _tot(acc, mask, day)
    ia, ii = arms.index(a), arms.index(incumbent)
    if T[ia][1] < 50 or T[ii][1] < 50:
        return True
    return T[ia][2] / T[ia][1] - T[ii][2] / T[ii][1] >= 0


Z_HARM_RECENT = -2.0
RECENT_DAYS = 2


def _recent_z(acc, arms, a, incumbent, mask, days_running):
    lo = max(days_running - RECENT_DAYS, 0)
    if days_running - lo < 1:
        return None, 0
    T = _tot(acc, mask, slice(lo, days_running))
    ia, ii = arms.index(a), arms.index(incumbent)
    if T[ia][1] < N_HARM or T[ii][1] < N_HARM:
        return None, int(T[ia][1])
    return stats.two_prop_z(T[ia][2], T[ia][1], T[ii][2], T[ii][1]), int(T[ia][1])


def look(acc, arms, incumbent, days_running, scope_mask=None, dropped=(), z_win=Z_WIN) -> dict:
    """Harm is checked on the whole test AND on the last RECENT_DAYS, because a variant
    can decay with exposure: cumulative numbers keep an early winner looking good."""
    st = arm_stats(acc, arms, incumbent, scope_mask, days_running)
    for a in arms:
        if a != incumbent:
            zr, nr = _recent_z(acc, arms, a, incumbent, scope_mask, days_running) if days_running >= 3 else (None, 0)
            st[a]["z_recent"] = None if zr is None else round(zr, 3)
    inc = st[incumbent]
    cands = []
    newly_dropped = []
    for a in arms:
        if a == incumbent or a in dropped:
            continue
        s = st[a]
        if (s["conn"] >= N_HARM and inc["conn"] >= N_HARM and s["z"] <= Z_HARM) or \
                (s.get("z_recent") is not None and s["z_recent"] <= Z_HARM_RECENT):
            newly_dropped.append(a)
            continue
        if (s["z"] >= z_win and s["conn"] >= N_MIN and inc["conn"] >= N_MIN and days_running >= MIN_DAYS
                and s["z_pickup"] > Z_PICKUP_GUARD
                and _recent_ok(acc, arms, a, incumbent, scope_mask, days_running - 1)):
            cands.append(a)
    if cands:
        w = max(cands, key=lambda a: st[a]["z"])
        return {"action": "promote", "winner": w, "alloc": {w: 1 - HOLDOUT, incumbent: HOLDOUT},
                "stats": st, "dropped": newly_dropped,
                "rule": f"z>={z_win}, n>={N_MIN}/arm, >={MIN_DAYS} days, last day not reversed, pickup guard"}
    all_dropped = set(dropped) | set(newly_dropped)
    alloc = {}
    for a in arms:
        if a == incumbent or a in all_dropped:
            continue
        s = st[a]
        recent_ok = s.get("z_recent") is None or s["z_recent"] >= 0
        alloc[a] = RAMP_SHARE if (s["conn"] >= N_HARM and s.get("z", 0) > 0 and recent_ok) else CHALLENGER_SHARE
    alloc = dict(list(alloc.items())[:MAX_CHALLENGERS])
    tot = sum(alloc.values())
    if tot > 0.6:
        alloc = {a: w * 0.6 / tot for a, w in alloc.items()}
    alloc[incumbent] = 1 - sum(alloc.values())
    return {"action": "ramp", "winner": None, "alloc": {a: round(w, 4) for a, w in alloc.items()},
            "stats": st, "dropped": newly_dropped,
            "rule": f"harm stop z<={Z_HARM} (whole test) or z<={Z_HARM_RECENT} (last {RECENT_DAYS} days), n>={N_HARM}"}


def cohort_split(acc, arms, incumbent, winner, cohorts, days_running) -> dict:
    """Per-cohort refinement on the shared partition: protect cohorts a global
    winner hurts; promote a cohort-specific winner at a stricter threshold."""
    out = {}
    for cid, mask in cells.cohort_masks(cohorts):
        if cid == "default" or not mask.any():
            continue
        st = arm_stats(acc, arms, incumbent, mask, days_running)
        rec = {"action": "keep", "stats": st}
        if winner and winner != incumbent:
            s = st[winner]
            if s["conn"] >= 200 and st[incumbent]["conn"] >= 200 and s["z"] <= Z_PROTECT:
                rec.update(action="protect", alloc={incumbent: 1.0},
                           reason=f"global winner {winner} is worse here (z={s['z']})")
                out[cid] = rec
                continue
        res = look(acc, arms, incumbent, days_running, mask, z_win=Z_WIN_COHORT)
        if res["action"] == "promote" and res["winner"] != winner:
            rec.update(action="promote", winner=res["winner"], alloc=res["alloc"],
                       reason=f"cohort-level winner at z>={Z_WIN_COHORT}")
        out[cid] = rec
    return out


def decay_check(acc, arms, winner, holdout, promote_day, today, mask=None) -> dict:
    """promote_day/today are experiment-relative day indices; uses full days only."""
    if today - promote_day < 1:
        return {"rollback": False, "reason": "not enough post-promotion data"}
    exp_days = slice(0, max(promote_day, 1))
    rec_days = slice(max(promote_day, today - 2), today)
    E, R = _tot(acc, mask, exp_days), _tot(acc, mask, rec_days)
    iw, ih = arms.index(winner), arms.index(holdout)
    if R[iw][1] < 200 or E[iw][1] < 200:
        return {"rollback": False, "reason": "insufficient data"}
    z_within = stats.two_prop_z(R[iw][2], R[iw][1], E[iw][2], E[iw][1])
    dw = R[iw][2] / R[iw][1] - E[iw][2] / E[iw][1]
    dh = (R[ih][2] / R[ih][1] - E[ih][2] / E[ih][1]) if R[ih][1] and E[ih][1] else 0.0
    did = dw - dh
    z_vs_hold = stats.two_prop_z(R[iw][2], R[iw][1], R[ih][2], R[ih][1]) if R[ih][1] else 0.0
    rollback = bool(z_within <= Z_DECAY and did <= 0.5 * dw and z_vs_hold < 1.0)
    return {"rollback": rollback, "z_within": round(z_within, 2), "winner_drop": round(dw, 4),
            "holdout_drift": round(dh, 4), "diff_in_diff": round(did, 4), "z_vs_holdout_recent": round(z_vs_hold, 2),
            "rule": f"z_within<={Z_DECAY} and DiD<=0.5*drop and winner no longer clearly ahead of holdout"}
