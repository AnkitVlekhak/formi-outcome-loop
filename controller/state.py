"""In-memory aggregate state: dense numpy counters per workflow, plus the small
amount of sequential detector state (CUSUM) that must survive restarts.

Persistence model (event sourcing + snapshots): the whole State is written as
one .npz every simulated hour, tagged with the last chunk it contains. On
restart we load the newest snapshot and replay every chunk after it from the
simulator (`GET /events/chunks/{n}`), which rebuilds the exact same arrays.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from . import cells

DAY_OFF = 30          # supports up to 30 history days before D0
MAX_EXP_DAYS = 16     # experiment accumulator horizon (days since start)
HOURS_PER_DAY = 24


class WfState:
    ARRAYS = ["lead_cell", "lead_day", "pick", "did", "kpi_h", "prompt", "leads_up", "leads_concluded"]

    def __init__(self, info: dict, n_days: int):
        self.id = info["workflow_id"]
        self.info = info
        o = info["options"]
        self.opt = {d: list(o[d]) for d in ("welcome_message", "voice", "caller_id", "prompt_version")}
        self.idx = {d: {v: i for i, v in enumerate(vals)} for d, vals in self.opt.items()}
        nD, nP = len(self.opt["caller_id"]), len(self.opt["prompt_version"])
        self.lead_cell = np.zeros(4096, dtype=np.uint8)
        self.lead_day = np.zeros(4096, dtype=np.int16)
        self.n_leads = 0
        self.pick = np.zeros((n_days, HOURS_PER_DAY, cells.N_CELLS, 2), dtype=np.int32)    # dials, connected
        self.did = np.zeros((n_days * 24, nD, 2), dtype=np.int32)                         # per abs hour
        self.kpi_h = np.zeros((n_days * 24, 4), dtype=np.int32)                           # dials, conn, eng, flag
        self.prompt = np.zeros((n_days, nP, 3), dtype=np.int32)                           # conn, eng, flag
        self.leads_up = np.zeros((n_days, cells.N_CELLS), dtype=np.int32)
        self.leads_concluded = np.zeros((n_days, cells.N_CELLS), dtype=np.int32)          # by campaign day
        self.cusum = {"S": 0.0, "p0": None, "p1": None, "h": None, "h_watch": None, "watch_until": -1,
                      "alarms": [], "last_event": 0}
        self.exps: dict[str, dict] = {}
        self.supervisor_events: list[dict] = []
        self.config_events: list[dict] = []
        self.campaign_version: dict[str, int] = {}
        self.history_flags: list[int] = []   # transient: per connected call during history, for calibration

    def ensure_leads(self, n: int):
        if n <= len(self.lead_cell):
            return
        cap = max(n, 2 * len(self.lead_cell))
        for name in ("lead_cell", "lead_day"):
            a = getattr(self, name)
            b = np.zeros(cap, dtype=a.dtype)
            b[: len(a)] = a
            setattr(self, name, b)

    # -------------------------------------------------------------- (de)serialisation
    def to_arrays(self, prefix: str) -> dict:
        out = {f"{prefix}{k}": getattr(self, k) for k in self.ARRAYS}
        out[f"{prefix}lead_cell"] = self.lead_cell[: self.n_leads]
        out[f"{prefix}lead_day"] = self.lead_day[: self.n_leads]
        for eid, e in self.exps.items():
            out[f"{prefix}exp|{eid}"] = e["counts"]
        return out

    def meta(self) -> dict:
        return {"n_leads": self.n_leads, "cusum": self.cusum,
                "exps": {k: {kk: vv for kk, vv in v.items() if kk != "counts"} for k, v in self.exps.items()},
                "supervisor_events": self.supervisor_events, "config_events": self.config_events,
                "campaign_version": self.campaign_version}


class State:
    def __init__(self):
        self.wfs: dict[str, WfState] = {}
        self.infos: list[dict] = []
        self.last_chunk = -1
        self.last_event_id = 0
        self.end_minute = 0
        self.n_days = 0
        self.calibration: dict = {}

    @classmethod
    def new(cls, infos: list[dict], end_minute: int) -> "State":
        s = cls()
        s.infos = infos
        s.end_minute = end_minute
        s.n_days = DAY_OFF + end_minute // 1440 + 2
        for info in infos:
            s.wfs[info["workflow_id"]] = WfState(info, s.n_days)
        return s

    # -------------------------------------------------------------- indexing
    def day_idx(self, minute: int) -> int:
        return minute // 1440 + DAY_OFF

    def hour_idx(self, minute: int) -> int:
        return minute // 60 + DAY_OFF * 24

    # -------------------------------------------------------------- experiments
    def add_experiment(self, wf: str, exp_id: str, dim: str, arms: list[str], start_version: int, start_minute: int):
        ws = self.wfs[wf]
        if exp_id in ws.exps:
            return
        ws.exps[exp_id] = {"dim": dim, "arms": list(arms), "start_version": int(start_version),
                           "start_day": start_minute // 1440, "active": True,
                           "counts": np.zeros((MAX_EXP_DAYS, len(arms), cells.N_CELLS, 3), dtype=np.int32)}

    def stop_experiment(self, wf: str, exp_id: str):
        if exp_id in self.wfs[wf].exps:
            self.wfs[wf].exps[exp_id]["active"] = False

    # -------------------------------------------------------------- snapshots
    def save(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        arrays = {}
        for i, (wid, ws) in enumerate(self.wfs.items()):
            arrays.update(ws.to_arrays(f"w{i}|"))
        meta = {"infos": self.infos, "last_chunk": self.last_chunk, "last_event_id": self.last_event_id,
                "end_minute": self.end_minute, "calibration": self.calibration,
                "wfs": {wid: ws.meta() for wid, ws in self.wfs.items()}}
        arrays["__meta__"] = np.frombuffer(json.dumps(meta).encode(), dtype=np.uint8)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "wb") as f:
            np.savez(f, **arrays)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str | Path) -> "State":
        z = np.load(path, allow_pickle=False)
        meta = json.loads(bytes(z["__meta__"]).decode())
        s = cls.new(meta["infos"], meta["end_minute"])
        s.last_chunk, s.last_event_id = meta["last_chunk"], meta["last_event_id"]
        s.calibration = meta["calibration"]
        for i, (wid, ws) in enumerate(s.wfs.items()):
            m = meta["wfs"][wid]
            p = f"w{i}|"
            for k in WfState.ARRAYS:
                a = z[p + k]
                if k in ("lead_cell", "lead_day"):
                    ws.ensure_leads(len(a))
                    getattr(ws, k)[: len(a)] = a
                else:
                    setattr(ws, k, a.copy())
            ws.n_leads = m["n_leads"]
            ws.cusum = m["cusum"]
            ws.supervisor_events = m["supervisor_events"]
            ws.config_events = m["config_events"]
            ws.campaign_version = m["campaign_version"]
            for eid, e in m["exps"].items():
                ws.exps[eid] = {**e, "counts": z[f"{p}exp|{eid}"].copy()}
        return s
