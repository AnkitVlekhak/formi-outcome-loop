"""SQLite (WAL) store: the controller's durable memory and audit trail.

Single writer (the control loop). The read API opens its own read-only
connection. Every write that represents a decision is keyed deterministically
so a crash-and-replay never duplicates it. Postgres would slot in behind the
same methods in production.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS config_versions (workflow_id TEXT, version INT, actor TEXT, changed_dims TEXT,
  proposal_id TEXT, approval_id TEXT, sim_minute INT, event_id INT, config_json TEXT,
  PRIMARY KEY (workflow_id, version));
CREATE TABLE IF NOT EXISTS decisions (decision_id TEXT PRIMARY KEY, sim_minute INT, workflow_id TEXT,
  kind TEXT, subject TEXT, rule TEXT, inputs_json TEXT, outcome TEXT, links_json TEXT);
CREATE INDEX IF NOT EXISTS decisions_wf ON decisions (workflow_id, sim_minute);
CREATE TABLE IF NOT EXISTS intents (intent_id TEXT PRIMARY KEY, workflow_id TEXT, kind TEXT, subject TEXT,
  priority INT, patch_json TEXT, evidence_json TEXT, decision_id TEXT, status TEXT, proposal_id TEXT,
  created_minute INT, not_before INT DEFAULT 0, updated_minute INT);
CREATE INDEX IF NOT EXISTS intents_open ON intents (workflow_id, status);
CREATE TABLE IF NOT EXISTS proposals (proposal_id TEXT PRIMARY KEY, workflow_id TEXT, base_version INT,
  route TEXT, state TEXT, approval_id TEXT, target_json TEXT, request_json TEXT, intent_ids TEXT,
  reasons TEXT, applied_version INT, parent_id TEXT, created_minute INT, submitted_minute INT,
  decided_minute INT, updated_minute INT, steps INT DEFAULT 0);
CREATE INDEX IF NOT EXISTS proposals_state ON proposals (state);
CREATE TABLE IF NOT EXISTS outbox (op_id TEXT PRIMARY KEY, kind TEXT, proposal_id TEXT, payload TEXT,
  state TEXT, response TEXT, sim_minute INT);
CREATE TABLE IF NOT EXISTS experiments (exp_id TEXT PRIMARY KEY, workflow_id TEXT, dim TEXT, arms_json TEXT,
  incumbent TEXT, state TEXT, start_version INT, start_minute INT, promote_minute INT, winner TEXT,
  plan_json TEXT, result_json TEXT, updated_minute INT);
CREATE TABLE IF NOT EXISTS incidents (incident_id TEXT PRIMARY KEY, workflow_id TEXT, type TEXT, state TEXT,
  detected_minute INT, evidence_json TEXT, candidate TEXT, validation_run_id TEXT, proposal_id TEXT,
  applied_minute INT, resolved_minute INT, tried_json TEXT, updated_minute INT);
CREATE TABLE IF NOT EXISTS did_status (workflow_id TEXT, did TEXT, status TEXT, sim_minute INT,
  evidence_json TEXT, PRIMARY KEY (workflow_id, did));
CREATE TABLE IF NOT EXISTS credits (op_id TEXT PRIMARY KEY, workflow_id TEXT, kind TEXT, cost REAL,
  state TEXT, sim_minute INT, result_json TEXT);
CREATE TABLE IF NOT EXISTS call_log (event_id INTEGER PRIMARY KEY, workflow_id TEXT, lead INT, person INT,
  sim_minute INT, config_version INT, cohort_id TEXT, w TEXT, v TEXT, d TEXT, p TEXT,
  connected INT, engaged INT, flag INT);
CREATE TABLE IF NOT EXISTS metrics (sim_minute INT, k TEXT, v REAL, PRIMARY KEY (sim_minute, k));
CREATE TABLE IF NOT EXISTS alerts (alert_id TEXT PRIMARY KEY, sim_minute INT, severity TEXT,
  workflow_id TEXT, message TEXT, runbook TEXT);
"""


def _h(*parts) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:20]


def _j(x) -> str:
    return json.dumps(x, sort_keys=True, default=str)


class Store:
    def __init__(self, path: str | Path, readonly: bool = False):
        self.path = str(path)
        if readonly:
            self.conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.executescript(SCHEMA)
        self.conn.row_factory = sqlite3.Row

    # ------------------------------------------------------------------ tx helper
    def tx(self):
        return _Tx(self.conn)

    # ------------------------------------------------------------------ meta
    def meta_get(self, k, default=None):
        r = self.conn.execute("select v from meta where k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def meta_set(self, k, v):
        self.conn.execute("insert into meta(k,v) values(?,?) on conflict(k) do update set v=excluded.v", (k, _j(v)))

    def checkpoint(self) -> int:
        return self.meta_get("last_chunk", -1)

    # ------------------------------------------------------------------ decisions / alerts
    def add_decision(self, kind, wf, minute, subject, rule, inputs, outcome, links=None) -> str:
        did = _h(kind, wf, minute, subject)
        self.conn.execute("insert or ignore into decisions values (?,?,?,?,?,?,?,?,?)",
                          (did, minute, wf, kind, subject, rule, _j(inputs), str(outcome), _j(links or {})))
        return did

    def decisions(self, wf=None, kind=None, since=None, until=None, limit=10_000):
        q, a = "select * from decisions where 1=1", []
        if wf:
            q += " and workflow_id=?"; a.append(wf)
        if kind:
            q += " and kind=?"; a.append(kind)
        if since is not None:
            q += " and sim_minute>=?"; a.append(since)
        if until is not None:
            q += " and sim_minute<=?"; a.append(until)
        q += " order by sim_minute, rowid limit ?"; a.append(limit)
        return [dict(r) for r in self.conn.execute(q, a)]

    def alert(self, minute, severity, wf, message, runbook):
        self.conn.execute("insert or ignore into alerts values (?,?,?,?,?,?)",
                          (_h(severity, wf, message, minute // 60), minute, severity, wf, message, runbook))

    # ------------------------------------------------------------------ intents
    def add_intent(self, wf, kind, subject, priority, patch, evidence, decision_id, minute, not_before=0) -> str:
        iid = _h(wf, kind, subject, minute, _j(patch))
        with self.tx():
            self.conn.execute("update intents set status='superseded', updated_minute=? where workflow_id=? and "
                              "kind=? and subject=? and status='open' and intent_id<>?",
                              (minute, wf, kind, subject, iid))
            self.conn.execute("insert or ignore into intents values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (iid, wf, kind, subject, priority, _j(patch), _j(evidence), decision_id, "open",
                               None, minute, not_before, minute))
        return iid

    def open_intents(self, wf):
        rows = self.conn.execute("select * from intents where workflow_id=? and status='open' "
                                 "order by priority, created_minute", (wf,)).fetchall()
        return [self._intent(r) for r in rows]

    def intents_by_ids(self, ids):
        if not ids:
            return []
        q = f"select * from intents where intent_id in ({','.join('?' * len(ids))})"
        return [self._intent(r) for r in self.conn.execute(q, list(ids))]

    def set_intents(self, ids, status, minute, proposal_id=None):
        for i in ids:
            self.conn.execute("update intents set status=?, proposal_id=coalesce(?, proposal_id), updated_minute=? "
                              "where intent_id=?", (status, proposal_id, minute, i))

    def cancel_intents(self, wf, kind, subject_prefix, minute):
        self.conn.execute("update intents set status='superseded', updated_minute=? where workflow_id=? and kind=? "
                          "and subject like ? and status='open'", (minute, wf, kind, subject_prefix + "%"))

    @staticmethod
    def _intent(r):
        d = dict(r)
        d["patch"] = json.loads(d.pop("patch_json"))
        d["evidence"] = json.loads(d.pop("evidence_json"))
        return d

    # ------------------------------------------------------------------ proposals
    def add_proposal(self, p: dict):
        self.conn.execute(
            "insert or ignore into proposals (proposal_id, workflow_id, base_version, route, state, target_json, "
            "request_json, intent_ids, parent_id, created_minute, updated_minute) values (?,?,?,?,?,?,?,?,?,?,?)",
            (p["proposal_id"], p["workflow_id"], p["base_version"], p["route"], p["state"], _j(p["target"]),
             _j(p["request"]), _j(p["intent_ids"]), p.get("parent_id"), p["minute"], p["minute"]))

    def update_proposal(self, pid, minute, **kw):
        sets, args = [], []
        for k, v in kw.items():
            sets.append(f"{k}=?")
            args.append(_j(v) if isinstance(v, (dict, list)) else v)
        sets.append("updated_minute=?")
        args += [minute, pid]
        self.conn.execute(f"update proposals set {', '.join(sets)} where proposal_id=?", args)

    def proposals(self, wf=None, states=None):
        q, a = "select * from proposals where 1=1", []
        if wf:
            q += " and workflow_id=?"; a.append(wf)
        if states:
            q += f" and state in ({','.join('?' * len(states))})"; a += list(states)
        q += " order by created_minute, rowid"
        out = []
        for r in self.conn.execute(q, a):
            d = dict(r)
            d["target"] = json.loads(d.pop("target_json"))
            d["request"] = json.loads(d.pop("request_json"))
            d["intent_ids"] = json.loads(d["intent_ids"])
            out.append(d)
        return out

    def proposal(self, pid):
        r = [p for p in self.proposals() if p["proposal_id"] == pid]
        return r[0] if r else None

    def approvals_submitted_since(self, wf, since_minute) -> int:
        return self.conn.execute("select count(*) from proposals where workflow_id=? and route='approval' and "
                                 "submitted_minute is not null and submitted_minute>?", (wf, since_minute)).fetchone()[0]

    # ------------------------------------------------------------------ outbox
    def outbox_put(self, op_id, kind, pid, payload, minute):
        self.conn.execute("insert or ignore into outbox values (?,?,?,?,?,?,?)",
                          (op_id, kind, pid, _j(payload), "planned", None, minute))

    def outbox_done(self, op_id, state, response):
        self.conn.execute("update outbox set state=?, response=? where op_id=?", (state, _j(response), op_id))

    def outbox_pending(self):
        return [dict(r) for r in self.conn.execute("select * from outbox where state in ('planned','sent')")]

    # ------------------------------------------------------------------ experiments / incidents / dids
    def upsert_experiment(self, e: dict, minute):
        cols = ["exp_id", "workflow_id", "dim", "arms_json", "incumbent", "state", "start_version", "start_minute",
                "promote_minute", "winner", "plan_json", "result_json", "updated_minute"]
        row = {**e, "arms_json": _j(e["arms"]), "plan_json": _j(e.get("plan", {})),
               "result_json": _j(e.get("result", {})), "updated_minute": minute}
        self.conn.execute(f"insert into experiments ({','.join(cols)}) values ({','.join('?' * len(cols))}) "
                          f"on conflict(exp_id) do update set " + ",".join(f"{c}=excluded.{c}" for c in cols[1:]),
                          [row.get(c) for c in cols])

    def experiments(self, wf=None, states=None):
        q, a = "select * from experiments where 1=1", []
        if wf:
            q += " and workflow_id=?"; a.append(wf)
        if states:
            q += f" and state in ({','.join('?' * len(states))})"; a += list(states)
        out = []
        for r in self.conn.execute(q + " order by rowid", a):
            d = dict(r)
            d["arms"] = json.loads(d.pop("arms_json"))
            d["plan"] = json.loads(d.pop("plan_json") or "{}")
            d["result"] = json.loads(d.pop("result_json") or "{}")
            out.append(d)
        return out

    def upsert_incident(self, i: dict, minute):
        cols = ["incident_id", "workflow_id", "type", "state", "detected_minute", "evidence_json", "candidate",
                "validation_run_id", "proposal_id", "applied_minute", "resolved_minute", "tried_json", "updated_minute"]
        row = {**i, "evidence_json": _j(i.get("evidence", {})), "tried_json": _j(i.get("tried", [])),
               "updated_minute": minute}
        self.conn.execute(f"insert into incidents ({','.join(cols)}) values ({','.join('?' * len(cols))}) "
                          f"on conflict(incident_id) do update set " + ",".join(f"{c}=excluded.{c}" for c in cols[1:]),
                          [row.get(c) for c in cols])

    def incidents(self, wf=None, states=None):
        q, a = "select * from incidents where 1=1", []
        if wf:
            q += " and workflow_id=?"; a.append(wf)
        if states:
            q += f" and state in ({','.join('?' * len(states))})"; a += list(states)
        out = []
        for r in self.conn.execute(q + " order by rowid", a):
            d = dict(r)
            d["evidence"] = json.loads(d.pop("evidence_json") or "{}")
            d["tried"] = json.loads(d.pop("tried_json") or "[]")
            out.append(d)
        return out

    def set_did(self, wf, did, status, minute, evidence):
        self.conn.execute("insert into did_status values (?,?,?,?,?) on conflict(workflow_id, did) do update set "
                          "status=excluded.status, sim_minute=excluded.sim_minute, evidence_json=excluded.evidence_json",
                          (wf, did, status, minute, _j(evidence)))

    def did_status(self, wf) -> dict:
        return {r["did"]: r["status"] for r in self.conn.execute("select * from did_status where workflow_id=?", (wf,))}

    # ------------------------------------------------------------------ credits
    def credit(self, op_id, wf, kind, cost, state, minute, result=None):
        self.conn.execute("insert into credits values (?,?,?,?,?,?,?) on conflict(op_id) do update set "
                          "state=excluded.state, result_json=excluded.result_json",
                          (op_id, wf, kind, cost, state, minute, _j(result or {})))

    def credits_spent(self) -> float:
        return self.conn.execute("select coalesce(sum(cost),0) from credits where state<>'reserved'").fetchone()[0]

    # ------------------------------------------------------------------ config versions / metrics
    def upsert_config_version(self, wf, version, actor, dims, pid, aid, minute, event_id=None, config=None):
        self.conn.execute(
            "insert into config_versions values (?,?,?,?,?,?,?,?,?) on conflict(workflow_id, version) do update set "
            "config_json=coalesce(excluded.config_json, config_versions.config_json), "
            "event_id=coalesce(excluded.event_id, config_versions.event_id)",
            (wf, version, actor, _j(dims), pid, aid, minute, event_id, _j(config) if config else None))

    def config_versions(self, wf):
        return [dict(r) for r in self.conn.execute(
            "select * from config_versions where workflow_id=? order by version", (wf,))]

    def metric(self, minute, k, v):
        self.conn.execute("insert or replace into metrics values (?,?,?)", (minute, k, float(v)))


class _Tx:
    def __init__(self, conn):
        self.conn = conn
        self.depth_owner = False

    def __enter__(self):
        if not self.conn.in_transaction:
            self.conn.execute("BEGIN")
            self.depth_owner = True
        return self.conn

    def __exit__(self, et, ev, tb):
        if self.depth_owner:
            self.conn.execute("COMMIT" if et is None else "ROLLBACK")
        return False
