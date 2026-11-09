"""HTTP client for the simulator with an explicit error taxonomy.

* 5xx / transport errors on reads and idempotent writes: exponential backoff retry.
* 4xx: raised immediately as SimError(status, code, detail) — callers own the semantics
  (409 stale → rebuild, 409 duplicate → reconcile, 410 lapsed → re-propose, 402 → credit freeze).
* /sim/advance is NOT blindly retried: a timed-out advance may have happened, so we
  re-read /sim/state and only advance again if time did not move.
"""
from __future__ import annotations

import time

import httpx


class SimError(Exception):
    def __init__(self, status: int, code: str, detail=None):
        super().__init__(f"{status} {code}: {detail}")
        self.status, self.code, self.detail = status, code, detail


class SimUnavailable(Exception):
    pass


class SimClient:
    def __init__(self, url: str, client: httpx.Client | None = None, retries: int = 8, backoff: float = 0.5,
                 timeout: float = 300.0):
        self.url = url.rstrip("/")
        self.http = client or httpx.Client(base_url=self.url, timeout=timeout)
        self.retries, self.backoff = retries, backoff
        self.calls = 0

    # ------------------------------------------------------------------ core
    def _req(self, method: str, path: str, json=None, params=None, retry: bool = True, raw: bool = False):
        last = None
        for attempt in range(self.retries if retry else 1):
            try:
                self.calls += 1
                r = self.http.request(method, path, json=json, params=params)
            except httpx.TransportError as e:
                last = e
            else:
                if r.status_code < 400:
                    return r.content if raw else r.json()
                if r.status_code < 500:
                    try:
                        body = r.json()
                    except ValueError:
                        body = {"error": r.text}
                    code = body.get("error") or body.get("detail") or "http_error"
                    raise SimError(r.status_code, code if isinstance(code, str) else str(code), body.get("detail"))
                last = SimError(r.status_code, "server_error", r.text[:200])
            if self.backoff:
                time.sleep(min(self.backoff * 2 ** attempt, 30))
        raise SimUnavailable(f"{method} {path} failed after retries: {last}")

    def get(self, path, params=None, raw=False):
        return self._req("GET", path, params=params, raw=raw)

    def post(self, path, body, retry=True):
        return self._req("POST", path, json=body, retry=retry)

    def put(self, path, body, retry=True):
        return self._req("PUT", path, json=body, retry=retry)

    # ------------------------------------------------------------------ typed helpers
    def state(self):
        return self.get("/sim/state")

    def advance(self, minutes: int, expected_from: int | None = None):
        try:
            return self._req("POST", "/sim/advance", json={"minutes": minutes}, retry=False)
        except (SimUnavailable, httpx.TransportError):
            st = self.state()
            if expected_from is not None and st["sim_minute"] > expected_from:
                return st            # it did advance; caller lists chunks by checkpoint anyway
            return self._req("POST", "/sim/advance", json={"minutes": minutes})

    def chunks(self, kind: str, after: int):
        return self.get("/events/chunks", params={"kind": kind, "after": after})

    def chunk(self, n: int) -> bytes:
        return self.get(f"/events/chunks/{n}", raw=True)

    def workflows(self):
        return self.get("/workflows")

    def config(self, wid):
        return self.get(f"/workflows/{wid}/config")

    def config_history(self, wid):
        return self.get(f"/workflows/{wid}/config/history")

    def approvals(self, wid=None, status=None):
        p = {k: v for k, v in (("workflow_id", wid), ("status", status)) if v}
        return self.get("/approvals", params=p)

    def approval(self, aid):
        return self.get(f"/approvals/{aid}")
