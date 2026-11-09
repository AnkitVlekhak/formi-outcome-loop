"""Crash-recovery test: SIGKILL the controller at random moments, restart it, let it finish,
then check against the simulator's own log that nothing was lost or done twice.

    .venv/bin/python scripts/crash_test.py --scenario scenarios/public_02_incidents.yaml --kills 5

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
PY = str(ROOT / ".venv/bin/python") if (ROOT / ".venv/bin/python").exists() else sys.executable


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="scenarios/public_02_incidents.yaml")
    ap.add_argument("--kills", type=int, default=5)
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
    try:
        for k in range(a.kills):
            p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            wait = rnd.uniform(1.5, 4.0)
            time.sleep(wait)
            st = httpx.get(url + "/sim/state").json()
            if p.poll() is not None:
                log(f"run {k + 1}: controller exited before kill (rc={p.returncode})")
                break
            os.kill(p.pid, signal.SIGKILL)
            p.wait()
            log(f"kill {k + 1}: SIGKILL after {wait:.1f}s wall at sim {st['ts']} (minute {st['sim_minute']})")
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        log(f"final run: rc={p.returncode}; resumed lines: "
            + "; ".join(l for l in p.stdout.splitlines() if l.startswith("[startup]")))
        if p.returncode:
            log(p.stderr[-3000:])
        st = httpx.get(url + "/sim/state").json()
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
    g = subprocess.run([PY, "-m", "sim", "grade", "--run", str(run), "--baseline", str(base), "--out",
                        str(ROOT / f"reports/crash_{name}.md")], cwd=ROOT, capture_output=True, text=True)
    ok = all(checks.values())
    out = ["# Crash-recovery test", "", f"Scenario `{a.scenario}`, {a.kills} SIGKILLs at random wall-clock moments, "
           "then a final run to completion. Same `--state-dir` every time.", "", "```"] + log_lines + ["```", "",
           "| check | result |", "|---|---|"] + [f"| {k} | {'PASS' if v else 'FAIL'} |" for k, v in checks.items()] + [
           "", f"Approval requests: {len(req)} · applied via approval: {len(applied)} · "
               f"credits used: {s.credits_spent():.0f}", "",
           f"Grade of the crashed run: `reports/crash_{name}.md` (compare with the uninterrupted `reports/{name}.md`).",
           "", f"**Overall: {'PASS' if ok else 'FAIL'}**"]
    (ROOT / "reports/crash_test.md").write_text("\n".join(out) + "\n")
    print("\n".join(out[-12:]))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
