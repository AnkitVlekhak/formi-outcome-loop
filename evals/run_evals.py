"""Run the controller on every scenario in a directory, grade each against its own
baseline, and write one summary table. Usage:

    python evals/run_evals.py evals/scenarios/*.yaml --out reports/eval_variants.md
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv/bin/python") if (ROOT / ".venv/bin/python").exists() else sys.executable


def run_one(sc: Path, port: int) -> dict:
    name = sc.stem
    base, mine, state = ROOT / f"runs/base_{name}", ROOT / f"runs/mine_{name}", ROOT / f"state/eval_{name}"
    subprocess.run([PY, "-m", "sim", "baseline", "--scenario", str(sc), "--run-dir", str(base)], cwd=ROOT,
                   check=True, capture_output=True)
    srv = subprocess.Popen([PY, "-m", "sim", "serve", "--scenario", str(sc), "--run-dir", str(mine), "--port",
                            str(port), "--force"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import httpx
        for _ in range(240):
            try:
                httpx.get(f"http://127.0.0.1:{port}/health", timeout=1); break
            except Exception:
                time.sleep(0.5)
        subprocess.run(["rm", "-rf", str(state)])
        t0 = time.time()
        r = subprocess.run([PY, "-m", "controller", "run", "--url", f"http://127.0.0.1:{port}", "--state-dir",
                            str(state)], cwd=ROOT, capture_output=True, text=True)
        wall = time.time() - t0
        if r.returncode:
            return {"scenario": name, "error": r.stderr[-2000:]}
    finally:
        srv.terminate(); srv.wait()
    g = json.loads(subprocess.run([PY, "-m", "sim", "grade", "--run", str(mine), "--baseline", str(base), "--json"],
                                  cwd=ROOT, capture_output=True, text=True, check=True).stdout)
    return summarise(name, g, wall)


def summarise(name, g, wall):
    import yaml
    out = {"scenario": name, "wall_s": round(wall, 1)}
    d = g["delta_vs_baseline"]
    out["conclusion_all"] = d["ALL"]["conclusion_rate"]
    v = g["controller_changes"]["verdicts"]
    out.update(applied=g["controller_changes"]["count"], harmful=v.get("harmful", 0), beneficial=v.get("beneficial", 0))
    gv = g["governance"]
    out.update(lapsed=gv["lapsed"], expired=gv["decisions"].get("expired", 0), auto_rejected=gv["auto_apply_rejected"],
               rejected=gv["decisions"].get("rejected", 0), requests=gv["approval_requests"])
    mttr = [i.get("mttr_minutes") for i in g["incidents"] if "mttr_minutes" in i]
    out["prompt_mttr_min"] = mttr
    did = [i["flagged_did_share_by_day"] for i in g["incidents"] if i["type"] == "did_flagged"]
    out["flagged_did_share_next_day"] = [list(x.values())[2] if len(x) > 2 else None for x in did]
    dec = g["decaying_variant_share_after_onset"]
    out["decay_share_last_day"] = {k: list(v.values())[-1] for k, v in dec.items()}
    sc = yaml.safe_load(open(ROOT / f"evals/scenarios/{name}.yaml")) if (ROOT / f"evals/scenarios/{name}.yaml").exists() else None
    guard = []
    for wid, m in d.items():
        if wid == "ALL":
            continue
        guard.append((wid, round(m["pickup_rate"] or 0, 3), round(m["engagement_rate"] or 0, 3)))
    out["per_wf_pickup_eng_delta"] = guard
    out["credits"] = g["credits_used"]
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="+")
    ap.add_argument("--out", default="reports/eval_variants.md")
    ap.add_argument("--port", type=int, default=8750)
    a = ap.parse_args()
    rows = []
    for i, s in enumerate(a.scenarios):
        res = run_one(Path(s), a.port + i)
        print(json.dumps(res), flush=True)
        rows.append(res)
    L = ["# Robustness eval — hidden-like variants", "",
         "Each variant re-draws the hidden truth (effects, decays, incidents, caller-ID health, approver noise). "
         "Graded against its own no-op baseline with the official grader.", "",
         "| scenario | conclusion Δ | applied | harmful | beneficial | requests | rejected | expired | lapsed | "
         "prompt MTTR (min) | flagged DID share next day | decaying-variant share, last day | credits | wall s |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "error" in r:
            L.append(f"| {r['scenario']} | ERROR | | | | | | | | | | | | |")
            continue
        L.append(f"| {r['scenario']} | {r['conclusion_all'] * 100:+.1f}% | {r['applied']} | {r['harmful']} | "
                 f"{r['beneficial']} | {r['requests']} | {r['rejected']} | {r['expired']} | {r['lapsed']} | "
                 f"{r['prompt_mttr_min']} | {r['flagged_did_share_next_day']} | {r['decay_share_last_day']} | "
                 f"{r['credits']:.0f} | {r['wall_s']} |")
    ok = [r for r in rows if "error" not in r]
    if ok:
        L += ["", f"**Mean conclusion Δ {sum(r['conclusion_all'] for r in ok) / len(ok) * 100:+.1f}%** · "
                  f"harmful changes {sum(r['harmful'] for r in ok)} of {sum(r['applied'] for r in ok)} applied · "
                  f"lapsed {sum(r['lapsed'] for r in ok)} · expired {sum(r['expired'] for r in ok)}", "",
              "Per-workflow pickup / engagement deltas (guardrail check):", ""]
        for r in ok:
            L.append(f"- {r['scenario']}: " + ", ".join(f"{w} pickup {p * 100:+.1f}% eng {e * 100:+.1f}%"
                                                         for w, p, e in r["per_wf_pickup_eng_delta"]))
    Path(a.out).write_text("\n".join(L) + "\n")
    print("wrote", a.out)
