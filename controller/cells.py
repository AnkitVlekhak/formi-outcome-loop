"""Feature cells: the atom every cohort is built from.

A lead's four features (lang, city_tier, age_band, value_band) map to one of
7*3*4*3 = 252 cells. All statistics are kept per cell, so any cohort — a set of
cells — can be evaluated after the fact without re-ingesting. This is the
"one shared cohort object": detection, experiments, config and the supervisor
view all refer to the same cell set via the same cohort id.
"""
from __future__ import annotations

import itertools

import numpy as np

FEATURES: dict[str, list[str]] = {
    "lang": ["hi", "en", "ta", "te", "kn", "mr", "bn"],
    "city_tier": ["1", "2", "3"],
    "age_band": ["18-30", "31-45", "46-60", "60+"],
    "value_band": ["low", "mid", "high"],
}
ORDER = ["lang", "city_tier", "age_band", "value_band"]
SIZES = [len(FEATURES[f]) for f in ORDER]
N_CELLS = int(np.prod(SIZES))
_IDX = {f: {v: i for i, v in enumerate(FEATURES[f])} for f in ORDER}


def encode(features: dict) -> int:
    c = 0
    for f, n in zip(ORDER, SIZES):
        c = c * n + _IDX[f][features[f]]
    return c


def decode(c: int) -> dict:
    out = {}
    for f, n in zip(reversed(ORDER), reversed(SIZES)):
        c, r = divmod(c, n)
        out[f] = FEATURES[f][r]
    return {f: out[f] for f in ORDER}


# LEVEL[f][cell] -> index of that cell's level for feature f
LEVEL: dict[str, np.ndarray] = {f: np.array([_IDX[f][decode(c)[f]] for c in range(N_CELLS)], dtype=np.int8)
                                for f in ORDER}


def where_mask(where: dict) -> np.ndarray:
    """Boolean mask over cells for a simulator `where` clause (AND across, OR within)."""
    m = np.ones(N_CELLS, dtype=bool)
    for f, vals in (where or {}).items():
        m &= np.isin(LEVEL[f], [_IDX[f][v] for v in vals])
    return m


_SAFE = {"18-30": "18_30", "31-45": "31_45", "46-60": "46_60", "60+": "60p"}
_PREFIX = {"lang": "lang", "city_tier": "tier", "age_band": "age", "value_band": "val"}


def _level_id(f: str, v: str) -> str:
    return f"{_PREFIX[f]}_{_SAFE.get(v, v)}"


def partition_cohorts(features: list[str], langs: list[str] | None = None) -> list[dict]:
    """Disjoint, exhaustive cohorts from the cross product of `features`' levels.

    Languages are restricted to the workflow's language mix so we don't emit
    cohorts that can never match. Every cohort is a rectangle, so it is
    expressible as a simulator `where` clause.
    """
    levels = []
    for f in features:
        vals = list(FEATURES[f])
        if f == "lang" and langs:
            vals = [v for v in vals if v in langs]
        levels.append([(f, v) for v in vals])
    out = []
    for combo in itertools.product(*levels):
        out.append({"id": "_".join(_level_id(f, v) for f, v in combo),
                    "where": {f: [v] for f, v in combo}})
    return out


def cohort_masks(cohorts: list[dict]) -> list[tuple[str, np.ndarray]]:
    """First-match semantics like the simulator; returns (cohort_id, mask) incl. 'default'."""
    taken = np.zeros(N_CELLS, dtype=bool)
    out = []
    for c in cohorts:
        m = where_mask(c["where"]) & ~taken
        taken |= m
        out.append((c["id"], m))
    out.append(("default", ~taken))
    return out
