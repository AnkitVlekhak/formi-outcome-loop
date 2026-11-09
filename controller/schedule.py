"""Call-time optimisation per cohort (C4, cohort level).

History before D0 dials every hour uniformly (no schedule), so the
(feature level x hour) pickup table is an unbiased estimate of who answers when.
We pick the single feature whose pickup profile varies most by hour (a
chi-square test of hour x level against independence), and give each level a
weight per hour proportional to its relative advantage at that hour.

Every hour of the dialling window gets a positive weight — an hour omitted from
a table gets weight 0 in the simulator and wastes capacity.
"""
from __future__ import annotations

import numpy as np

from . import cells, stats

GAMMA = 1.0
SHRINK_DIALS = 200
CLIP = (0.3, 3.0)
P_MAX = 1e-3
MIN_LEVEL_DIALS = 300


def _levels(f, langs):
    vals = cells.FEATURES[f]
    return [i for i, v in enumerate(vals) if f != "lang" or not langs or v in langs]


def _table(pick, f, window, langs):
    """dials/conn per (level, hour) -> arrays [L, H]."""
    lo, hi = window
    hours = list(range(lo, hi))
    levels = _levels(f, langs)
    D = np.zeros((len(levels), len(hours)))
    C = np.zeros_like(D)
    lv = cells.LEVEL[f]
    for li, l in enumerate(levels):
        m = lv == l
        for hi_, h in enumerate(hours):
            D[li, hi_] = pick[h, m, 0].sum()
            C[li, hi_] = pick[h, m, 1].sum()
    return levels, hours, D, C


def _expected(D, C):
    p_all = C.sum() / max(D.sum(), 1)
    p_l = C.sum(1, keepdims=True) / np.maximum(D.sum(1, keepdims=True), 1)
    p_h = C.sum(0, keepdims=True) / np.maximum(D.sum(0, keepdims=True), 1)
    return np.clip(p_l * p_h / max(p_all, 1e-9), 1e-6, 0.999)


def choose_feature(pick, window, langs=None):
    scores = {}
    for f in cells.ORDER:
        levels, hours, D, C = _table(pick, f, window, langs)
        keep = D.sum(1) >= MIN_LEVEL_DIALS
        if keep.sum() < 2:
            continue
        D, C = D[keep], C[keep]
        E = _expected(D, C)
        ok = D > 0
        chi2 = float((((C - D * E) ** 2) / (D * E * (1 - E) + 1e-12))[ok].sum())
        df = (D.shape[0] - 1) * (D.shape[1] - 1)
        scores[f] = {"chi2": round(chi2, 1), "df": df, "p": stats.chi2_sf(chi2, df),
                     "z": (chi2 - df) / np.sqrt(2 * df)}
    best = max(scores, key=lambda f: scores[f]["z"], default=None)
    if best is None or scores[best]["p"] > P_MAX:
        return None, scores
    return best, scores


def fit_weights(pick, f, window, langs=None) -> dict:
    levels, hours, D, C = _table(pick, f, window, langs)
    E = _expected(D, C)
    a = (C + SHRINK_DIALS * E) / ((D + SHRINK_DIALS) * E)
    w = np.clip(a ** GAMMA, *CLIP)
    w = w / w.mean(axis=1, keepdims=True)
    w = np.clip(w, *CLIP)
    ids = {c["where"][f][0]: c["id"] for c in cells.partition_cohorts([f], langs)}
    out = {}
    for li, l in enumerate(levels):
        out[ids[cells.FEATURES[f][l]]] = {str(h): round(float(w[li, hi_]), 3) for hi_, h in enumerate(hours)}
    return out


def dry_run(pick, f, weights, window, langs=None) -> dict:
    """Replay against the historical cohort table: at each hour the dialled mix is
    proportional to (level share x weight). Ignores pool depletion across hours,
    so it is an upper-bound-ish estimate; we say so in the proposal."""
    levels, hours, D, C = _table(pick, f, window, langs)
    E = _expected(D, C)
    P = (C + SHRINK_DIALS * E) / (D + SHRINK_DIALS)
    pi = D.sum(1) / max(D.sum(), 1)
    ids = {c["where"][f][0]: c["id"] for c in cells.partition_cohorts([f], langs)}
    W = np.ones_like(P)
    for li, l in enumerate(levels):
        tab = weights.get(ids[cells.FEATURES[f][l]], {})
        for hi_, h in enumerate(hours):
            W[li, hi_] = tab.get(str(h), 1.0)
    old = float(np.mean((pi[:, None] * P).sum(0) / pi.sum()))
    new = float(np.mean((pi[:, None] * W * P).sum(0) / (pi[:, None] * W).sum(0)))
    return {"method": "replay of pre-D0 history by cohort x hour, pool depletion ignored",
            "feature": f, "expected_pickup_old": round(old, 4), "expected_pickup_new": round(new, 4),
            "relative_uplift": round(new / old - 1, 4) if old else 0.0,
            "history_dials": int(D.sum())}
