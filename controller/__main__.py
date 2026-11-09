"""CLI.

  python -m controller run    --url http://127.0.0.1:8700 [--state-dir state] [--api-port 8800] [--no-call-log]
  python -m controller why    --state-dir state --wf nw_renewal --at "D3 14:00"
  python -m controller heard  --state-dir state --wf nw_renewal --lead 12345
  python -m controller status --state-dir state
"""
import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="controller")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--url", required=True)
    r.add_argument("--state-dir", default="state")
    r.add_argument("--api-port", type=int, default=0)
    r.add_argument("--no-call-log", action="store_true")
    r.add_argument("--max-ticks", type=int, default=0)
    for name in ("why", "heard", "status"):
        p = sub.add_parser(name)
        p.add_argument("--state-dir", default="state")
        if name in ("why", "heard"):
            p.add_argument("--wf", required=True)
        if name == "why":
            p.add_argument("--at", required=True)
        if name == "heard":
            p.add_argument("--lead", type=int, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        from .loop import Controller
        c = Controller(a.url, a.state_dir, keep_call_log=not a.no_call_log, max_ticks=a.max_ticks or None,
                       log=lambda m: print(m, flush=True))
        if a.api_port:
            from .api import serve_in_thread
            Path(a.state_dir).mkdir(parents=True, exist_ok=True)
            c._api_port = a.api_port
        out = c.run() if not a.api_port else _run_with_api(c, a)
        print(json.dumps(out, indent=2, default=str))
        return
    from .store import Store
    s = Store(Path(a.state_dir) / "ctl.db", readonly=True)
    if a.cmd == "why":
        from .audit import why
        print(json.dumps(why(s, a.wf, a.at), indent=2, default=str))
    elif a.cmd == "heard":
        from .audit import customer_heard
        print(json.dumps(customer_heard(s, a.wf, a.lead), indent=2, default=str))
    elif a.cmd == "status":
        rows = s.conn.execute("select state, count(*) from proposals group by state").fetchall()
        print(json.dumps({"proposals": {r[0]: r[1] for r in rows},
                          "incidents": [(i["incident_id"], i["state"]) for i in s.incidents()],
                          "experiments": [(x["exp_id"], x["state"], x.get("winner")) for x in s.experiments()],
                          "alerts": [dict(r) for r in s.conn.execute("select * from alerts order by sim_minute desc limit 10")]},
                         indent=2, default=str))


def _run_with_api(c, a):
    from .api import serve_in_thread
    c.startup_hook = None
    orig = c.startup

    def startup():
        orig()
        serve_in_thread(str(Path(a.state_dir) / "ctl.db"), a.api_port)
        print(f"[api] http://127.0.0.1:{a.api_port}/docs", flush=True)
    c.startup = startup
    return c.run()


if __name__ == "__main__":
    main()
