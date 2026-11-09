"""Builder + governance against the real simulator (in-process)."""
import copy
import json

import pytest

from controller import builder, configops
from controller.governance import Governance
from controller.store import Store


def _infos(sim):
    return {w["workflow_id"]: w for w in sim.workflows()}


def _intent(store, wid, kind, subject, patch, priority=3, minute=0, **ev):
    ev.setdefault("summary", f"{kind} {subject}")
    ev.setdefault("rationale", "test")
    ev.setdefault("dry_run", {"x": 1})
    did = store.add_decision(kind, wid, minute, subject, "test", {}, "intent")
    return store.add_intent(wid, kind, subject, priority, patch, ev, did, minute)


def _advance_to(sim, minute):
    st = sim.state()
    if minute > st["sim_minute"]:
        sim.advance(minute - st["sim_minute"])
    return sim.state()["sim_minute"]


# ---------------------------------------------------------------- builder
LIVE = {"cohorts": [{"id": "old", "where": {"age_band": ["60+"]}}],
        "allocations": {"default": {"welcome_message": {"W1": 1}, "voice": {"V1": 1}, "caller_id": {"D1": 1}},
                        "old": {"voice": {"V3": 1}, "caller_id": {"D1": 1}}},
        "prompt_version": "P1", "schedule": {"hour_weights": {}, "lead_preferred_hour": {}}}


def _it(kind, patch, prio=3, **ev):
    return {"intent_id": kind, "kind": kind, "subject": kind, "priority": prio, "patch": patch, "evidence": ev,
            "created_minute": 0, "decision_id": "d"}


def test_merge_partition_drops_stale_cohort_allocations_and_applies_caller_to_pinned_cohorts():
    part = _it("schedule", {"op": "partition", "cohorts": [{"id": "age_60p", "where": {"age_band": ["60+"]}}],
                            "hour_weights": {"age_60p": {"9": 2.0}}})
    did = _it("callerid", {"op": "alloc", "dim": "caller_id", "allocs": {"default": {"D1": 0.5, "D2": 0.5}}}, 1)
    t, used, skipped = builder.merge(LIVE, [part, did], set())
    assert [c["id"] for c in t["cohorts"]] == ["age_60p"] and "old" not in t["allocations"]
    assert t["allocations"]["default"]["caller_id"] == {"D1": 0.5, "D2": 0.5}
    t2, _, _ = builder.merge(LIVE, [did], set())
    assert t2["allocations"]["old"]["caller_id"] == {"D1": 0.5, "D2": 0.5}   # pinned cohort follows


def test_merge_respects_supervisor_lock_unless_override():
    v = _it("experiment", {"op": "alloc", "dim": "voice", "allocs": {"default": {"V1": 0.8, "V2": 0.2}}})
    t, used, skipped = builder.merge(LIVE, [v], {"voice"})
    assert not used and "supervisor" in skipped[0]["skip_reason"]
    p = _it("incident", {"op": "prompt", "prompt_version": "P3"}, 0, override_supervisor=True)
    t, used, _ = builder.merge(LIVE, [p], {"prompt_version"})
    assert t["prompt_version"] == "P3"


def test_request_has_all_required_fields_and_sane_impact():
    v = _it("experiment", {"op": "alloc", "dim": "voice", "allocs": {"default": {"V1": 0.8, "V2": 0.2}}},
            gain_per_day=10, summary="explore voice", rationale="r", dry_run={"a": 1})
    t, used, _ = builder.merge(LIVE, [v], set())
    body = builder.request("wf", {"objective": {"primary": "engagement_rate"}}, 3, LIVE, t, used, 120, "pid", 24)
    for k in ("proposal_id", "workflow_id", "base_version", "proposed_config", "change_summary", "diff",
              "affected_leads", "dry_run", "impact_score", "rationale"):
        assert body[k] not in (None, "", {}), k
    assert 0 < body["impact_score"] < 1


# ---------------------------------------------------------------- gate
def test_gate_timing_ttl_and_stakeholder_hours(sim01, tmp_path):
    g = Governance(sim01, Store(tmp_path / "g.db"), _infos(sim01))
    assert g.gate("nw_renewal", 9 * 60)[0] is False
    assert g.gate("nw_renewal", 10 * 60)[0] is True
    assert g.gate("ks_cancel", 10 * 60 + 30)[0] is False          # Anita: never before 11:00
    assert g.gate("ks_cancel", 11 * 60)[0] is True
    ok, why = g.gate("ks_cancel", 18 * 60 + 30)                     # 12h TTL would expire overnight
    assert ok is False and "TTL" in why


# ---------------------------------------------------------------- lifecycle
def test_approval_lifecycle_applies_exact_target(sim01, tmp_path):
    store = Store(tmp_path / "g.db")
    applied = []
    g = Governance(sim01, store, _infos(sim01), on_applied=lambda p, v, now: applied.append(v))
    now = _advance_to(sim01, 10 * 60)
    _intent(store, "nw_renewal", "experiment", "voice", {"op": "alloc", "dim": "voice",
            "allocs": {"default": {"V1": 0.7, "V2": 0.1, "V3": 0.1, "V4": 0.1}}}, minute=now)
    g.plan("nw_renewal", now)
    p = store.proposals("nw_renewal")[0]
    assert p["state"] == "PENDING" and p["approval_id"]
    for _ in range(80):
        now = _advance_to(sim01, now + 15)
        g.poll(now)
        p = store.proposals("nw_renewal")[0]
        if p["state"] not in ("PENDING", "APPROVED"):
            break
    assert p["state"] in ("APPLIED", "REJECTED")
    if p["state"] == "APPLIED":
        live = sim01.config("nw_renewal")["config"]
        assert live["allocations"]["default"]["voice"] == pytest.approx({"V1": 0.7, "V2": 0.1, "V3": 0.1, "V4": 0.1})
        assert applied == [live and sim01.config("nw_renewal")["version"]]


def test_stale_base_reopens_intents_instead_of_overwriting(sim01, tmp_path):
    store = Store(tmp_path / "g.db")
    g = Governance(sim01, store, _infos(sim01))
    now = _advance_to(sim01, 10 * 60)
    iid = _intent(store, "nw_kyc", "experiment", "voice", {"op": "alloc", "dim": "voice",
                  "allocs": {"default": {"V1": 0.9, "V2": 0.1}}}, minute=now)
    g.plan("nw_kyc", now)
    # someone else changes the config while we wait (stand-in for a supervisor edit)
    other = copy.deepcopy(sim01.config("nw_renewal"))
    cfg = other["config"]; cfg["allocations"]["default"]["caller_id"] = {"D1": 0.4, "D2": 0.4, "D3": 0.2}
    from sim import server
    w = server.W()
    w._apply(w.wfs["nw_kyc"], configops.canonical({**sim01.config("nw_kyc")["config"],
             "schedule": {"hour_weights": {"default": {str(h): 1 for h in range(10, 20)}}, "lead_preferred_hour": {}}}),
             "supervisor", None, None)
    for _ in range(80):
        now = _advance_to(sim01, now + 15)
        g.poll(now)
        p = store.proposals("nw_kyc")[0]
        if p["state"] not in ("PENDING", "APPROVED"):
            break
    assert p["state"] in ("STALE", "REJECTED")
    if p["state"] == "STALE":
        assert store.conn.execute("select status from intents where intent_id=?", (iid,)).fetchone()[0] == "open"


def test_auto_apply_steps_within_max_shift(sim01, tmp_path):
    store = Store(tmp_path / "g.db")
    g = Governance(sim01, store, _infos(sim01), overrides={})
    now = _advance_to(sim01, 9 * 60)
    _intent(store, "ks_cancel", "experiment", "voice", {"op": "alloc", "dim": "voice",
            "allocs": {"default": {"V1": 0.55, "V2": 0.15, "V3": 0.15, "V4": 0.15}}}, minute=now)
    g.plan("ks_cancel", now)
    for _ in range(6):
        now = _advance_to(sim01, now + 15)
        g.poll(now)
    p = store.proposals("ks_cancel")[0]
    assert p["state"] == "APPLIED" and p["steps"] == 3
    hist = sim01.config_history("ks_cancel")
    assert all(h["actor"] == "controller_auto" for h in hist[1:])


def test_reconcile_adopts_approval_posted_before_crash(sim01, tmp_path):
    store = Store(tmp_path / "g.db")
    g = Governance(sim01, store, _infos(sim01))
    now = _advance_to(sim01, 10 * 60)
    _intent(store, "nw_renewal", "experiment", "voice", {"op": "alloc", "dim": "voice",
            "allocs": {"default": {"V1": 0.9, "V2": 0.1}}}, minute=now)
    g._post = lambda pid, body, now: sim01.post("/approvals", body)   # "crash" right after the POST
    g.plan("nw_renewal", now)
    assert store.proposals("nw_renewal")[0]["state"] == "SUBMITTING"
    g2 = Governance(sim01, store, _infos(sim01))
    g2.reconcile(now)
    p = store.proposals("nw_renewal")[0]
    assert p["state"] == "PENDING" and p["approval_id"].startswith("apr_")
    g2.poll(now)   # must not double-submit
    assert len(sim01.approvals("nw_renewal")) == 1


def test_urgent_gate_uses_median_latency(sim01, tmp_path):
    """variant_001: an incident at 17:00 on a 12h-TTL workflow should not wait for tomorrow."""
    g = Governance(sim01, Store(tmp_path / "g.db"), _infos(sim01))
    assert g.gate("ks_cancel", 17 * 60)[0] is False
    assert g.gate("ks_cancel", 17 * 60, urgent=True)[0] is True


def test_urgent_gate_accepts_a_reasonable_chance_today(tmp_path):
    """variant_001: latency [60,240], incident at 16:45 — ~40% chance of a same-day decision beats
    a guaranteed overnight wait (an expiry only costs one request)."""
    info = {"ks_cancel": {"tenant_id": "kestrel_finance", "governance": {
        "approver_hours": [10, 19], "approver_latency_minutes": [60, 240], "proposal_ttl_hours": 12,
        "max_requests_per_24h": 4, "auto_apply": {"enabled": True, "allowed_dims": [], "max_shift": 0.2}}}}
    g = Governance(None, Store(tmp_path / "g.db"), info)
    t = 4 * 1440 + 16 * 60 + 45
    assert g.gate("ks_cancel", t)[0] is False
    assert g.gate("ks_cancel", t, urgent=True)[0] is True


class _FakeSim:
    def __init__(self):
        self.applied = []

    def approval(self, aid):
        return {"approval_id": aid, "status": "approved", "decided_at": "x", "reasons": []}

    def post(self, path, body):
        self.applied.append(body)
        return {"version": 9}

    def config(self, wid):
        return {"version": 9, "actor": "controller_approved", "config": {}}


def test_routine_approval_is_not_applied_over_a_pending_incident_fix(tmp_path):
    """variant_006: a routine change applied first made the incident fix stale and burned the day's budget."""
    store = Store(tmp_path / "g.db")
    g = Governance(_FakeSim(), store, {"wf": {"tenant_id": "t", "governance": {"apply_window_hours": 2}}})
    for pid, prio, aid in (("routine", 3, "apr_1"), ("fix", 0, "apr_2")):
        d = store.add_decision("k", "wf", 0, pid, "r", {}, "o")
        iid = store.add_intent("wf", "incident" if prio == 0 else "callerid", pid, prio, {"op": "prompt"}, {}, d, 0)
        store.add_proposal({"proposal_id": pid, "workflow_id": "wf", "base_version": 3, "route": "approval",
                            "state": "PENDING", "target": {}, "request": {}, "intent_ids": [iid], "minute": 0})
        store.update_proposal(pid, 0, approval_id=aid)
    g._poll_approval(store.proposal("routine"), 100)
    assert store.proposal("routine")["state"] == "DEFERRED" and g.sim.applied == []


# ---------------------------------------------------------------- tenant overrides file
def test_default_overrides_file_loads_and_only_has_known_keys():
    from controller.governance import load_overrides
    o = load_overrides()
    assert o["kestrel_finance"]["max_requests_per_24h"] == 2
    assert o["northwind_life"] == {"customer_facing_requires_approval": True}


@pytest.mark.parametrize("rules", [{"max_request_per_24h": 2},          # typo must not be ignored
                                   {"max_requests_per_24h": True},       # bool is not an int here
                                   {"submit_from_hour": "11"}])
def test_bad_override_fails_fast(tmp_path, rules):
    from controller.governance import load_overrides
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"t": rules}))
    with pytest.raises(ValueError):
        load_overrides(f)


def test_overrides_can_be_disabled(monkeypatch):
    from controller.governance import load_overrides
    monkeypatch.setenv("CTL_TENANT_OVERRIDES", "none")
    assert load_overrides() == {}
