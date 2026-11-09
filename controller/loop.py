"""The control loop: advance -> ingest -> detect -> decide -> govern -> verify -> snapshot.

One process, one writer. All decisions are written to the store with their
inputs before any side effect, so `ctl why` can explain every config version.
"""
from __future__ import annotations

import json
import math
import shutil
import signal
import time
from pathlib import Path

import numpy as np

from . import callerid, cells, configops, crashpoint, experiments, incidents, schedule, stats
from .governance import Governance
from .ingest import Ingestor
from .simclient import SimClient, SimError
from .state import State
from .store import Store
from .timeutil import MIN_PER_DAY, day_of, hour_of, minute_to_label

DECISION_HOUR = 9          # daily looks happen at 09:00, before approvers start
SNAPSHOT_EVERY = 60
ESC = {"RESOLVED", "FALSE_ALARM", "ESCALATED", "CLOSED"}


class Controller:
    def __init__(self, url: str, state_dir: str | Path = "state", keep_call_log: bool = True,
                 sim: SimClient | None = None, log=print, max_ticks: int | None = None):
        self.sim = sim or SimClient(url)
        self.dir = Path(state_dir)
        self.keep_call_log = keep_call_log
        self.log = log
        self.max_ticks = max_ticks
        self._stop = False
        self.live: dict[str, dict] = {}

    # ================================================================== lifecycle
    def run(self) -> dict:
        self.startup()
        signal.signal(signal.SIGTERM, self._sigterm)
        ticks = 0
        while not self._stop:
            if not self.tick():
                break
            ticks += 1
            if self.max_ticks and ticks >= self.max_ticks:
                break
        self.state.save(self.snap_path)
        return self.summary()

    def _sigterm(self, *_):
        self._stop = True

    @property
    def snap_path(self):
        return self.dir / "snapshot.npz"

    def startup(self):
        st = self.sim.state()
        hist = self.sim.chunks("history", -1)
        fp = {"scenario": st["scenario"], "end": st["end_minute"],
              "history": [(c["chunk"], c["events"], c["until_minute"]) for c in hist]}
        self.dir.mkdir(parents=True, exist_ok=True)
        db = self.dir / "ctl.db"
        if db.exists():
            old = Store(db)
            if old.meta_get("fingerprint") != json.loads(json.dumps(fp)) or \
                    old.meta_get("last_sim_minute", -10**9) > st["sim_minute"]:
                old.conn.close()
                arch = self.dir.with_name(self.dir.name + f".old-{int(time.time())}")
                shutil.move(str(self.dir), arch)
                self.dir.mkdir(parents=True)
                self.log(f"[startup] new simulator world detected; archived previous state to {arch}")
        self.store = Store(self.dir / "ctl.db")
        self.store.meta_set("fingerprint", fp)
        infos = self.sim.workflows()
        self.infos = {w["workflow_id"]: w for w in infos}
        self.store.meta_set("workflows", infos)
        if self.snap_path.exists():
            self.state = State.load(self.snap_path)
            self.log(f"[startup] resumed from snapshot at chunk {self.state.last_chunk}")
        else:
            self.state = State.new(infos, st["end_minute"])
        self.ing = Ingestor(self.state, self.store, self.keep_call_log)
        self.gov = Governance(self.sim, self.store, self.infos, on_applied=self._on_applied,
                              affected=self._affected_leads)
        self.gov.locks = {k: set(v) for k, v in (self.store.meta_get("locks", {}) or {}).items()}
        t0 = time.perf_counter()
        for c in self.sim.chunks("history", self.state.last_chunk):
            self.ing.ingest_text(c["chunk"], self.sim.chunk(c["chunk"]), "history")
        if not self.state.calibration:
            self._calibrate(st["sim_minute"])
        self._catch_up()
        self.log(f"[startup] history+catch-up ingested in {time.perf_counter() - t0:.1f}s; "
                 f"sim at {minute_to_label(st['sim_minute'])}")
        self.gov.reconcile(st["sim_minute"])
        if not self.store.meta_get("bootstrapped"):
            self._bootstrap(st["sim_minute"])
            self.store.meta_set("bootstrapped", True)
        self.state.save(self.snap_path)

    def _catch_up(self) -> int:
        n = 0
        for c in self.sim.chunks("events", self.state.last_chunk):
            r = self.ing.ingest_text(c["chunk"], self.sim.chunk(c["chunk"]), "events")
            n += r.get("events", 0)
        return n

    # ================================================================== tick
    def step_minutes(self, now: int) -> int:
        h = hour_of(now)
        busy = 8 <= h < 21 or bool(self.store.proposals(states=("STEPPING", "APPROVED")))
        return 15 if (busy or now % 60) else 60

    def tick(self) -> bool:
        t0 = time.perf_counter()
        st = self.sim.state()
        if st["finished"]:
            self._catch_up()
            return False
        before = st["sim_minute"]
        pending = self.sim.chunks("events", self.state.last_chunk)
        if not pending:
            try:
                st = self.sim.advance(self.step_minutes(before), expected_from=before)
            except SimError as e:
                if e.code == "finished":
                    return False
                raise
        t1 = time.perf_counter()
        n = self._catch_up()
        t2 = time.perf_counter()
        now = self.sim.state()["sim_minute"]
        self.store.meta_set("last_sim_minute", now)
        self.live = {}
        self._supervisor_edits(now)
        self._incidents(now)
        self._callerid(now)
        if now % MIN_PER_DAY == DECISION_HOUR * 60:
            self._daily(now)
        self.gov.poll(now)
        for wid in self.infos:
            try:
                self.gov.plan(wid, now)
            except SimError as e:
                self.store.alert(now, "warn", wid, f"planning failed: {e}", "Retried next tick; see decisions.")
        self._post_apply_checks(now)
        t3 = time.perf_counter()
        if now % SNAPSHOT_EVERY == 0:
            self.state.save(self.snap_path)
        t4 = time.perf_counter()
        for k, v in {"events": n, "ingest_s": t2 - t1, "advance_s": t1 - t0, "decide_s": t3 - t2,
                     "snapshot_s": t4 - t3, "tick_s": t4 - t0, "events_per_s": n / max(t2 - t1, 1e-6),
                     "credits_remaining": self._credits(),
                     "open_intents": self._count("intents", "status='open'"),
                     "in_flight": self._count("proposals", "state in ('PENDING','APPROVED','STEPPING','SUBMITTING')")}.items():
            self.store.metric(now, k, v)
        if now % MIN_PER_DAY == 0:
            self.log(f"[{minute_to_label(now)}] day done; credits={self.sim.state()['credits_remaining']} "
                     f"applied={self._count('proposals', "state='APPLIED'")}")
        return True

    def _credits(self):
        return self.sim.state()["credits_remaining"]

    def _count(self, table, where):
        return self.store.conn.execute(f"select count(*) from {table} where {where}").fetchone()[0]

    def _live(self, wid):
        if wid not in self.live:
            self.live[wid] = self.sim.config(wid)
        return self.live[wid]

    # ================================================================== calibration & bootstrap
    def _calibrate(self, now):
        cal = {}
        for wid, ws in self.state.wfs.items():
            flags = np.array(ws.history_flags, dtype=np.int8)
            ws.history_flags = []
            n = len(flags)
            p0 = max(float(flags.mean()) if n else 0.015, 0.005)
            p1 = min(3 * p0, 0.5)
            hit, miss = stats.bernoulli_llr(p0, p1)
            s, smax = 0.0, 0.0
            for x in flags:
                s = max(0.0, s + (hit if x else miss))
                smax = max(smax, s)
            h = max(5.0, 1.3 * smax)
            ws.cusum.update({"p0": p0, "p1": p1, "h": h, "h_watch": max(3.0, 0.6 * h), "S": 0.0,
                             "llr": [hit, miss]})
            cal[wid] = {"halluc_p0": round(p0, 5), "cusum_h": round(h, 2), "history_max_S": round(smax, 2),
                        "history_connected": n}
            self.store.add_decision("calibrate", wid, now, "halluc_cusum",
                                    "p0 from history; p1=3*p0; h=max(5, 1.3*max in-control S)", cal[wid], "set")
        self.state.calibration = cal
        self.store.meta_set("calibration", cal)

    def _bootstrap(self, now):
        """D0 plan per workflow: cohort partition + schedule from history, caller-ID spread, experiments."""
        for wid, info in self.infos.items():
            ws = self.state.wfs[wid]
            live = self._live(wid)["config"]
            hist_days = slice(0, self.state.day_idx(now))
            pick = ws.pick[hist_days].sum(axis=0)
            feat, scores = schedule.choose_feature(pick, info["dialling_window"], info["languages"])
            did = self.store.add_decision("schedule_fit", wid, now, "partition", "chi-square hour x level, p<1e-3",
                                          {"scores": scores, "chosen": feat}, feat or "none")
            if feat:
                w = schedule.fit_weights(pick, feat, info["dialling_window"], info["languages"])
                dr = schedule.dry_run(pick, feat, w, info["dialling_window"], info["languages"])
                cohorts = cells.partition_cohorts([feat], info["languages"])
                dials_day = info["dials_per_hour"] * (info["dialling_window"][1] - info["dialling_window"][0])
                gain = dr["expected_pickup_new"] - dr["expected_pickup_old"]
                gain_day = gain * dials_day * self._eng_rate(ws)
                self.store.add_intent(wid, "schedule", "partition", 4,
                                      {"op": "partition", "cohorts": cohorts, "hour_weights": w},
                                      {"summary": f"call each {feat.replace('_', ' ')} group in the hours it answers "
                                                  f"(+{dr['relative_uplift'] * 100:.1f}% pickup est.)",
                                       "rationale": f"pre-D0 history shows pickup-by-hour differs by {feat} "
                                                    f"(chi2 p={scores[feat]['p']:.1e}); weights are relative pickup "
                                                    f"advantage per hour, clipped to [0.3,3], all window hours kept",
                                       "dry_run": dr, "gain_per_day": gain_day}, did, now)
            self._callerid_rebalance(wid, now, force_decision=True)
            for dim in ("welcome_message", "voice"):
                arms = info["options"][dim]
                if len(arms) < 2:
                    continue
                cur = configops.dist(live, "default", dim)
                inc = max(cur, key=cur.get)
                alloc = experiments.explore_alloc(arms, inc, ())
                xid = f"{wid}:{dim}:1"
                self.store.upsert_experiment({"exp_id": xid, "workflow_id": wid, "dim": dim, "arms": arms,
                                              "incumbent": inc, "state": "DESIGNED", "plan": {"scopes": {}}}, now)
                did = self.store.add_decision("experiment_design", wid, now, xid,
                                              f"challengers {experiments.CHALLENGER_SHARE:.0%} each, incumbent rest",
                                              {"arms": arms, "incumbent": inc, "alloc": alloc,
                                               "n_for_10pct_lift": stats.sample_size_per_arm(0.5, 0.05, 2.9, 0.84)},
                                              "designed")
                self.store.add_intent(wid, "experiment", f"{dim}:default", 5,
                                      {"op": "alloc", "dim": dim, "allocs": {"default": alloc}},
                                      {"summary": f"test {', '.join(a for a in alloc if a != inc)} against {inc} "
                                                  f"({dim.replace('_', ' ')}) on {1 - alloc[inc]:.0%} of calls",
                                       "rationale": "no variant evidence exists before D0 (history ran the default "
                                                    "only); small challenger shares cap the cost of a bad arm at <1% "
                                                    "expected engagement",
                                       "dry_run": {"expected_engagement_change": "unknown before data; "
                                                   "worst plausible arm (-10%) costs <=1% at this share"},
                                       "gain_per_day": 0.0, "exp_id": xid, "exp_action": "explore"}, did, now)

    def _eng_rate(self, ws) -> float:
        k = ws.kpi_h.sum(axis=0)
        return k[2] / k[1] if k[1] else 0.5

    # ================================================================== supervisor edits
    def _supervisor_edits(self, now):
        seen = set(self.store.meta_get("supervisor_seen", []))
        locks = self.gov.locks
        changed = False
        for wid, ws in self.state.wfs.items():
            for ev in ws.supervisor_events:
                if ev["event_id"] in seen:
                    continue
                seen.add(ev["event_id"])
                changed = True
                dims = set(ev["dims"]) - {"prompt_version"}   # prompts are owned by the supervisor anyway
                locks.setdefault(wid, set()).update(dims | ({"prompt_version"} & set(ev["dims"])))
                live = self._live(wid)
                self.store.upsert_config_version(wid, live["version"], live["actor"], ev["dims"], None, None,
                                                 ev["minute"], ev["event_id"], live["config"])
                for x in self.store.experiments(wid, ["DESIGNED", "RUNNING", "MONITORING"]):
                    if x["dim"] in dims:
                        x["state"] = "INTERRUPTED"
                        x["result"] = {**x["result"], "interrupted_by": "supervisor", "at": ev["minute"]}
                        self.store.upsert_experiment(x, now)
                        self.state.stop_experiment(wid, x["exp_id"])
                        self.store.cancel_intents(wid, "experiment", x["dim"], now)
                self.store.add_decision("supervisor_edit", wid, ev["minute"], f"v{ev['version']}",
                                        "supervisor edits win; we lock the dims and stop experiments on them",
                                        {"dims": ev["dims"], "version": ev["version"]}, "locked",
                                        {"version": ev["version"]})
        if changed:
            self.store.meta_set("supervisor_seen", sorted(seen))
            self.store.meta_set("locks", {k: sorted(v) for k, v in locks.items()})

    # ================================================================== caller ID
    def _did_window(self, ws, now):
        """Dialling hours of the last 24h, most recent last (assess() picks its own window)."""
        hi = self.state.hour_idx(now)
        rows = [h for h in range(max(0, hi - 24), hi) if ws.did[h, :, 0].sum() > 0]
        return ws.did[rows] if rows else np.zeros((0,) + ws.did.shape[1:], dtype=ws.did.dtype)

    def _callerid(self, now):
        for wid, ws in self.state.wfs.items():
            names = ws.opt["caller_id"]
            prior = self.store.did_status(wid)
            res = callerid.assess(names, self._did_window(ws, now), ws.did.sum(axis=0), prior)
            newly = [d for d, r in res.items() if r["status"] == "flagged" and prior.get(d) != "flagged"]
            for d in newly:
                self.store.set_did(wid, d, "flagged", now, res[d])
                self.store.alert(now, "info", wid, f"caller ID {d} flagged (pickup ratio {res[d].get('ratio')})",
                                 "Auto-handled: traffic is moved off the number. Ask telecom ops to check its "
                                 "spam reputation; no page.")
            for d, r in res.items():
                if r["status"] == "healthy" and prior.get(d) != "healthy" and prior.get(d) != "flagged":
                    self.store.set_did(wid, d, "healthy", now, r)
            if newly:
                self.store.add_decision("did_flag", wid, now, ",".join(newly),
                                        f"ratio<{callerid.RATIO_FLAG} and z<={callerid.Z_FLAG} vs sibling numbers "
                                        f"over the last {callerid.WINDOW_HOURS} dialling hours",
                                        {d: res[d] for d in names}, "flagged")
                self._callerid_rebalance(wid, now, urgent=True)
            elif now % 60 == 0:
                self._callerid_rebalance(wid, now)

    def _callerid_rebalance(self, wid, now, urgent=False, force_decision=False):
        ws = self.state.wfs[wid]
        names = ws.opt["caller_id"]
        prior = self.store.did_status(wid)
        res = callerid.assess(names, self._did_window(ws, now), ws.did.sum(axis=0), prior)
        status = {d: r["status"] for d, r in res.items()}
        for d, s in status.items():
            if prior.get(d) != s and s != "flagged":
                self.store.set_did(wid, d, s, now, res[d])
        target = callerid.target_allocation(status)
        if target is None:
            return
        live = self._live(wid)["config"]
        cur = configops._norm(configops.dist(live, "default", "caller_id"))
        tvd = configops.tv(cur, target)
        on_flagged = any(cur.get(d, 0) > 0 for d, s in status.items() if s == "flagged")
        if tvd < 0.05 and not on_flagged:
            return
        rel_old = callerid.expected_relative_pickup(cur, res)
        rel_new = callerid.expected_relative_pickup(target, res)
        info = self.infos[wid]
        dials_day = info["dials_per_hour"] * (info["dialling_window"][1] - info["dialling_window"][0])
        p = ws.kpi_h.sum(0)
        pick = p[1] / p[0] if p[0] else 0.3
        gain = max(rel_new - rel_old, 0) * pick * dials_day * self._eng_rate(ws)
        did = self.store.add_decision("did_rebalance", wid, now, "caller_id",
                                      "equal volume across healthy numbers, probe unknown, retire flagged",
                                      {"status": res, "current": cur, "target": target}, "intent")
        self.store.add_intent(wid, "callerid", "caller_id", 1 if (urgent or on_flagged) else 3,
                              {"op": "alloc", "dim": "caller_id", "allocs": {"default": target}},
                              {"summary": "caller IDs: " + ", ".join(f"{d} {w:.0%}" for d, w in target.items())
                                          + (f" (retire flagged {[d for d in status if status[d] == 'flagged']})"
                                             if on_flagged else ""),
                               "rationale": "spread dial volume evenly over healthy numbers (concentrated volume "
                                            "burns a number's reputation); unknown numbers get a small probe",
                               "dry_run": {"pickup_relative_to_best_number_old": round(rel_old, 4),
                                           "pickup_relative_to_best_number_new": round(rel_new, 4),
                                           "per_number": {d: {k: res[d].get(k) for k in ("status", "rate", "window_dials")}
                                                          for d in names}},
                               "gain_per_day": gain}, did, now)

    # ================================================================== daily
    def _daily(self, now):
        for wid in self.infos:
            self._kpi_drift(wid, now)
            self._experiment_looks(wid, now)

    def _kpi_drift(self, wid, now):
        ws = self.state.wfs[wid]
        d = self.state.day_idx(now)
        y = ws.kpi_h[(d - 1) * 24:d * 24].sum(0)
        b = ws.kpi_h[(d - 4) * 24:(d - 1) * 24].sum(0)
        if y[0] < 200 or b[0] < 600:
            return
        zp = stats.two_prop_z(y[1], y[0], b[1], b[0])
        ze = stats.two_prop_z(y[2], y[1], b[2], b[1])
        rec = {"pickup_yesterday": round(y[1] / y[0], 4), "pickup_prev3d": round(b[1] / b[0], 4), "z_pickup": round(zp, 2),
               "engagement_yesterday": round(y[2] / max(y[1], 1), 4),
               "engagement_prev3d": round(b[2] / max(b[1], 1), 4), "z_engagement": round(ze, 2)}
        drift = abs(zp) >= 3 or abs(ze) >= 3
        self.store.add_decision("kpi_check", wid, now, "daily", "|z|>=3 vs previous 3 days", rec,
                                "drift" if drift else "ok")
        if drift:
            self.store.alert(now, "warn", wid, f"KPI drift: {rec}",
                             "Not paged. Check supervisor edits/incidents for this workflow in `ctl why`.")

    def _experiment_looks(self, wid, now):
        today = day_of(now)
        live = self._live(wid)["config"]
        cohorts = live["cohorts"]
        for x in self.store.experiments(wid, ["RUNNING", "MONITORING"]):
            ws = self.state.wfs[wid]
            acc = ws.exps.get(x["exp_id"], {}).get("counts")
            if acc is None:
                continue
            k = today - day_of(x["start_minute"])
            if k < 1:
                continue
            arms, inc, dim = x["arms"], x["incumbent"], x["dim"]
            scopes = x["plan"].setdefault("scopes", {})
            split = {c for c, s in scopes.items() if c != "default" and s.get("state") in
                     ("promoted", "protected", "rolled_back")}
            default_mask = np.ones(cells.N_CELLS, dtype=bool)
            for cid, m in cells.cohort_masks(cohorts):
                if cid in split:
                    default_mask &= ~m
            ds = scopes.setdefault("default", {"state": "explore", "dropped": []})
            allocs, notes, gain = {}, [], 0.0
            conn_day = ws.kpi_h[(self.state.day_idx(now) - 1) * 24: self.state.day_idx(now) * 24, 1].sum()
            if ds["state"] == "explore":
                res = experiments.look(acc, arms, inc, k, default_mask, ds.get("dropped", []))
                ds["dropped"] = sorted(set(ds.get("dropped", [])) | set(res["dropped"]))
                self.store.add_decision("experiment_look", wid, now, f"{x['exp_id']}:default", res["rule"],
                                        {"day": k, "stats": res["stats"], "dropped": res["dropped"]}, res["action"],
                                        {"exp_id": x["exp_id"]})
                cur = configops._norm(configops.dist(live, "default", dim))
                if res["action"] == "promote":
                    ds["pending"] = {"action": "promote", "winner": res["winner"]}
                    allocs["default"] = res["alloc"]
                    s = res["stats"][res["winner"]]
                    gain += max(s["lift_abs"], 0) * (1 - experiments.HOLDOUT) * conn_day
                    notes.append(f"promote {res['winner']} (z={s['z']}, +{s['lift_abs'] * 100:.1f}pp engagement) "
                                 f"with {experiments.HOLDOUT:.0%} holdout on {inc}")
                elif configops.tv(cur, res["alloc"]) >= 0.05:
                    allocs["default"] = res["alloc"]
                    notes.append(f"rebalance test arms: {res['alloc']}" + (f", stop {res['dropped']}"
                                                                           if res["dropped"] else ""))
                if cohorts:
                    split_res = experiments.cohort_split(acc, arms, inc, res.get("winner"), cohorts, k)
                    for cid, r in split_res.items():
                        if cid in split or r["action"] == "keep":
                            continue
                        scopes[cid] = {"state": "explore", "pending": {"action": r["action"],
                                                                       "winner": r.get("winner", inc)}}
                        allocs[cid] = r["alloc"]
                        notes.append(f"{cid}: {r['action']} ({r['reason']})")
                        self.store.add_decision("experiment_cohort", wid, now, f"{x['exp_id']}:{cid}",
                                                "cohort split on shared partition", {"stats": r["stats"]},
                                                r["action"], {"exp_id": x["exp_id"]})
            for scope, s in scopes.items():
                if s.get("state") != "promoted":
                    continue
                mask = default_mask if scope == "default" else dict(cells.cohort_masks(cohorts)).get(scope)
                pd = s["promote_day"] - day_of(x["start_minute"])
                glob = any(e["minute"] >= x["start_minute"] and ("prompt_version" in e["dims"] or e["actor"] == "supervisor")
                           for e in ws.config_events)
                dc = experiments.decay_check(acc, arms, s["winner"], inc, pd, k, mask, global_change=glob)
                self.store.add_decision("decay_check", wid, now, f"{x['exp_id']}:{scope}", dc.get("rule", ""), dc,
                                        "rollback" if dc["rollback"] else "ok", {"exp_id": x["exp_id"]})
                if dc["rollback"]:
                    s["pending"] = {"action": "rollback", "winner": s["winner"]}
                    allocs[scope] = {inc: 1.0}
                    gain += max(-dc["winner_drop"], 0) * conn_day
                    notes.append(f"roll back {s['winner']} in {scope}: engagement fell "
                                 f"{dc['winner_drop'] * 100:.1f}pp vs its test period (holdout drift "
                                 f"{dc['holdout_drift'] * 100:.1f}pp)")
            self.store.upsert_experiment(x, now)
            if allocs:
                did = self.store.add_decision("experiment_decision", wid, now, x["exp_id"], "see looks",
                                              {"allocs": allocs, "notes": notes}, "intent", {"exp_id": x["exp_id"]})
                prio = 2 if any("roll back" in n for n in notes) else 5
                old_e = self._expected_eng(acc, arms, inc, live, dim, cohorts)
                self.store.add_intent(wid, "experiment", f"{dim}:{x['exp_id']}", prio,
                                      {"op": "alloc", "dim": dim, "allocs": allocs},
                                      {"summary": f"{dim.replace('_', ' ')}: " + "; ".join(notes),
                                       "rationale": "deterministic test on observed calls (by the variant each call "
                                                    "actually had): " + experiments.__doc__.split("Design")[1][:300],
                                       "dry_run": {"expected_engagement_current_alloc": old_e,
                                                   "expected_engagement_proposed": self._expected_eng(
                                                       acc, arms, inc, {**live, "allocations": {**live["allocations"],
                                                       **{kk: {**live["allocations"].get(kk, {}), dim: v}
                                                          for kk, v in allocs.items()}}}, dim, cohorts),
                                                   "method": "per-arm engagement since test start, shrunk to the "
                                                             "pooled mean (prior strength 50 calls)"},
                                       "gain_per_day": gain, "exp_id": x["exp_id"]}, did, now)

    def _expected_eng(self, acc, arms, inc, cfg, dim, cohorts):
        T = acc.sum(axis=(0, 2))
        pooled = T[:, 2].sum() / max(T[:, 1].sum(), 1)
        p = {a: stats.shrink(T[i][2], T[i][1], pooled) for i, a in enumerate(arms)}
        d = configops._norm(configops.dist(cfg, "default", dim))
        return round(sum(w * p.get(a, pooled) for a, w in d.items()), 4)

    # ================================================================== incidents
    def _incidents(self, now):
        for wid, ws in self.state.wfs.items():
            c = ws.cusum
            open_ = [i for i in self.store.incidents(wid) if i["state"] not in ESC]
            seen = set(self.store.meta_get(f"alarms_seen:{wid}", []))
            fresh = [al for al in c["alarms"] if al["event_id"] not in seen]
            if fresh:
                self.store.meta_set(f"alarms_seen:{wid}", sorted(seen | {al["event_id"] for al in fresh}))
            for al in fresh:
                iid = f"inc-{wid}-{al['event_id']}"
                if open_:
                    o = open_[0]
                    o["evidence"].setdefault("extra_alarms", []).append(al)
                    self.store.upsert_incident(o, now)
                    continue
                inc = {"incident_id": iid, "workflow_id": wid, "type": "hallucination", "state": "DETECTED",
                       "detected_minute": al["minute"], "evidence": {"alarm": al, "p0": c["p0"], "h": al["h"]}}
                self.store.upsert_incident(inc, now)
                self.store.add_decision("incident_detect", wid, now, iid, "Bernoulli CUSUM on hallucination flags",
                                        inc["evidence"], "detected", {"incident_id": iid})
                open_ = [inc]
            for inc in [i for i in self.store.incidents(wid) if i["state"] not in ESC]:
                self._advance_incident(wid, ws, inc, now)

    def _window_rate(self, ws, now, hours=3, since=None):
        hi = self.state.hour_idx(now)
        lo = self.state.hour_idx(since) if since is not None else hi - hours
        k = ws.kpi_h[max(lo, 0):hi].sum(0)
        return int(k[1]), int(k[3])

    def _advance_incident(self, wid, ws, inc, now):
        p0 = ws.cusum["p0"]
        st = inc["state"]
        cur_prompt = self._live(wid)["config"]["prompt_version"]
        P = ws.opt["prompt_version"]
        totals = ws.prompt.sum(axis=0)
        if st == "DETECTED":
            # Hypothesis under test: "the prompt that is live now is worse than baseline". So confirm
            # over everything since that prompt went live; with no prompt change, the last 3 hours.
            changes = [e["minute"] for e in ws.config_events if "prompt_version" in e["dims"]]
            since = max(changes) if changes else None
            recent_prompt_change = since is not None and since >= now - 3 * MIN_PER_DAY
            conn, flags = self._window_rate(ws, now, since=since)
            pval = incidents.confirm_p(flags, conn, p0)
            # a fresh prompt change is a known risk event (higher prior), so the bar is lower
            bar = incidents.CONFIRM_P_AFTER_CHANGE if recent_prompt_change else incidents.CONFIRM_P
            cur_i = P.index(cur_prompt)
            cur_rate = totals[cur_i][2] / max(totals[cur_i][0], 1)
            inc["evidence"].update({"confirm_window_conn": conn, "confirm_window_flags": flags,
                                    "confirm_p": pval, "confirm_window_since": since,
                                    "current_prompt": cur_prompt, "recent_prompt_change": recent_prompt_change,
                                    "current_prompt_flag_rate": round(cur_rate, 4)})
            if conn < 100:
                self.store.upsert_incident(inc, now)
                return
            if pval >= bar:
                inc["state"] = "FALSE_ALARM"
                self.store.upsert_incident(inc, now)
                self.store.add_decision("incident_close", wid, now, inc["incident_id"],
                                        f"not confirmed: exact binomial tail p>={bar} since the live prompt "
                                        f"started", inc["evidence"], "false_alarm")
                return
            if not (recent_prompt_change or cur_rate >= 2 * p0):
                inc["state"] = "ESCALATED"
                self.store.upsert_incident(inc, now)
                self.store.alert(now, "page", wid, "hallucination spike with no prompt change to blame",
                                 "Listen to flagged calls (call_log flag=1) and check the detector; the controller "
                                 "will not change a prompt without a cause.")
                return
            inc["state"] = "SELECTING"
            self.store.upsert_incident(inc, now)
            st = "SELECTING"
        if st == "SELECTING":
            bad = incidents.known_bad(P, totals, p0) | {cur_prompt}
            tried = {t["prompt"] for t in inc.get("tried", [])}
            cands = [g["prompt"] for g in incidents.known_good(P, totals, p0, exclude=bad | tried)]
            source = "own data (known-good prompts)"
            if not cands:
                r = self._spend(wid, "llm", 3, now, lambda: self.sim.post(
                    "/llm/suggest-fixes", {"workflow_id": wid, "problem": f"hallucination flag rate "
                                           f"{inc['evidence'].get('current_prompt_flag_rate')} vs baseline {p0:.4f} "
                                           f"after prompt {cur_prompt} went live"}), inc["incident_id"])
                if r is None:
                    return
                cands = [s["prompt_version"] for s in r["suggestions"] if s["prompt_version"] not in bad | tried]
                source = "LLM suggestions"
            if not cands:
                inc["state"] = "ESCALATED"
                self.store.upsert_incident(inc, now)
                self.store.alert(now, "page", wid, "no safe prompt candidate for hallucination incident",
                                 "A human must pick a prompt; validation evidence is required for approval.")
                return
            inc["candidate"] = cands[0]
            inc["evidence"]["candidate_source"] = source
            inc["state"] = "VALIDATING"
            self.store.upsert_incident(inc, now)
            st = "VALIDATING"
        if st == "VALIDATING":
            gov = self.infos[wid]["governance"]
            min_rate = gov.get("min_validation_pass_rate", 0.97)
            esc = inc["evidence"].get("escalated_for") == inc["candidate"]
            n = incidents.VALIDATION_N_ESCALATED if esc else incidents.VALIDATION_N
            r = self._spend(wid, "validation", math.ceil(n / 100), now, lambda: self.sim.post(
                "/validation/runs", {"workflow_id": wid, "prompt_version": inc["candidate"], "n": n}),
                f"{inc['incident_id']}:{inc['candidate']}:{n}")
            if r is None:
                return
            verdict = incidents.validation_verdict(r["pass_rate"], n, min_rate, escalated=esc)
            self.store.add_decision("validation", wid, now, f"{inc['incident_id']}:{inc['candidate']}:{n}",
                                    "one-sided 95% Wilson lower bound >= min pass rate", r, verdict,
                                    {"incident_id": inc["incident_id"]})
            if verdict == "escalate":
                inc["evidence"]["escalated_for"] = inc["candidate"]
                self.store.upsert_incident(inc, now)
                return
            if verdict == "fail":
                inc.setdefault("tried", []).append({"prompt": inc["candidate"], "validation": r})
                inc["state"] = "SELECTING" if len(inc["tried"]) < 3 else "ESCALATED"
                self.store.upsert_incident(inc, now)
                return
            inc["validation_run_id"] = r["validation_run_id"]
            inc["state"] = "PROPOSED"
            supervisor_owned = "prompt_version" in self.gov.locks.get(wid, set())
            cand_i = P.index(inc["candidate"])
            conn_day = ws.kpi_h[self.state.hour_idx(now) - 24:self.state.hour_idx(now), 1].sum()
            cur_rate = inc["evidence"].get("current_prompt_flag_rate", 0)
            did = self.store.add_decision("incident_fix", wid, now, inc["incident_id"],
                                          "known-good prompt first, then LLM; validated before proposing",
                                          {"candidate": inc["candidate"], "validation": r}, "propose",
                                          {"incident_id": inc["incident_id"]})
            self.store.add_intent(wid, "incident", f"prompt:{inc['incident_id']}", 0,
                                  {"op": "prompt", "prompt_version": inc["candidate"]},
                                  {"summary": f"switch prompt {cur_prompt} -> {inc['candidate']}: hallucination flags "
                                              f"{cur_rate:.1%} vs baseline {p0:.1%}",
                                   "rationale": f"CUSUM alarm confirmed (exact p={inc['evidence'].get('confirm_p'):.1e}); "
                                                f"candidate from {inc['evidence'].get('candidate_source')}; "
                                                f"validation pass rate {r['pass_rate']} on n={r['n']}",
                                   "dry_run": {"candidate_observed_flag_rate": round(
                                       totals[cand_i][2] / max(totals[cand_i][0], 1), 4),
                                       "candidate_observed_engagement": round(
                                           totals[cand_i][1] / max(totals[cand_i][0], 1), 4),
                                       "current_flag_rate": cur_rate, "validation": r},
                                   "gain_per_day": 5 * max(cur_rate - p0, 0) * conn_day,
                                   "validation_run_id": r["validation_run_id"],
                                   "override_supervisor": supervisor_owned, "incident_id": inc["incident_id"]},
                                  did, now)
            self.store.upsert_incident(inc, now)
            return
        if st in ("PROPOSED",):
            if cur_prompt == inc["candidate"] or (cur_prompt != inc["evidence"].get("current_prompt")
                                                   and cur_prompt not in incidents.known_bad(P, totals, p0)):
                inc["state"] = "VERIFYING"
                inc["applied_minute"] = inc.get("applied_minute") or now
                inc["evidence"]["fixed_by"] = "controller" if cur_prompt == inc["candidate"] else "supervisor"
                self.store.upsert_incident(inc, now)
                # never let a leftover intent overwrite whatever prompt is now live
                self.store.cancel_intents(wid, "incident", f"prompt:{inc['incident_id']}", now)
            return
        if st == "VERIFYING":
            conn, flags = self._window_rate(ws, now, since=inc["applied_minute"] + 60)  # post-fix hours only
            if conn >= incidents.VERIFY_MIN_CONN:
                rate = flags / conn
                if rate <= incidents.VERIFY_OK_RATIO * p0:
                    inc["state"] = "RESOLVED"
                    inc["resolved_minute"] = now
                    self.store.cancel_intents(wid, "incident", f"prompt:{inc['incident_id']}", now)
                    self.store.add_decision("incident_verify", wid, now, inc["incident_id"],
                                            f"flag rate <= {incidents.VERIFY_OK_RATIO}x baseline on "
                                            f">={incidents.VERIFY_MIN_CONN} connected calls",
                                            {"conn": conn, "flags": flags, "rate": round(rate, 4)}, "resolved")
                elif rate >= 3 * p0 and conn >= 300:
                    inc.setdefault("tried", []).append({"prompt": inc["candidate"], "post_apply_rate": rate})
                    inc["state"] = "SELECTING"
                    self.store.alert(now, "page", wid, "prompt fix did not reduce hallucinations",
                                     "Controller is trying the next candidate; review flagged calls.")
                self.store.upsert_incident(inc, now)

    def _spend(self, wid, kind, cost, now, fn, op_key):
        op = f"{kind}:{op_key}"
        if self.sim.state()["credits_remaining"] < cost:
            self.store.alert(now, "page", wid, f"out of credits for {kind}",
                             "Top up credits or fix manually; incidents cannot be validated.")
            return None
        self.store.credit(op, wid, kind, cost, "reserved", now)
        try:
            r = fn()
            if kind == "validation":
                crashpoint.hit("validation_spent")
        except SimError as e:
            self.store.credit(op, wid, kind, cost, "failed", now, {"error": str(e)})
            if e.status == 402:
                self.store.alert(now, "page", wid, "simulator reports out of credits", "Top up credits.")
            return None
        self.store.credit(op, wid, kind, cost, "spent", now, r)
        return r

    # ================================================================== apply hooks & verification
    def _on_applied(self, p, version, now):
        wid = p["workflow_id"]
        for it in self.store.intents_by_ids(p["intent_ids"]):
            ev = it["evidence"]
            if it["kind"] == "experiment" and ev.get("exp_id"):
                xs = [x for x in self.store.experiments(wid) if x["exp_id"] == ev["exp_id"]]
                if not xs:
                    continue
                x = xs[0]
                if x["state"] == "DESIGNED":
                    x.update(state="RUNNING", start_version=version, start_minute=now)
                    self.state.add_experiment(wid, x["exp_id"], x["dim"], x["arms"], version, now)
                for scope, s in x["plan"].get("scopes", {}).items():
                    pend = s.pop("pending", None)
                    if not pend or scope not in it["patch"]["allocs"]:
                        continue
                    if pend["action"] == "promote":
                        s.update(state="promoted", winner=pend["winner"], promote_day=day_of(now) + 1,
                                 promote_version=version)
                        x["state"] = "MONITORING"
                        x["winner"] = pend["winner"]
                    elif pend["action"] == "protect":
                        s.update(state="protected")
                    elif pend["action"] == "rollback":
                        s.update(state="rolled_back", banned=pend["winner"])
                self.store.upsert_experiment(x, now)
            if it["kind"] == "incident":
                for inc in self.store.incidents(wid):
                    if inc["incident_id"] == ev.get("incident_id"):
                        inc.update(state="VERIFYING", applied_minute=now, proposal_id=p["proposal_id"])
                        self.store.upsert_incident(inc, now)

    def _post_apply_checks(self, now):
        """24h after every applied change, record what happened next (for `ctl why`)."""
        if now % 60:
            return
        for p in self.store.proposals(states=["APPLIED"]):
            t = p["decided_minute"]
            if not (t + MIN_PER_DAY <= now < t + MIN_PER_DAY + 60):
                continue
            ws = self.state.wfs[p["workflow_id"]]
            a, b = self.state.hour_idx(t), self.state.hour_idx(now)
            before = ws.kpi_h[a - 24:a].sum(0)
            after = ws.kpi_h[a:b].sum(0)
            rec = {k: {"pickup": round(x[1] / max(x[0], 1), 4), "engagement": round(x[2] / max(x[1], 1), 4),
                       "halluc_flag_rate": round(x[3] / max(x[1], 1), 4), "dials": int(x[0])}
                   for k, x in (("24h_before", before), ("24h_after", after))}
            self.store.add_decision("post_apply", p["workflow_id"], now, p["proposal_id"],
                                    "KPIs 24h before vs 24h after apply (observational, not causal)", rec, "recorded",
                                    {"proposal_id": p["proposal_id"], "version": p["applied_version"]})

    def _affected_leads(self, wid, mask, next_campaign_only):
        ws = self.state.wfs[wid]
        info = self.infos[wid]
        d = self.state.day_idx(self.store.meta_get("last_sim_minute", 0) or 0)
        L = len(info["cadence"])
        up = ws.leads_up[max(d - L + 1, 0):d + 1]
        if next_campaign_only:
            recent = ws.leads_up[max(d - 3, 0):d + 1].sum(0)
            share = recent[mask].sum() / max(recent.sum(), 1)
            return int(round(info["daily_batch"]["size"] * share))
        active = up.sum(0) - ws.leads_concluded[max(d - L + 1, 0):d + 1].sum(0)
        return int(max(active[mask].sum(), 0))

    # ================================================================== summary
    def summary(self) -> dict:
        s = self.store
        return {"proposals": {r[0]: r[1] for r in s.conn.execute("select state, count(*) from proposals group by state")},
                "incidents": [(i["incident_id"], i["state"]) for i in s.incidents()],
                "experiments": [(x["exp_id"], x["state"], x.get("winner")) for x in s.experiments()],
                "credits_spent": s.credits_spent(), "last_chunk": self.state.last_chunk}
