"""Hallucination incident helpers (C8). Orchestration lives in loop.Controller._incidents."""
from __future__ import annotations

from . import stats

VALIDATION_N = 300
VALIDATION_N_ESCALATED = 1000
GOOD_RATIO = 1.5      # observed flag rate <= 1.5 x baseline counts as known-good
MIN_CONN = 300
VERIFY_MIN_CONN = 200
VERIFY_OK_RATIO = 2.0


def validation_verdict(pass_rate: float, n: int, min_rate: float, escalated: bool = False) -> str:
    """Stricter than the approver: the one-sided 95% Wilson lower bound must clear the bar.
    Borderline point estimates get one bigger run, never repeated small re-runs (that is p-hacking)."""
    lb = stats.wilson_lower(pass_rate * n, n, 1.645)
    if lb >= min_rate:
        return "pass"
    if pass_rate >= min_rate and not escalated:
        return "escalate"
    return "fail"


def known_good(prompts, prompt_counts, p0: float, exclude=()) -> list[dict]:
    """prompt_counts: [P, 3] = connected, engaged, flagged summed over our own data."""
    out = []
    for i, p in enumerate(prompts):
        conn, eng, flag = (int(x) for x in prompt_counts[i])
        if p in exclude or conn < MIN_CONN:
            continue
        rate = flag / conn
        if rate <= GOOD_RATIO * p0:
            out.append({"prompt": p, "conn": conn, "flag_rate": round(rate, 4), "eng_rate": round(eng / conn, 4)})
    return sorted(out, key=lambda r: -r["eng_rate"])


def known_bad(prompts, prompt_counts, p0: float) -> set:
    bad = set()
    for i, p in enumerate(prompts):
        conn, _, flag = (int(x) for x in prompt_counts[i])
        if conn >= MIN_CONN and flag / conn >= 2 * p0:
            bad.add(p)
    return bad
