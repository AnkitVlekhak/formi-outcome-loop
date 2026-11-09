"""Pure operations on workflow configs. Mirrors the simulator's contract (docs/SIMULATOR.md §3–4)."""
from __future__ import annotations

import copy
import hashlib
import json

AGENT_DIMS = ["welcome_message", "voice", "caller_id"]
CHANGE_DIMS = ["cohorts", "welcome_message", "voice", "caller_id", "prompt_version", "schedule"]
CUSTOMER_FACING = {"welcome_message", "voice", "prompt_version"}


def dist(cfg: dict, cohort: str, dim: str) -> dict:
    return (cfg["allocations"].get(cohort) or {}).get(dim) or cfg["allocations"]["default"][dim]


def _keys(*cfgs) -> set:
    ks = {"default"}
    for c in cfgs:
        ks |= set(c["allocations"]) | {x["id"] for x in c["cohorts"]}
    return ks


def tv(a: dict, b: dict) -> float:
    return 0.5 * sum(abs(a.get(o, 0.0) - b.get(o, 0.0)) for o in set(a) | set(b))


def changed_dims(old: dict, new: dict) -> list[str]:
    ch = set()
    if old["cohorts"] != new["cohorts"]:
        ch.add("cohorts")
    keys = set(old["allocations"]) | set(new["allocations"])
    for d in AGENT_DIMS:
        if any(_norm(dist(old, k, d)) != _norm(dist(new, k, d)) for k in keys if _has(old, k) and _has(new, k)):
            ch.add(d)
    if old["prompt_version"] != new["prompt_version"]:
        ch.add("prompt_version")
    if old["schedule"] != new["schedule"]:
        ch.add("schedule")
    return [d for d in CHANGE_DIMS if d in ch]


def _has(cfg, k):
    return k == "default" or k in cfg["allocations"] or True


def _norm(d: dict) -> dict:
    s = sum(d.values()) or 1.0
    return {k: round(v / s, 6) for k, v in sorted(d.items()) if v > 0}


def max_shift(old: dict, new: dict) -> float:
    worst = 0.0
    for k in _keys(old, new):
        for d in AGENT_DIMS:
            worst = max(worst, tv(_norm(dist(old, k, d)), _norm(dist(new, k, d))))
    return worst


def canonical(cfg: dict) -> dict:
    """Normalised weights, zero weights dropped, stable rounding."""
    out = copy.deepcopy(cfg)
    out.setdefault("cohorts", [])
    out.setdefault("schedule", {"hour_weights": {}, "lead_preferred_hour": {}})
    out["schedule"].setdefault("hour_weights", {})
    out["schedule"].setdefault("lead_preferred_hour", {})
    for k, dims in out["allocations"].items():
        for d, w in list(dims.items()):
            s = float(sum(w.values()))
            dims[d] = {o: round(float(v) / s, 4) for o, v in sorted(w.items()) if v > 0}
    return out


def step_toward(cur: dict, target: dict, max_tv: float) -> dict:
    """Move agent-dim allocations from cur toward target by a uniform fraction so that
    no (cohort, dim) moves more than max_tv. Non-agent dims are taken from target."""
    worst = max_shift(cur, target)
    t = 1.0 if worst <= max_tv + 1e-12 else max(0.0, (max_tv - 1e-6) / worst)
    out = copy.deepcopy(target)
    if t >= 1.0:
        return out
    for k in set(target["allocations"]) | {"default"}:
        out["allocations"].setdefault(k, {})
        for d in AGENT_DIMS:
            if d not in target["allocations"].get(k, {}) and k != "default":
                continue
            a, b = _norm(dist(cur, k, d)), _norm(dist(target, k, d))
            mixed = {o: (1 - t) * a.get(o, 0.0) + t * b.get(o, 0.0) for o in set(a) | set(b)}
            out["allocations"][k][d] = {o: round(v, 6) for o, v in sorted(mixed.items()) if v > 1e-9}
    # cohorts that only cur has an explicit allocation for: keep cur's mixed view via default rules
    return out


def validate(wf: dict, cfg: dict) -> list[str]:
    """Local pre-flight of the simulator's hard rules so we never burn a request on a 422."""
    p = []
    opts = wf["options"]
    ids = [c["id"] for c in cfg.get("cohorts", [])]
    if len(ids) > 20 or len(set(ids)) != len(ids) or "default" in ids:
        p.append("bad cohort ids")
    if "default" not in cfg["allocations"]:
        p.append("allocations.default missing")
    for k, dims in cfg["allocations"].items():
        if k != "default" and k not in ids:
            p.append(f"allocation for unknown cohort {k}")
        for d, w in dims.items():
            if any(o not in opts[d] for o in w) or sum(w.values()) <= 0:
                p.append(f"bad options in {k}.{d}")
    for d in AGENT_DIMS:
        if d not in cfg["allocations"].get("default", {}):
            p.append(f"allocations.default.{d} missing")
    if cfg["prompt_version"] not in opts["prompt_version"]:
        p.append("bad prompt_version")
    lo, hi = wf["dialling_window"]
    for k, hw in cfg["schedule"]["hour_weights"].items():
        if k != "default" and k not in ids:
            p.append(f"hour_weights for unknown cohort {k}")
        for h, w in hw.items():
            if not lo <= int(h) < hi or w < 0:
                p.append(f"bad hour weight {k}.{h}")
    return p


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(canonical(cfg), sort_keys=True).encode()).hexdigest()[:16]


def diff(old: dict, new: dict) -> dict:
    """Human-readable diff: one entry per changed path."""
    out = {}
    if old["cohorts"] != new["cohorts"]:
        out["cohorts"] = {"from": [c["id"] for c in old["cohorts"]], "to": [c["id"] for c in new["cohorts"]]}
    for k in sorted(_keys(old, new)):
        for d in AGENT_DIMS:
            a, b = _norm(dist(old, k, d)), _norm(dist(new, k, d))
            if a != b:
                out[f"allocations.{k}.{d}"] = {"from": a, "to": b}
    if old["prompt_version"] != new["prompt_version"]:
        out["prompt_version"] = {"from": old["prompt_version"], "to": new["prompt_version"]}
    if old["schedule"]["hour_weights"] != new["schedule"]["hour_weights"]:
        out["schedule.hour_weights"] = {"to": new["schedule"]["hour_weights"]}
    return out
