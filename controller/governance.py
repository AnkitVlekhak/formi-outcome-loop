"""Governance client (C9): the only component that changes a workflow's config.

Proposal state machine (persisted in `proposals.state`):

  approval route
    SUBMITTING --POST ok--> PENDING --approved--> (apply) APPLIED
        |  409 duplicate -> reconcile          |--rejected--> REJECTED  (intents reopened w/ back-off)
        |  422 -> DROPPED (alert)              |--expired---> EXPIRED   (= rejection; reopened, rebuilt fresh)
                                               |--apply 409 stale--> STALE (reopened, rebuilt on live config)
                                               |--apply 410-------> LAPSED (reopened)
  auto route
    STEPPING --PUT step (<= max_shift TV)--> ... --> APPLIED
        |  live version moved by someone else -> STALE  (never overwrite a supervisor silently)
        |  403 not permitted -> re-planned via approval (alert: routing bug)

Submission gate (approval route): inside approver hours (and any stricter
stakeholder hours), worst-case decision time before the proposal TTL, rolling
24h request budget (one slot reserved for incidents), one in-flight request per
workflow. All ids are deterministic so a crash can never double-submit.
"""
from __future__ import annotations

import json

from . import builder, configops
from .simclient import SimError
from .timeutil import MIN_PER_DAY, hour_of, next_working

IN_FLIGHT = ("SUBMITTING", "PENDING", "APPROVED", "STEPPING")

# Stakeholder agreements that are stricter than the platform policy (see SUBMISSION.md §3).
OVERRIDES = {
    "kestrel_finance": {"max_requests_per_24h": 2, "submit_from_hour": 11,
                        "customer_facing_notice_minutes": 60, "auto_customer_facing_hours": [11, 19]},
    "northwind_life": {"customer_facing_requires_approval": True},
}
REJECT_BACKOFF = {"fatigue": 6 * 60, "judgement": 12 * 60, "default": 2 * 60}


class Governance:
    def __init__(self, sim, store, infos: dict, overrides=None, on_applied=None, affected=None):
        self.sim, self.store, self.infos = sim, store, infos
        self.ovr = OVERRIDES if overrides is None else overrides
        self.on_applied = on_applied or (lambda p, v, now: None)
        self.affected = affected or (lambda wid, mask, nco: 0)
        self.locks: dict[str, set] = {}

    # ------------------------------------------------------------------ policy helpers
    def _gov(self, wid):
        return self.infos[wid]["governance"]

    def _ovr(self, wid):
        return self.ovr.get(self.infos[wid]["tenant_id"], {})

    def request_limit(self, wid) -> int:
        lim = self._gov(wid)["max_requests_per_24h"]
        return min(lim, self._ovr(wid).get("max_requests_per_24h", lim))

    def gate(self, wid, now, urgent=False) -> tuple[bool, str]:
        g, o = self._gov(wid), self._ovr(wid)
        lo, hi = g["approver_hours"]
        start = max(lo, o.get("submit_from_hour", lo))
        mod = now % MIN_PER_DAY
        if not start * 60 <= mod < hi * 60:
            return False, f"outside submission hours [{start},{hi})"
        lat_max = g["approver_latency_minutes"][1]
        ttl = g["proposal_ttl_hours"] * 60
        worst = next_working(now + lat_max, g["approver_hours"])
        if worst > now + ttl:
            return False, f"worst-case decision {worst - now}min after submit exceeds TTL {ttl}min"
        used = self.store.approvals_submitted_since(wid, now - MIN_PER_DAY)
        lim = self.request_limit(wid)
        budget = lim if urgent else max(lim - 1, 1) if lim >= 2 else lim
        if used >= budget:
            return False, f"request budget used ({used}/{budget} in 24h, limit {lim})"
        inflight = [p for p in self.store.proposals(wid, ["SUBMITTING", "PENDING", "APPROVED"])]
        if inflight and not urgent:
            return False, "another request in flight"
        return True, "ok"

    def auto_ok(self, wid, dims, intents) -> tuple[bool, str]:
        pol = self._gov(wid)["auto_apply"]
        if not pol.get("enabled"):
            return False, "auto-apply disabled by policy"
        bad = [d for d in dims if d not in pol.get("allowed_dims", [])]
        if bad:
            return False, f"dims need approval: {bad}"
        if any(i["evidence"].get("override_supervisor") for i in intents):
            return False, "touches a supervisor edit: ask, don't overwrite"
        if set(dims) & configops.CUSTOMER_FACING and self._ovr(wid).get("customer_facing_requires_approval"):
            return False, "tenant requires named human approval for customer-facing changes"
        return True, "ok"

    # ------------------------------------------------------------------ planning
    def plan(self, wid, now):
        intents = [i for i in self.store.open_intents(wid) if (i.get("not_before") or 0) <= now]
        if not intents:
            return
        if self.store.proposals(wid, ["STEPPING"]):
            return  # let the running rollout finish; new intents bundle into the next one
        live = self.sim.config(wid)
        target, used, skipped = builder.merge(live["config"], intents, self.locks.get(wid, set()))
        for s in skipped:
            self.store.set_intents([s["intent_id"]], "skipped", now)
            self.store.add_decision("skip", wid, now, s["intent_id"], "builder", {"reason": s["skip_reason"]},
                                    "skipped")
        if not used:
            return
        dims = configops.changed_dims(live["config"], target)
        if not dims:
            self.store.set_intents([i["intent_id"] for i in used], "done", now)
            return
        urgent = min(i["priority"] for i in used) <= 1
        ok_auto, why_auto = self.auto_ok(wid, dims, used)
        if ok_auto:
            if self.store.proposals(wid, ["SUBMITTING", "PENDING", "APPROVED"]) and not urgent:
                return
            if not self._notice_ok(wid, dims, used, now):
                return
            self._start_auto(wid, live, target, used, now)
            return
        ok, why = self.gate(wid, now, urgent)
        if not ok:
            # gate closed: ship the auto-eligible subset now rather than idle until approver hours
            sub = [i for i in used if self.auto_ok(wid, builder.intent_dims(i), [i])[0]]
            if sub and len(sub) < len(used) and not self.store.proposals(wid, ["SUBMITTING", "PENDING", "APPROVED"]):
                t2, u2, _ = builder.merge(live["config"], sub, self.locks.get(wid, set()))
                d2 = configops.changed_dims(live["config"], t2)
                if d2 and self.auto_ok(wid, d2, u2)[0] and self._notice_ok(wid, d2, u2, now):
                    self._start_auto(wid, live, t2, u2, now)
            return
        self._submit(wid, live, target, used, now)

    def _notice_ok(self, wid, dims, intents, now) -> bool:
        o = self._ovr(wid)
        if not (set(dims) & configops.CUSTOMER_FACING) or "customer_facing_notice_minutes" not in o:
            return True
        lo, hi = o.get("auto_customer_facing_hours", [0, 24])
        first = min(i["created_minute"] for i in intents)
        for i in intents:
            self.store.add_decision("announce", wid, i["created_minute"], i["intent_id"], "notice before change",
                                    {"summary": i["evidence"].get("summary"), "earliest_apply":
                                     first + o["customer_facing_notice_minutes"]}, "announced")
        return now >= first + o["customer_facing_notice_minutes"] and lo <= hour_of(now) < hi

    def _affected(self, wid, live_cfg, target):
        mask, dims = builder.changed_masks(live_cfg, target)
        nco = self.infos[wid].get("mid_flight") == "next_campaign_only" and not (
            {"prompt_version", "schedule"} & set(dims))
        return self.affected(wid, mask, nco)

    def _submit(self, wid, live, target, used, now):
        ids = [i["intent_id"] for i in used]
        pid = builder.proposal_id(wid, live["version"], target, ids)
        if self.store.proposal(pid):
            pid = builder.proposal_id(wid, live["version"], target, ids, salt=str(now))
        body = builder.request(wid, self.infos[wid], live["version"], live["config"], target, used,
                               self._affected(wid, live["config"], target), pid,
                               self._gov(wid)["proposal_ttl_hours"])
        with self.store.tx():
            self.store.add_proposal({"proposal_id": pid, "workflow_id": wid, "base_version": live["version"],
                                     "route": "approval", "state": "SUBMITTING", "target": target, "request": body,
                                     "intent_ids": ids, "minute": now})
            self.store.set_intents(ids, "in_proposal", now, pid)
        self._post(pid, body, now)

    def _post(self, pid, body, now):
        wid = body["workflow_id"]
        try:
            a = self.sim.post("/approvals", body)
        except SimError as e:
            if e.code == "duplicate_proposal_id":
                return self._adopt(pid, wid, now)
            if e.code == "stale_base_version":
                return self._close(pid, "STALE", now, reopen_after=0, reasons=["stale at submit"])
            self.store.alert(now, "page" if e.status == 422 else "warn", wid, f"approval POST failed: {e}",
                             "Check the proposal body in `proposals.request_json`; a 422 is a controller bug.")
            return self._close(pid, "DROPPED", now, reopen_after=None, reasons=[str(e)])
        self.store.update_proposal(pid, now, state="PENDING", approval_id=a["approval_id"], submitted_minute=now)
        self.store.add_decision("submit", wid, now, pid, "approval route", {"approval": a,
                                "impact_score": body["impact_score"], "affected_leads": body["affected_leads"],
                                "summary": body["change_summary"]}, "pending", {"proposal_id": pid,
                                "approval_id": a["approval_id"]})

    def _adopt(self, pid, wid, now):
        for a in self.sim.approvals(wid):
            if a["proposal_id"] == pid:
                st = {"pending": "PENDING", "approved": "APPROVED"}.get(a["status"], "PENDING")
                self.store.update_proposal(pid, now, state=st, approval_id=a["approval_id"],
                                           submitted_minute=self.store.proposal(pid)["created_minute"])
                return
        self._close(pid, "DROPPED", now, reopen_after=0, reasons=["duplicate id but approval not found"])

    def _start_auto(self, wid, live, target, used, now):
        ids = [i["intent_id"] for i in used]
        pid = builder.proposal_id(wid, live["version"], target, ids, salt="auto")
        if self.store.proposal(pid):
            pid = builder.proposal_id(wid, live["version"], target, ids, salt=f"auto{now}")
        body = builder.request(wid, self.infos[wid], live["version"], live["config"], target, used,
                               self._affected(wid, live["config"], target), pid,
                               self._gov(wid)["proposal_ttl_hours"])
        with self.store.tx():
            self.store.add_proposal({"proposal_id": pid, "workflow_id": wid, "base_version": live["version"],
                                     "route": "auto", "state": "STEPPING", "target": target, "request": body,
                                     "intent_ids": ids, "minute": now})
            self.store.update_proposal(pid, now, applied_version=live["version"])
            self.store.set_intents(ids, "in_proposal", now, pid)
        self.store.add_decision("auto_start", wid, now, pid, "auto-apply within policy",
                                {"summary": body["change_summary"], "impact_score": body["impact_score"],
                                 "affected_leads": body["affected_leads"], "diff": body["diff"]}, "stepping",
                                {"proposal_id": pid})
        self._step(self.store.proposal(pid), now)

    # ------------------------------------------------------------------ progressing proposals
    def poll(self, now):
        for p in self.store.proposals(states=IN_FLIGHT):
            try:
                if p["state"] == "SUBMITTING":
                    self._post(p["proposal_id"], p["request"], now)
                elif p["state"] in ("PENDING", "APPROVED"):
                    self._poll_approval(p, now)
                elif p["state"] == "STEPPING":
                    self._step(p, now)
            except SimError as e:
                self.store.alert(now, "warn", p["workflow_id"], f"governance error on {p['proposal_id']}: {e}",
                                 "Inspect proposals/decisions for this id; the loop will retry next tick.")

    def _poll_approval(self, p, now):
        a = self.sim.approval(p["approval_id"])
        st, wid, pid = a["status"], p["workflow_id"], p["proposal_id"]
        if st == "pending":
            return
        decided = a.get("decided_at")
        if st == "approved":
            self.store.update_proposal(pid, now, state="APPROVED", reasons=a.get("reasons") or [])
            try:
                r = self.sim.post(f"/workflows/{wid}/apply", {"approval_id": p["approval_id"]})
            except SimError as e:
                if e.status == 410:
                    self.store.alert(now, "page", wid, f"approval {p['approval_id']} lapsed before apply",
                                     "The loop missed the 2h apply window — check tick cadence / crash timing.")
                    return self._close(pid, "LAPSED", now, reopen_after=0, reasons=["lapsed"])
                if e.code == "stale_base_version":
                    return self._close(pid, "STALE", now, reopen_after=0, reasons=["config changed since proposal"])
                if e.code == "not_approved":
                    return self._poll_approval(p, now)
                raise
            return self._applied(p, r["version"], now, actor="approver", decided=decided)
        if st == "applied":
            v = next((h["version"] for h in self.sim.config_history(wid) if h.get("approval_id") == p["approval_id"]),
                     None)
            return self._applied(p, v, now, actor="approver", decided=decided)
        reasons = a.get("reasons") or []
        kind = ("fatigue" if any("fatigue" in r for r in reasons) else
                "judgement" if any("judgement" in r for r in reasons) else "default")
        urgent = any(i["priority"] == 0 for i in self.store.intents_by_ids(p["intent_ids"]))
        delay = 0 if (urgent or st in ("expired", "lapsed")) else REJECT_BACKOFF[kind]
        self._close(pid, st.upper(), now, reopen_after=delay, reasons=reasons)

    def _step(self, p, now):
        wid, pid = p["workflow_id"], p["proposal_id"]
        live = self.sim.config(wid)
        expect = p["applied_version"] or p["base_version"]
        if live["version"] != expect:
            return self._close(pid, "STALE", now, reopen_after=0,
                               reasons=[f"config moved to v{live['version']} by someone else during rollout"])
        target = p["target"]
        if self._reached(live["config"], target):
            return self._applied(p, live["version"], now, actor="policy-auto")
        nxt = configops.step_toward(live["config"], target, self._gov(wid)["auto_apply"]["max_shift"])
        sid = f"{pid}.s{p['steps'] or 0}"
        body = {"proposal_id": sid, "base_version": live["version"], "proposed_config": nxt,
                "rationale": p["request"]["rationale"], "evidence": p["request"]["evidence"]}
        try:
            r = self.sim.put(f"/workflows/{wid}/config", body)
        except SimError as e:
            if e.code == "duplicate_proposal_id":       # step landed before a crash
                hist = self.sim.config_history(wid)
                v = next((h["version"] for h in hist if h.get("proposal_id") == sid), live["version"])
                self.store.update_proposal(pid, now, applied_version=v, steps=(p["steps"] or 0) + 1)
                return
            if e.status == 403:
                self.store.alert(now, "warn", wid, f"auto-apply refused: {e.detail}",
                                 "Routing disagreed with policy; the change was re-queued for approval.")
                return self._close(pid, "REFUSED", now, reopen_after=0, reasons=[str(e.detail)])
            if e.code == "stale_base_version":
                return self._close(pid, "STALE", now, reopen_after=0, reasons=["stale during step"])
            raise
        self.store.update_proposal(pid, now, applied_version=r["version"], steps=(p["steps"] or 0) + 1)
        self.store.add_decision("auto_step", wid, now, sid, "TV step <= max_shift",
                                {"version": r["version"], "dims": r["changed_dims"]}, "applied",
                                {"proposal_id": pid, "version": r["version"]})
        if self._reached(nxt, target):
            self._applied(self.store.proposal(pid), r["version"], now, actor="policy-auto")

    @staticmethod
    def _reached(cfg, target) -> bool:
        return (configops.max_shift(cfg, target) < 1e-3 and cfg["cohorts"] == target["cohorts"]
                and cfg["prompt_version"] == target["prompt_version"]
                and cfg["schedule"]["hour_weights"] == target["schedule"]["hour_weights"])

    def _applied(self, p, version, now, actor, decided=None):
        pid, wid = p["proposal_id"], p["workflow_id"]
        self.store.update_proposal(pid, now, state="APPLIED", applied_version=version, decided_minute=now)
        self.store.set_intents(p["intent_ids"], "done", now)
        cfg = self.sim.config(wid)
        if cfg["version"] == version:
            self.store.upsert_config_version(wid, version, cfg["actor"], [], None, p.get("approval_id"), now,
                                             None, cfg["config"])
        self.store.add_decision("applied", wid, now, pid, f"{p['route']} route", {"version": version,
                                "decided_at": decided, "approved_by": actor}, "applied",
                                {"proposal_id": pid, "approval_id": p.get("approval_id"), "version": version})
        self.on_applied(self.store.proposal(pid), version, now)

    def _close(self, pid, state, now, reopen_after, reasons):
        p = self.store.proposal(pid)
        self.store.update_proposal(pid, now, state=state, reasons=reasons, decided_minute=now)
        if reopen_after is not None:
            for i in p["intent_ids"]:
                self.store.conn.execute("update intents set status='open', not_before=?, updated_minute=? "
                                        "where intent_id=? and status='in_proposal'", (now + reopen_after, now, i))
        else:
            self.store.set_intents(p["intent_ids"], "dropped", now)
        self.store.add_decision("proposal_closed", p["workflow_id"], now, pid, state.lower(),
                                {"reasons": reasons, "reopen_after_min": reopen_after}, state,
                                {"proposal_id": pid, "approval_id": p.get("approval_id")})

    # ------------------------------------------------------------------ crash recovery
    def reconcile(self, now):
        """Called on startup: the simulator is the source of truth for approvals and config."""
        for p in self.store.proposals(states=IN_FLIGHT):
            if p["state"] == "SUBMITTING":
                found = [a for a in self.sim.approvals(p["workflow_id"]) if a["proposal_id"] == p["proposal_id"]]
                if found:
                    self.store.update_proposal(p["proposal_id"], now, state="PENDING",
                                               approval_id=found[0]["approval_id"], submitted_minute=p["created_minute"])
                    self.store.add_decision("reconcile", p["workflow_id"], now, p["proposal_id"],
                                            "adopted approval found after restart", found[0], "pending")
            elif p["state"] == "STEPPING":
                hist = self.sim.config_history(p["workflow_id"])
                mine = [h for h in hist if (h.get("proposal_id") or "").startswith(p["proposal_id"] + ".s")]
                if mine:
                    self.store.update_proposal(p["proposal_id"], now, applied_version=mine[-1]["version"],
                                               steps=len(mine))
