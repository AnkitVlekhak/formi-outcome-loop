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
Z_GRADUATE = 1.64          # a probe graduates only when confidently above 0.8x its siblings


def assess(names, hours, lifetime, prior: dict) -> dict:
    """hours: [H, n_dids, 2] (dials, connected) per dialling hour, most recent LAST.
    Each number is compared with its siblings over the same hours. The window starts
    at WINDOW_HOURS and is extended (up to H) until the number has MIN_WINDOW_DIALS,
    so low-volume probes get judged on enough data instead of being waved through.

    Status transitions: unknown -> healthy only after a passed comparison
    (ratio >= RATIO_FLAG); any -> flagged on a significant, material shortfall;
    inconclusive keeps the previous status (probes stay probes)."""
    import numpy as np
    hours = np.asarray(hours)
    H = len(hours)
    out = {}
    for i, d in enumerate(names):
        life = int(lifetime[i][0])
        others = [j for j in range(len(names)) if j != i and prior.get(names[j]) != "flagged"]

        def enough(k):
            w = hours[H - k:]
            return w[:, i, 0].sum() >= MIN_WINDOW_DIALS and w[:, others, 0].sum() >= MIN_WINDOW_DIALS
        k = min(WINDOW_HOURS, H)
        while k < H and not enough(k):     # grow until BOTH the number and its reference have enough dials
            k += 1
        win = hours[H - k:].sum(axis=0) if H else np.zeros((len(names), 2))
        dials, conn = int(win[i][0]), int(win[i][1])
        rec = {"window_dials": dials, "window_conn": conn, "window_hours": k, "lifetime_dials": life,
               "rate": conn / dials if dials else None}
        if prior.get(d) == "flagged":
            rec["status"] = "flagged"
            out[d] = rec
            continue
        ref_d = int(sum(win[j][0] for j in others))
        ref_c = int(sum(win[j][1] for j in others))
        was = prior.get(d) or ("unknown" if life < MIN_LIFETIME_DIALS else "healthy")
        if dials >= MIN_WINDOW_DIALS and ref_d >= MIN_WINDOW_DIALS and ref_c > 0:
            z = stats.two_prop_z(conn, dials, ref_c, ref_d)
            ratio = (conn / dials) / (ref_c / ref_d)
            p, q = conn / dials, ref_c / ref_d
            se = (p * (1 - p) / dials + RATIO_FLAG ** 2 * q * (1 - q) / ref_d) ** 0.5
            z80 = (p - RATIO_FLAG * q) / se if se else 0.0      # one-sided: is it confidently above 0.8x?
            rec.update(z=round(z, 2), ratio=round(ratio, 3), ref_rate=round(q, 4), z_vs_0_8=round(z80, 2))
            if ratio < RATIO_FLAG and z <= Z_FLAG:
                rec["status"] = "flagged"
            elif was == "unknown":
                rec["status"] = "healthy" if z80 >= Z_GRADUATE else "unknown"
            else:
                rec["status"] = was
        else:
            rec["status"] = was
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
