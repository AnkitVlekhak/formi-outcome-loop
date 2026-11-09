"""Event ingestion: chunk NDJSON -> per-cell counters, detector state, audit rows.

Hot path. One Python pass per event with orjson, numeric updates batched into
np.add.at per chunk. Exactly-once *effect*: array state is only persisted via
snapshots tagged with a chunk number; DB rows written here are idempotent
(INSERT OR IGNORE on event_id / natural keys), so replaying a chunk is safe.
"""
from __future__ import annotations

import time

import numpy as np

try:
    import orjson as _json
    _loads = _json.loads
except ImportError:  # pragma: no cover - orjson is in requirements, json is the fallback
    import json as _json
    _loads = _json.loads

from . import cells
from .state import MAX_EXP_DAYS, State
from .store import Store
from .timeutil import FastTs

WATCH_MINUTES = 48 * 60   # heightened sensitivity for 48h after a supervisor prompt edit (confirmation still gates action)


def _num(s: str) -> int:
    """'wf:l00012345' -> 12345 (ids are '<workflow>:<letter><digits>')."""
    return int(s[s.rindex(":") + 2:])


class Ingestor:
    def __init__(self, state: State, store: Store, keep_call_log: bool = True):
        self.state, self.store, self.keep_call_log = state, store, keep_call_log
        self.ts = FastTs()
        self._cell_cache: dict[tuple, int] = {}

    def _cell(self, f: dict) -> int:
        k = (f["lang"], f["city_tier"], f["age_band"], f["value_band"])
        c = self._cell_cache.get(k)
        if c is None:
            c = self._cell_cache[k] = cells.encode(f)
        return c

    # ------------------------------------------------------------------ public
    def ingest_text(self, chunk_no: int, text: str | bytes, kind: str) -> dict:
        t0 = time.perf_counter()
        st = self.state
        if chunk_no <= st.last_chunk:
            return {"skipped": True, "events": 0}
        history = kind == "history"
        buf = {wid: {"pick": [], "did": [], "kpi": [], "prompt": [], "concl": [], "exp": {}}
               for wid in st.wfs}
        call_rows, cfg_rows = [], []
        n = 0
        lines = text.splitlines() if isinstance(text, (bytes, str)) else text
        for line in lines:
            if not line:
                continue
            ev = _loads(line)
            n += 1
            eid = ev["event_id"]
            if eid <= st.last_event_id:
                continue  # already applied (defensive: chunk boundaries never overlap)
            st.last_event_id = eid
            t = ev["type"]
            ws = st.wfs.get(ev.get("workflow_id"))
            if ws is None:
                continue
            if t == "call":
                minute = self.ts(ev["ts"])
                lead = _num(ev["lead_id"])
                cell = int(ws.lead_cell[lead]) if lead < ws.n_leads else 0
                hour_abs = st.hour_idx(minute)
                day = st.day_idx(minute)
                hod = (minute % 1440) // 60
                var = ev["variant"]
                d_i = ws.idx["caller_id"][var["caller_id"]]
                p_i = ws.idx["prompt_version"][var["prompt_version"]]
                conn = ev["connected"]
                eng = ev["engaged"]
                flag = bool(conn and ev["qa"] and ev["qa"]["hallucination_flag"])
                b = buf[ws.id]
                b["pick"].append((day, hod, cell, conn))
                b["did"].append((hour_abs, d_i, conn))
                b["kpi"].append((hour_abs, conn, eng, flag))
                if conn:
                    b["prompt"].append((day, p_i, eng, flag))
                    if history:
                        ws.history_flags.append(1 if flag else 0)
                    else:
                        self._cusum(ws, flag, minute, eid)
                if eng:
                    b["concl"].append((int(ws.lead_day[lead]) if lead < ws.n_leads else day, cell))
                if not history and ws.exps:
                    ver = ev["config_version"]
                    for xid, x in ws.exps.items():
                        if not x["active"] or ver < x["start_version"]:
                            continue
                        val = var[x["dim"]]
                        if val not in x["arms"]:
                            continue
                        dr = min(max(minute // 1440 - x["start_day"], 0), MAX_EXP_DAYS - 1)
                        b["exp"].setdefault(xid, []).append((dr, x["arms"].index(val), cell, conn, eng))
                if self.keep_call_log and not history:
                    call_rows.append((eid, ws.id, lead, _num(ev["person_id"]), minute, ev["config_version"],
                                      ev["cohort_id"], var["welcome_message"], var["voice"], var["caller_id"],
                                      var["prompt_version"], int(conn), int(eng), int(flag)))
            elif t == "lead":
                lead = _num(ev["lead_id"])
                ws.ensure_leads(lead + 1)
                c = self._cell(ev["features"])
                minute = self.ts(ev["ts"])
                ws.lead_cell[lead] = c
                ws.lead_day[lead] = st.day_idx(minute)
                ws.n_leads = max(ws.n_leads, lead + 1)
                ws.leads_up[st.day_idx(minute), c] += 1
            elif t == "config_changed":
                minute = self.ts(ev["ts"])
                rec = {"event_id": eid, "minute": minute, "version": ev["version"], "actor": ev["actor"],
                       "dims": ev["changed_dims"], "proposal_id": ev.get("proposal_id"),
                       "approval_id": ev.get("approval_id")}
                ws.config_events.append(rec)
                if ev["actor"] == "supervisor":
                    ws.supervisor_events.append(rec)
                    if "prompt_version" in ev["changed_dims"]:
                        ws.cusum["watch_until"] = minute + WATCH_MINUTES
                cfg_rows.append((ws.id, ev["version"], ev["actor"], ev["changed_dims"], ev.get("proposal_id"),
                                 ev.get("approval_id"), minute, eid))
            elif t == "campaign_created":
                ws.campaign_version[ev["campaign_id"]] = ev["config_version_at_creation"]
        self._flush(buf)
        with self.store.tx():
            if call_rows:
                self.store.conn.executemany("insert or ignore into call_log values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                            call_rows)
            for r in cfg_rows:
                self.store.upsert_config_version(*r)
            self.store.meta_set("last_chunk", chunk_no)
        st.last_chunk = chunk_no
        return {"events": n, "seconds": time.perf_counter() - t0}

    # ------------------------------------------------------------------ internals
    def _cusum(self, ws, flag: bool, minute: int, eid: int):
        c = ws.cusum
        if c["p0"] is None:
            return
        hit, miss = c.get("llr") or (None, None)
        if hit is None:
            import math
            hit, miss = math.log(c["p1"] / c["p0"]), math.log((1 - c["p1"]) / (1 - c["p0"]))
            c["llr"] = [hit, miss]
        c["S"] = max(0.0, c["S"] + (hit if flag else miss))
        h = c["h_watch"] if (c.get("h_watch") and minute < c["watch_until"]) else c["h"]
        if c["S"] > h:
            c["alarms"].append({"event_id": eid, "minute": minute, "S": round(c["S"], 3), "h": h})
            c["S"] = 0.0

    def _flush(self, buf):
        st = self.state
        for wid, b in buf.items():
            ws = st.wfs[wid]
            if b["pick"]:
                a = np.array(b["pick"], dtype=np.int64)
                np.add.at(ws.pick, (a[:, 0], a[:, 1], a[:, 2], 0), 1)
                np.add.at(ws.pick, (a[:, 0], a[:, 1], a[:, 2], 1), a[:, 3])
                a = np.array(b["did"], dtype=np.int64)
                np.add.at(ws.did, (a[:, 0], a[:, 1], 0), 1)
                np.add.at(ws.did, (a[:, 0], a[:, 1], 1), a[:, 2])
                a = np.array(b["kpi"], dtype=np.int64)
                np.add.at(ws.kpi_h, (a[:, 0], 0), 1)
                for j in (1, 2, 3):
                    np.add.at(ws.kpi_h, (a[:, 0], j), a[:, j])
            if b["prompt"]:
                a = np.array(b["prompt"], dtype=np.int64)
                np.add.at(ws.prompt, (a[:, 0], a[:, 1], 0), 1)
                np.add.at(ws.prompt, (a[:, 0], a[:, 1], 1), a[:, 2])
                np.add.at(ws.prompt, (a[:, 0], a[:, 1], 2), a[:, 3])
            if b["concl"]:
                a = np.array(b["concl"], dtype=np.int64)
                np.add.at(ws.leads_concluded, (a[:, 0], a[:, 1]), 1)
            for xid, rows in b["exp"].items():
                a = np.array(rows, dtype=np.int64)
                cnt = ws.exps[xid]["counts"]
                np.add.at(cnt, (a[:, 0], a[:, 1], a[:, 2], 0), 1)
                np.add.at(cnt, (a[:, 0], a[:, 1], a[:, 2], 1), a[:, 3])
                np.add.at(cnt, (a[:, 0], a[:, 1], a[:, 2], 2), a[:, 4])
