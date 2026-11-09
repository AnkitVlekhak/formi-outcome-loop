"""Proposal builder: merge open change intents into ONE target config on top of the
live config (supervisor edits included), then package it for governance.

Intent patch ops
  {"op": "partition", "cohorts": [...], "hour_weights": {...}}   cohorts + schedule (approval: cohorts dim)
  {"op": "hour_weights", "hour_weights": {...}}                  schedule refresh
  {"op": "alloc", "dim": d, "allocs": {cohort_key: dist}}         agent-dim allocation
  {"op": "prompt", "prompt_version": "P1"}

Rules: higher priority (lower number) wins a (cohort, dim) conflict; dims a
supervisor edited are locked unless the intent carries override_supervisor
(and then it must go through approval, labelled as such).
"""
from __future__ import annotations

import copy
import hashlib
import json

from . import cells, configops

IMPACT_HALF = 25.0   # impact = x / (x + 25); x = expected extra concluded leads/day (incidents: 5 per avoided hallucinated call)


def merge(live: dict, intents: list[dict], locks: set) -> tuple[dict, list[dict], list[dict]]:
    target = configops.canonical(copy.deepcopy(live))
    used, skipped = [], []
    taken: set = set()
    for it in sorted(intents, key=lambda i: (i["priority"], i["created_minute"])):
        p = it["patch"]
        op = p["op"]
        dims = intent_dims(it)
        if any(d in locks for d in dims) and not it["evidence"].get("override_supervisor"):
            skipped.append({**it, "skip_reason": f"supervisor owns {sorted(set(dims) & locks)}"})
            continue
        if op == "partition":
            if "cohorts" in taken:
                skipped.append({**it, "skip_reason": "superseded by higher-priority partition"})
                continue
            taken.add("cohorts")
            ids = {c["id"] for c in p["cohorts"]}
            target["cohorts"] = copy.deepcopy(p["cohorts"])
            target["allocations"] = {k: v for k, v in target["allocations"].items() if k == "default" or k in ids}
            hw = {k: v for k, v in target["schedule"]["hour_weights"].items() if k == "default" or k in ids}
            hw.update(p.get("hour_weights") or {})
            target["schedule"]["hour_weights"] = hw
        elif op == "hour_weights":
            ids = {c["id"] for c in target["cohorts"]} | {"default"}
            target["schedule"]["hour_weights"].update({k: v for k, v in p["hour_weights"].items() if k in ids})
        elif op == "alloc":
            d = p["dim"]
            keys = dict(p["allocs"])
            if d == "caller_id" and "default" in keys:
                # a caller-ID decision applies to every cohort that pins its own caller_id
                for k, dims_ in target["allocations"].items():
                    if k != "default" and "caller_id" in dims_:
                        keys.setdefault(k, keys["default"])
            ids = {c["id"] for c in target["cohorts"]} | {"default"}
            applied = False
            for k, dist in keys.items():
                if k not in ids or (k, d) in taken:
                    continue
                taken.add((k, d))
                target["allocations"].setdefault(k, {})[d] = {o: float(w) for o, w in dist.items() if w > 0}
                applied = True
            if not applied:
                skipped.append({**it, "skip_reason": "cohort missing or superseded"})
                continue
        elif op == "prompt":
            if "prompt_version" in taken:
                skipped.append({**it, "skip_reason": "superseded"})
                continue
            taken.add("prompt_version")
            target["prompt_version"] = p["prompt_version"]
        used.append(it)
    return configops.canonical(target), used, skipped


def intent_dims(it: dict) -> list[str]:
    p = it["patch"]
    return {"partition": ["cohorts", "schedule"], "hour_weights": ["schedule"], "alloc": [p.get("dim")],
            "prompt": ["prompt_version"]}[p["op"]]


def proposal_id(wid: str, base_version: int, target: dict, intent_ids: list[str], salt: str = "") -> str:
    h = hashlib.sha256(f"{wid}|{base_version}|{configops.config_hash(target)}|{','.join(sorted(intent_ids))}|{salt}"
                       .encode()).hexdigest()[:16]
    return f"ctl-{wid}-v{base_version}-{h}"


def changed_masks(live: dict, target: dict):
    """Cells whose experience changes (for affected-lead counts)."""
    import numpy as np
    dims = configops.changed_dims(live, target)
    if {"prompt_version", "cohorts"} & set(dims):
        return np.ones(cells.N_CELLS, dtype=bool), dims
    m = np.zeros(cells.N_CELLS, dtype=bool)
    for cid, mask in cells.cohort_masks(target["cohorts"]):
        for d in configops.AGENT_DIMS:
            if configops._norm(configops.dist(live, cid, d)) != configops._norm(configops.dist(target, cid, d)):
                m |= mask
        if live["schedule"]["hour_weights"].get(cid) != target["schedule"]["hour_weights"].get(cid):
            m |= mask
    return m, dims


def request(wid: str, info: dict, live_version: int, live: dict, target: dict, intents: list[dict],
            affected_leads: int, pid: str, ttl_hours: float) -> dict:
    gain = sum(float(i["evidence"].get("gain_per_day", 0.0)) for i in intents)
    impact = round(max(gain, 0.0) / (max(gain, 0.0) + IMPACT_HALF), 4)
    summary = "; ".join(i["evidence"].get("summary", i["kind"]) for i in intents)
    rationale = " | ".join(f"[{i['kind']}] {i['evidence'].get('rationale', '')} (decision {i['decision_id']})"
                           for i in intents)
    dry = {f"{i['kind']}:{i['subject']}": i["evidence"].get("dry_run", {"note": "no replay available"})
           for i in intents}
    dry["_combined"] = {"value_per_day": round(gain, 2),
                        "value_unit": "extra concluded leads per day; an incident fix counts each avoided "
                                      "hallucinated call as 5",
                        "impact_score_formula": f"value / (value + {IMPACT_HALF:g})",
                        "objective": info["objective"]}
    body = {"proposal_id": pid, "workflow_id": wid, "base_version": live_version, "proposed_config": target,
            "change_summary": summary[:400] or "controller change", "diff": configops.diff(live, target) or
            {"note": "no-op"}, "affected_leads": int(affected_leads), "dry_run": dry, "impact_score": impact,
            "rationale": rationale[:4000], "evidence": {"decision_ids": [i["decision_id"] for i in intents]},
            "expires_in_hours": ttl_hours}
    for i in intents:
        if i["evidence"].get("validation_run_id"):
            body["evidence"]["validation_run_id"] = i["evidence"]["validation_run_id"]
        if i["evidence"].get("override_supervisor"):
            body["change_summary"] = "REVERTS A SUPERVISOR EDIT (with evidence): " + body["change_summary"]
    return json.loads(json.dumps(body))
