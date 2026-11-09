"""Read-only API: the supervisor's one screen, the audit query, and loop health.

Runs in a daemon thread next to the controller with its own read-only SQLite
connection (WAL lets it read while the loop writes)."""
from __future__ import annotations

import json
import threading

from fastapi import FastAPI

from . import audit
from .store import Store
from .timeutil import minute_to_label


def make_app(db_path: str) -> FastAPI:
    app = FastAPI(title="Formi controller", version="1.0")

    def S():
        return Store(db_path, readonly=True)

    @app.get("/supervisor/{tenant_id}")
    def supervisor(tenant_id: str):
        s = S()
        wfs = [w for w in s.meta_get("workflows", []) if w["tenant_id"] == tenant_id]
        now = s.meta_get("last_sim_minute", 0)
        out = {"tenant_id": tenant_id, "as_of": minute_to_label(now), "workflows": []}
        for w in wfs:
            wid = w["workflow_id"]
            props = s.proposals(wid)
            out["workflows"].append({
                "workflow_id": wid, "objective": w["objective"],
                "being_tested": [{"exp": x["exp_id"], "dim": x["dim"], "state": x["state"], "incumbent": x["incumbent"],
                                  "winner": x.get("winner"), "scopes": x["plan"].get("scopes")} for x in s.experiments(wid)],
                "waiting_for_you": [{"proposal_id": p["proposal_id"], "approval_id": p["approval_id"],
                                     "summary": p["request"]["change_summary"], "impact_score": p["request"]["impact_score"],
                                     "affected_leads": p["request"]["affected_leads"]}
                                    for p in sorted(props, key=lambda p: -p["request"]["impact_score"])
                                    if p["state"] in ("PENDING",)],
                "changed_today": [{"at": minute_to_label(p["decided_minute"]), "summary": p["request"]["change_summary"],
                                   "route": p["route"], "version": p["applied_version"]}
                                  for p in props if p["state"] == "APPLIED" and p["decided_minute"] >= now - now % 1440],
                "announced_upcoming": [json.loads(d["inputs_json"]) for d in s.decisions(wid, "announce", since=now - 1440)],
                "incidents": [{"id": i["incident_id"], "state": i["state"], "candidate": i["candidate"]}
                              for i in s.incidents(wid)],
                "caller_ids": s.did_status(wid),
            })
        return out

    @app.get("/why")
    def why(workflow_id: str, at: str):
        return audit.why(S(), workflow_id, at)

    @app.get("/heard")
    def heard(workflow_id: str, lead: int):
        return audit.customer_heard(S(), workflow_id, lead)

    @app.get("/metrics")
    def metrics():
        s = S()
        rows = s.conn.execute("select k, v from metrics where sim_minute=(select max(sim_minute) from metrics)").fetchall()
        dec = s.conn.execute("select count(*) from decisions where sim_minute>=?",
                             ((s.meta_get("last_sim_minute", 0) or 0) - 60,)).fetchone()[0]
        return {"as_of": minute_to_label(s.meta_get("last_sim_minute", 0) or 0), **{r[0]: r[1] for r in rows},
                "decisions_last_hour": dec, "credits_spent": s.credits_spent()}

    @app.get("/alerts")
    def alerts(severity: str | None = None):
        s = S()
        q = "select * from alerts" + (" where severity=?" if severity else "") + " order by sim_minute desc limit 200"
        return [dict(r) for r in s.conn.execute(q, (severity,) if severity else ())]

    return app


def serve_in_thread(db_path: str, port: int):
    import uvicorn
    cfg = uvicorn.Config(make_app(db_path), host="127.0.0.1", port=port, log_level="warning")
    t = threading.Thread(target=uvicorn.Server(cfg).run, daemon=True)
    t.start()
    return t
