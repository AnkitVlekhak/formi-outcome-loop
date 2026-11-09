"""Crash-recovery test: SIGKILL the controller at targeted and random moments, restart it, let it
finish, then check against the simulator's own log that nothing was lost or done twice.

    .venv/bin/python scripts/crash_test.py --scenario scenarios/public_02_incidents.yaml --kills 3

Phase 1 (targeted): one run per crash point in controller/crashpoint.py, in sim-time order. The
controller SIGKILLs itself at the most dangerous moment of that code path (side effect accepted by
the simulator, not yet recorded in our store). A point the scenario never reaches is reported.
Phase 2 (random): --kills SIGKILLs from outside at random wall-clock moments.

Checks
  * the run finishes (scenario end reached)
  * every approval the simulator received maps to exactly one proposal in our store (no orphans/dupes)
  * no approval applied twice, no proposal stuck in SUBMITTING, no lapsed approval
  * the store's audit chain explains every controller config version
Writes reports/crash_test.md (and the grade of the crashed run).
"""
import argparse
import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from controller.crashpoint import POINTS  # noqa: E402

# roughly the sim-time order in which public_02 first reaches each point; ":n" = crash on the n-th hit
# (the first chunks and snapshot happen during startup; the later hits are mid-run, during the D0 working day)
ORDER = ["chunk_ingested:60", "snapshot_tmp_written:3", "auto_step_put", "approval_posted", "apply_posted",
         "validation_spent"]
PY = str(ROOT / ".venv/bin/python") if (ROOT / ".venv/bin/python").exists() else sys.executable


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="scenarios/public_02_incidents.yaml")
    ap.add_argument("--kills", type=int, default=3, help="random external kills after the targeted ones")
    ap.add_argument("--points", default=",".join(ORDER), help="comma-separated crash points (empty = none)")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    name = Path(a.scenario).stem
    run, base, state = ROOT / f"runs/crash_{name}", ROOT / f"runs/base_{name}", ROOT / f"state/crash_{name}"
    log_lines = []

    def log(m):
        line = f"[{time.strftime('%H:%M:%S')}] {m}"
        print(line, flush=True)
        log_lines.append(line)

    if not base.exists():
        subprocess.run([PY, "-m", "sim", "baseline", "--scenario", a.scenario, "--run-dir", str(base)], cwd=ROOT, check=True)
    subprocess.run(["rm", "-rf", str(state)])
    srv = subprocess.Popen([PY, "-m", "sim", "serve", "--scenario", a.scenario, "--run-dir", str(run), "--port",
                            str(a.port), "--force"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import httpx
    url = f"http://127.0.0.1:{a.port}"
    for _ in range(240):
        try:
            httpx.get(url + "/health", timeout=1); break
        except Exception:
            time.sleep(0.5)
    cmd = [PY, "-m", "controller", "run", "--url", url, "--state-dir", str(state)]
    credits0 = httpx.get(url + "/sim/state").json()["credits_remaining"]
    points = [(x.split(":")[0], x.split(":")[1] if ":" in x else "1") for x in a.points.split(",") if x]
    fired, finished_early = {}, False
    env0 = {k: v for k, v in os.environ.items() if not k.startswith("CTL_CRASH")}
    try:
        for pt, nth in points:
            p = subprocess.run(cmd, cwd=ROOT, env={**env0, "CTL_CRASH_AT": pt, "CTL_CRASH_NTH": nth},
                               capture_output=True, text=True)
            st = httpx.get(url + "/sim/state").json()
            fired[pt] = p.returncode == -signal.SIGKILL and f"SIGKILL at {pt}" in p.stderr
            if fired[pt]:
                log(f"crash point {pt} (hit #{nth}): SIGKILL at sim {st['ts']} (minute {st['sim_minute']}) — {POINTS[pt]}")
            else:
                log(f"crash point {pt}: not reached, controller finished (rc={p.returncode})")
                finished_early = True
                break
        n_random = 0
        for k in range(0 if finished_early else a.kills):
            p = subprocess.Popen(cmd, cwd=ROOT, env=env0, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            wait = rnd.uniform(1.5, 4.0)
            time.sleep(wait)
            st = httpx.get(url + "/sim/state").json()
            if p.poll() is not None:
                log(f"random kill {k + 1}: controller had already finished (rc={p.returncode}); no kill")
                break
            os.kill(p.pid, signal.SIGKILL)
            p.wait()
            n_random += 1
            log(f"random kill {k + 1}: SIGKILL after {wait:.1f}s wall at sim {st['ts']} (minute {st['sim_minute']})")
        p = subprocess.run(cmd, cwd=ROOT, env=env0, capture_output=True, text=True)
        log(f"final run: rc={p.returncode}; resumed lines: "
            + "; ".join(l for l in p.stdout.splitlines() if l.startswith("[startup]")))
        if p.returncode:
            log(p.stderr[-3000:])
        st = httpx.get(url + "/sim/state").json()
        credits_used = credits0 - st["credits_remaining"]
    finally:
        srv.terminate(); srv.wait()

    from controller import audit
    from controller.store import Store
    s = Store(state / "ctl.db", readonly=True)
    sim_log = [json.loads(l) for l in (run / "sim_log.jsonl").read_text().splitlines() if l.strip()]
    req = [r for r in sim_log if r["kind"] == "approval_requested"]
    applied = [r for r in sim_log if r["kind"] == "approval_applied"]
    ours = {p["approval_id"]: p for p in s.proposals() if p["approval_id"]}
    checks = {
        "scenario finished": st["finished"],
        "every simulator approval request maps to one proposal in our store":
            len(req) == len({r["approval_id"] for r in req}) == len(ours) and all(r["approval_id"] in ours for r in req),
        "no approval applied twice": len(applied) == len({r["approval_id"] for r in applied}),
        "no proposal stuck in SUBMITTING": not s.proposals(states=["SUBMITTING"]),
        "no lapsed approvals": not any(r["kind"] == "approval_lapsed" for r in sim_log),
        "auto-apply duplicates rejected by idempotency (none expected)":
            not any(r["kind"] == "auto_apply_rejected" for r in sim_log),
    }
    unexplained = []
    for w in s.meta_get("workflows"):
        for v in s.config_versions(w["workflow_id"]):
            if (v["actor"] or "").startswith("controller"):
                ans = audit.why(s, w["workflow_id"], v["sim_minute"])
                if not ans.get("proposal_id"):
                    unexplained.append((w["workflow_id"], v["version"]))
    checks["every controller config version explained by the audit store"] = not unexplained
    for pt, _ in points:
        checks[f"crash point `{pt}` fired"] = fired.get(pt, False)
    g = subprocess.run([PY, "-m", "sim", "grade", "--run", str(run), "--baseline", str(base), "--out",
                        str(ROOT / f"reports/crash_{name}.md")], cwd=ROOT, capture_output=True, text=True)
    ok = all(checks.values())
    n_fired = sum(fired.values())
    out = ["# Crash-recovery test", "",
           f"Scenario `{a.scenario}`, same `--state-dir` throughout. {n_fired} targeted SIGKILLs (the controller "
           f"kills itself at a named crash point, see `controller/crashpoint.py`), then {n_random} SIGKILLs from "
           "outside at random wall-clock moments, then a final run to completion.", "",
           "| crash point | the moment it kills |", "|---|---|"] + [f"| `{k}` | {POINTS[k]} |" for k, _ in points] + [
           "", "```"] + log_lines + ["```", "",
           "| check | result |", "|---|---|"] + [f"| {k} | {'PASS' if v else 'FAIL'} |" for k, v in checks.items()] + [
           "", f"Approval requests: {len(req)} · applied via approval: {len(applied)} · "
               f"credits used (simulator): {credits_used:g} · credits in our ledger: {s.credits_spent():g}", "",
           "A crash at `validation_spent` loses the result of a paid validation run (the validation API has no "
           "idempotency key), so the run is paid for again after restart; the gap between the two credit "
           "numbers is that re-spend.", "",
           f"Grade of the crashed run: `reports/crash_{name}.md` (compare with the uninterrupted `reports/{name}.md`).",
           "", f"**Overall: {'PASS' if ok else 'FAIL'}**"]
    (ROOT / "reports/crash_test.md").write_text("\n".join(out) + "\n")
    print("\n".join(out[-12:]))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
