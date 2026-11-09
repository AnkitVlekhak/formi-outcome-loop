"""Answer "why did workflow X change at time T, who approved it, and what happened next?"
from the controller's own store only (never the simulator's logs)."""
from __future__ import annotations

import json
import re

from .timeutil import label_to_minute, minute_to_label


def _pid(p):
    return re.sub(r"\.s\d+$", "", p) if p else p


def why(store, wid: str, at) -> dict:
    t = label_to_minute(at) if isinstance(at, str) else int(at)
    vers = [v for v in store.config_versions(wid) if (v["sim_minute"] is None or v["sim_minute"] <= t)]
    if not vers:
        return {"workflow_id": wid, "at": minute_to_label(t), "answer": "no config change recorded before this time"}
    v = max(vers, key=lambda r: r["version"])
    out = {"workflow_id": wid, "at": minute_to_label(t), "live_version": v["version"], "actor": v["actor"],
           "changed_at": minute_to_label(v["sim_minute"]) if v["sim_minute"] is not None else "before D0",
           "changed_dims": json.loads(v["changed_dims"] or "[]")}
    if v["actor"] == "supervisor":
        out["answer"] = "A client supervisor edited the config directly (outside governance)."
        out["controller_response"] = [d for d in store.decisions(wid, "supervisor_edit") if d["subject"] == f"v{v['version']}"]
        return out
    if v["actor"] in ("business_default",) or not v["proposal_id"]:
        out["answer"] = "Business default configuration (no controller change yet)."
        return out
    pid = _pid(v["proposal_id"])
    p = store.proposal(pid)
    if not p:
        out["answer"] = f"proposal {pid} not found in store"
        return out
    intents = store.intents_by_ids(p["intent_ids"])
    dec_ids = {i["decision_id"] for i in intents}
    decisions = [d for d in store.decisions(wid) if d["decision_id"] in dec_ids]
    links = [d for d in store.decisions(wid) if pid in (d["links_json"] or "")]
    out.update({
        "answer": p["request"]["change_summary"],
        "proposal_id": pid, "route": p["route"], "approval_id": p["approval_id"],
        "approved_by": "client approver (approval path)" if p["route"] == "approval" else
                       "workflow policy (auto-apply within allowed dims and max_shift)",
        "submitted_at": minute_to_label(p["submitted_minute"]) if p["submitted_minute"] is not None else None,
        "impact_score": p["request"]["impact_score"], "affected_leads": p["request"]["affected_leads"],
        "diff": p["request"]["diff"], "dry_run": p["request"]["dry_run"],
        "rationale": p["request"]["rationale"],
        "evidence_decisions": [{"kind": d["kind"], "at": minute_to_label(d["sim_minute"]), "rule": d["rule"],
                                "outcome": d["outcome"], "inputs": json.loads(d["inputs_json"])} for d in decisions],
        "lifecycle": [{"kind": d["kind"], "at": minute_to_label(d["sim_minute"]), "outcome": d["outcome"]}
                      for d in links],
        "what_happened_next": [json.loads(d["inputs_json"]) for d in links if d["kind"] == "post_apply"]
                              or "post-apply KPIs are recorded 24h after the change",
    })
    later = [x for x in store.config_versions(wid) if x["version"] > v["version"]]
    if later:
        n = later[0]
        out["superseded_by"] = {"version": n["version"], "actor": n["actor"],
                                "at": minute_to_label(n["sim_minute"]) if n["sim_minute"] is not None else None}
    return out


def customer_heard(store, wid: str, lead: int) -> list[dict]:
    """IRDAI-style question: what did this customer hear, and why was it live?"""
    rows = store.conn.execute("select * from call_log where workflow_id=? and lead=? order by event_id",
                              (wid, lead)).fetchall()
    out = []
    for r in rows:
        w = why(store, wid, r["sim_minute"])
        out.append({"at": minute_to_label(r["sim_minute"]), "config_version": r["config_version"],
                    "cohort": r["cohort_id"], "welcome": r["w"], "voice": r["v"], "caller_id": r["d"],
                    "prompt": r["p"], "connected": bool(r["connected"]), "engaged": bool(r["engaged"]),
                    "why_live": w.get("answer"), "proposal_id": w.get("proposal_id"),
                    "approval_id": w.get("approval_id")})
    return out
