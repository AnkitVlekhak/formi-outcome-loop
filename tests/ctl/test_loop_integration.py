"""End-to-end: the controller drives the real simulator (in-process)."""
import json

import pytest

from controller import audit
from controller.loop import Controller
from controller.store import Store
from controller.timeutil import minute_to_label

from conftest import make_sim


def _sim_log(tmp_path):
    return [json.loads(l) for l in (tmp_path / "run" / "sim_log.jsonl").read_text().splitlines() if l.strip()]


def _run(sim, d, **kw):
    return Controller("x", d, sim=sim, log=lambda m: None, **kw).run()


def test_public01_short_run_is_clean_and_auditable(tmp_path):
    sim = make_sim(tmp_path, days=3, history_days=4)
    out = _run(sim, tmp_path / "state")
    log = _sim_log(tmp_path)
    kinds = [r["kind"] for r in log]
    assert sim.state()["finished"]
    assert "approval_lapsed" not in kinds, "never miss an apply window"
    assert "auto_apply_rejected" not in kinds, "routing must agree with policy"
    assert kinds.count("approval_applied") + kinds.count("auto_applied") >= 2
    # governance hygiene: never above the policy's request budget per 24h
    s = Store(tmp_path / "state" / "ctl.db")
    for wid in ("nw_renewal", "nw_kyc", "ks_cancel"):
        reqs = sorted(r["sim_minute"] for r in log if r["kind"] == "approval_requested" and r["workflow_id"] == wid)
        lim = {"nw_renewal": 3, "nw_kyc": 2, "ks_cancel": 2}[wid]
        assert all(sum(1 for u in reqs if t <= u < t + 1440) <= lim for t in reqs)
        # every controller config version is explainable from our own store
        for v in s.config_versions(wid):
            if v["actor"].startswith("controller"):
                w = audit.why(s, wid, v["sim_minute"])
                assert w["proposal_id"] and w["answer"] and w["rationale"], w
    # Kestrel supervisor asked for nothing before 11:00
    for r in log:
        if r["kind"] == "approval_requested" and r["workflow_id"] == "ks_cancel":
            assert r["sim_minute"] % 1440 >= 11 * 60


def _incident_world(sc):
    sc["incidents"] = [
        {"type": "did_flagged", "workflow": "ks_cancel", "did": "D2", "at": "D1 10:00", "base_health": 0.35},
        {"type": "supervisor_edit", "workflow": "ks_cancel", "at": "D1 11:30", "patch": {"prompt_version": "P2"},
         "note": "bad prompt"},
    ]


def test_incidents_detected_fixed_and_verified(tmp_path):
    sim = make_sim(tmp_path, scenario="scenarios/public_02_incidents.yaml", days=3, history_days=4,
                   mutate=_incident_world)
    _run(sim, tmp_path / "state")
    s = Store(tmp_path / "state" / "ctl.db")
    incs = s.incidents("ks_cancel")
    assert incs, "hallucination spike must be detected"
    assert incs[0]["detected_minute"] < 1440 + 16 * 60, "detected within hours of the bad prompt"
    hist = sim.config_history("ks_cancel")
    final_prompt = sim.config("ks_cancel")["config"]["prompt_version"]
    assert final_prompt != "P2", f"bad prompt still live: {hist}"
    assert s.did_status("ks_cancel").get("D2") == "flagged"
    alloc = sim.config("ks_cancel")["config"]["allocations"]["default"]["caller_id"]
    assert alloc.get("D2", 0) == 0
    assert s.credits_spent() <= 30


def test_kill_and_resume_finishes_without_double_actions(tmp_path):
    sim = make_sim(tmp_path, days=2, history_days=3)
    d = tmp_path / "state"
    _run(sim, d, max_ticks=45)          # "killed" mid-D0 (approvals in flight)
    _run(sim, d, max_ticks=7)           # killed again
    _run(sim, d)                        # resumes to the end
    assert sim.state()["finished"]
    s = Store(d / "ctl.db")
    log = _sim_log(tmp_path)
    ours = {p["approval_id"] for p in s.proposals() if p["approval_id"]}
    sim_reqs = [r["approval_id"] for r in log if r["kind"] == "approval_requested"]
    assert len(sim_reqs) == len(set(sim_reqs)) == len(ours), "no orphaned or duplicate approval requests"
    applied = [r for r in log if r["kind"] == "approval_applied"]
    assert len(applied) == len({r["approval_id"] for r in applied})
    assert s.proposals(states=["SUBMITTING"]) == []
