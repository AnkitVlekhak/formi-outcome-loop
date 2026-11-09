"""Caller-ID health (C5).

Caller IDs are randomised per dial independently of who is dialled, so within a
time window the pickup rate per caller ID is directly comparable — no
mix-adjustment needed. A caller ID is flagged when it picks up materially and
significantly worse than its siblings in the same recent window.

Allocation policy: spread volume evenly across healthy numbers (concentrating
volume on one number degrades it — the industry rule is "cap volume per
number"), give never-measured numbers a small probe share, retire flagged ones.
"""
from __future__ import annotations

from . import stats

MIN_WINDOW_DIALS = 120     # per number, inside the detection window
MIN_LIFETIME_DIALS = 150   # below this a number is "unknown" and only probed
RATIO_FLAG = 0.80          # effect size: >=20% worse pickup than siblings
Z_FLAG = -3.5              # significance: ~2e-4 one-sided per number per look
PROBE_SHARE = 0.06         # per unknown number; sized so a bad probe stays under the 2% harm line
WINDOW_HOURS = 3


def assess(names, window, lifetime, prior: dict) -> dict:
    """window/lifetime: arrays [n_dids, 2] of (dials, connected)."""
    out = {}
    for i, d in enumerate(names):
        dials, conn = int(window[i][0]), int(window[i][1])
        life = int(lifetime[i][0])
        rec = {"window_dials": dials, "window_conn": conn, "lifetime_dials": life,
               "rate": conn / dials if dials else None}
        if prior.get(d) == "flagged":
            rec["status"] = "flagged"
            out[d] = rec
            continue
        ref_d = sum(int(window[j][0]) for j in range(len(names))
                    if j != i and prior.get(names[j]) != "flagged" and window[j][0] >= MIN_WINDOW_DIALS)
        ref_c = sum(int(window[j][1]) for j in range(len(names))
                    if j != i and prior.get(names[j]) != "flagged" and window[j][0] >= MIN_WINDOW_DIALS)
        if life < MIN_LIFETIME_DIALS:
            rec["status"] = "unknown"
        elif dials >= MIN_WINDOW_DIALS and ref_d >= MIN_WINDOW_DIALS and ref_c > 0:
            z = stats.two_prop_z(conn, dials, ref_c, ref_d)
            ratio = (conn / dials) / (ref_c / ref_d)
            rec.update(z=round(z, 2), ratio=round(ratio, 3), ref_rate=round(ref_c / ref_d, 4))
            rec["status"] = "flagged" if (ratio < RATIO_FLAG and z <= Z_FLAG) else "healthy"
        else:
            rec["status"] = prior.get(d) if prior.get(d) in ("healthy",) else "healthy"
        out[d] = rec
    return out


def target_allocation(status: dict) -> dict | None:
    healthy = [d for d, s in status.items() if s == "healthy"]
    unknown = [d for d, s in status.items() if s == "unknown"]
    if not healthy and not unknown:
        return None
    if not healthy:
        return {d: 1 / len(unknown) for d in unknown}
    probe = min(PROBE_SHARE * len(unknown), 0.3)
    out = {d: probe / len(unknown) for d in unknown} if unknown else {}
    for d in healthy:
        out[d] = (1 - probe) / len(healthy)
    return {d: round(w, 4) for d, w in out.items()}


def expected_relative_pickup(alloc: dict, status_detail: dict) -> float:
    """Dry run: pickup of an allocation relative to the best measured number."""
    rates = {d: r.get("rate") for d, r in status_detail.items() if r.get("rate")}
    if not rates:
        return 1.0
    best = max(rates.values())
    tot = 0.0
    for d, w in alloc.items():
        tot += w * (rates.get(d) or best) / best
    return tot
