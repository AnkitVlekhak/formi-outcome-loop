"""Store idempotency, ingestion correctness, snapshot round-trip and replay safety."""
import json

import numpy as np
import pytest

from controller import cells
from controller.ingest import Ingestor
from controller.state import State
from controller.store import Store

WF = {"workflow_id": "wf1", "tenant_id": "t1", "languages": ["hi", "en"],
      "options": {"welcome_message": ["W1", "W2"], "voice": ["V1", "V2"], "caller_id": ["D1", "D2"],
                  "prompt_version": ["P1", "P2"]},
      "dialling_window": [9, 21], "mid_flight": "allowed"}


def _lead(eid, n, feats, ts="2027-01-04T08:00:00+05:30"):
    return {"type": "lead", "ts": ts, "workflow_id": "wf1", "campaign_id": "wf1:c0001",
            "lead_id": f"wf1:l{n:08d}", "person_id": f"wf1:p{n:07d}", "features": feats, "event_id": eid}


def _call(eid, n, w="W1", v="V1", d="D1", p="P1", conn=True, eng=False, flag=False, ver=1,
          ts="2027-01-04T10:05:00+05:30"):
    return {"type": "call", "ts": ts, "tenant_id": "t1", "workflow_id": "wf1", "campaign_id": "wf1:c0001",
            "lead_id": f"wf1:l{n:08d}", "person_id": f"wf1:p{n:07d}", "attempt_no": 1, "campaign_day_index": 0,
            "config_version": ver, "cohort_id": "default",
            "variant": {"welcome_message": w, "voice": v, "caller_id": d, "prompt_version": p},
            "connected": conn, "engaged": eng, "disposition": "x", "duration_s": 1, "turns": 1,
            "qa": {"hallucination_flag": flag, "flow_adherence": 0.9} if conn else None, "event_id": eid}


def _chunk(evs):
    return "\n".join(json.dumps(e) for e in evs) + "\n"


F = {"lang": "hi", "city_tier": "1", "age_band": "60+", "value_band": "low"}


@pytest.fixture()
def env(tmp_path):
    store = Store(tmp_path / "ctl.db")
    state = State.new([WF], end_minute=3 * 1440)
    return store, state, Ingestor(state, store, keep_call_log=True)


def test_decision_ids_are_idempotent(tmp_path):
    s = Store(tmp_path / "a.db")
    a = s.add_decision("detect", "wf1", 100, "did:D2", "rule", {"x": 1}, "flag")
    b = s.add_decision("detect", "wf1", 100, "did:D2", "rule", {"x": 1}, "flag")
    assert a == b and len(s.decisions("wf1")) == 1


def test_intent_supersedes_open_intent_with_same_subject(tmp_path):
    s = Store(tmp_path / "a.db")
    s.add_intent("wf1", "callerid", "caller_id", 2, {"x": 1}, {}, "d1", minute=10)
    s.add_intent("wf1", "callerid", "caller_id", 2, {"x": 2}, {}, "d2", minute=20)
    open_ = s.open_intents("wf1")
    assert len(open_) == 1 and open_[0]["patch"] == {"x": 2}


def test_ingest_counts_by_actual_variant_and_cell(env):
    store, state, ing = env
    evs = [_lead(1, 0, F), _lead(2, 1, {**F, "age_band": "18-30"}),
           _call(3, 0, w="W2", conn=True, eng=True), _call(4, 1, d="D2", conn=False),
           _call(5, 0, w="W2", conn=True, eng=False, flag=True)]
    ing.ingest_text(0, _chunk(evs), kind="events")
    ws = state.wfs["wf1"]
    c0 = cells.encode(F)
    assert ws.lead_cell[0] == c0
    d = state.day_idx(0)
    h = state.hour_idx(10 * 60)
    assert ws.kpi_h[h].tolist() == [3, 2, 1, 1]
    assert ws.did[h, 0].tolist() == [2, 2] and ws.did[h, 1].tolist() == [1, 0]
    assert ws.pick[d, 10, c0].tolist() == [2, 2]
    assert ws.leads_concluded[d, c0] == 1
    assert store.checkpoint() == 0


def test_experiment_accumulator_respects_version_boundary(env):
    store, state, ing = env
    state.add_experiment("wf1", "exp1", "welcome_message", ["W1", "W2"], start_version=2, start_minute=0)
    evs = [_lead(1, 0, F), _call(2, 0, w="W2", ver=1, eng=True), _call(3, 0, w="W2", ver=2, eng=True),
           _call(4, 0, w="W1", ver=3, eng=False)]
    ing.ingest_text(0, _chunk(evs), kind="events")
    acc = state.wfs["wf1"].exps["exp1"]["counts"]
    # [day_rel, arm, cell, (dials, conn, eng)]
    tot = acc.sum(axis=(0, 2))
    assert tot.tolist() == [[1, 1, 0], [1, 1, 1]]


def test_snapshot_round_trip_and_replay_is_idempotent(env, tmp_path):
    store, state, ing = env
    evs1 = [_lead(1, 0, F), _call(2, 0, eng=True)]
    evs2 = [_call(3, 0, w="W2", conn=False)]
    ing.ingest_text(0, _chunk(evs1), kind="events")
    path = tmp_path / "snap.npz"
    state.save(path)
    ing.ingest_text(1, _chunk(evs2), kind="events")
    full = state.wfs["wf1"].kpi_h.copy()
    # crash: reload snapshot (chunk 0) and replay chunk 1 again
    st2 = State.load(path)
    assert st2.last_chunk == 0
    Ingestor(st2, store, keep_call_log=True).ingest_text(1, _chunk(evs2), kind="events")
    assert (st2.wfs["wf1"].kpi_h == full).all()
    assert store.conn.execute("select count(*) from call_log").fetchone()[0] == 2


def test_cusum_raises_alarm_on_flag_burst(env):
    store, state, ing = env
    ws = state.wfs["wf1"]
    ws.cusum.update({"p0": 0.015, "p1": 0.045, "h": 4.0})
    evs = [_lead(1, 0, F)] + [_call(10 + i, 0, flag=(i % 4 == 0)) for i in range(60)]
    ing.ingest_text(0, _chunk(evs), kind="events")
    assert ws.cusum["alarms"], "a 25% flag rate must trip the CUSUM"


def test_supervisor_config_change_is_recorded(env):
    store, state, ing = env
    ev = {"type": "config_changed", "ts": "2027-01-04T11:30:00+05:30", "workflow_id": "wf1", "version": 2,
          "actor": "supervisor", "changed_dims": ["prompt_version"], "proposal_id": None, "approval_id": None,
          "event_id": 7}
    ing.ingest_text(0, _chunk([ev]), kind="events")
    assert state.wfs["wf1"].supervisor_events[0]["dims"] == ["prompt_version"]
    assert state.wfs["wf1"].cusum["watch_until"] == 11 * 60 + 30 + 360
    assert store.conn.execute("select actor from config_versions where version=2").fetchone()[0] == "supervisor"
