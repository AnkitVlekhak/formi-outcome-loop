"""Generate hidden-like scenario variants: same schema as the public scenarios, different truth.

This is the guard against tuning to public truth. Each variant re-draws effects
(sign, size, target cohort, decay), incidents (which caller ID, when, which
workflow ships a bad prompt, mid-experiment supervisor edits), caller-ID base
health and governance noise. Deterministic per seed.

    python evals/make_variants.py --n 6 --out evals/scenarios
"""
import argparse
import copy
import random
from pathlib import Path

import yaml

FEATS = {"lang": ["hi", "en", "ta", "kn"], "age_band": ["18-30", "31-45", "46-60", "60+"], "city_tier": ["1", "2", "3"]}
MULTS = [0.85, 0.9, 0.94, 1.06, 1.1, 1.14, 1.2]


def variant(base: dict, seed: int) -> dict:
    r = random.Random(seed)
    sc = copy.deepcopy(base)
    sc["name"] = f"variant_{seed:03d}"
    sc["seed"] = 1000 + seed
    sc["days"] = r.choice([8, 9, 10])
    sc["prompts"]["P2"] = {"summary": "Supervisor edit: adds urgency language and benefit claims",
                           "halluc": r.choice([0.03, 0.045, 0.06]), "engage_mult": r.choice([0.9, 0.95, 1.02])}
    effects, incidents = [], []
    wfs = [w for t in sc["tenants"] for w in t["workflows"]]
    for wf in wfs:
        wf["did_base_health"] = {}
        if r.random() < 0.4:
            wf["did_base_health"][r.choice(wf["options"]["caller_id"][1:])] = r.choice([0.5, 0.6, 0.7])
        g = wf["governance"]
        g["base_reject_rate"] = r.choice([0.05, 0.1, 0.2])
        lo = r.choice([20, 30, 60]); g["approver_latency_minutes"] = [lo, lo + r.choice([90, 180, 300])]
        if "P2" not in wf["options"]["prompt_version"] and r.random() < 0.5:
            wf["options"]["prompt_version"].append("P2")
        for _ in range(r.randint(2, 4)):
            dim = r.choice(["welcome_message", "voice"])
            val = r.choice(wf["options"][dim][1:])
            e = {"workflow": wf["id"], "dim": dim, "value": val, "mult": r.choice(MULTS)}
            if r.random() < 0.5:
                f = r.choice(list(FEATS))
                e["where"] = {f: r.sample(FEATS[f], r.randint(1, 2))}
            if e["mult"] > 1 and r.random() < 0.3:
                e["decay"] = {"after_exposure_days": r.choice([2, 3]), "to_mult": r.choice([0.9, 0.95]), "over_days": 2}
            effects.append(e)
    w = r.choice(wfs)
    incidents.append({"type": "did_flagged", "workflow": w["id"], "did": r.choice(w["default_config"]["allocations"]
                      ["default"]["caller_id"] and list(w["default_config"]["allocations"]["default"]["caller_id"])),
                      "at": f"D{r.randint(1, 4)} {r.randint(10, 17)}:{r.choice(['00', '30'])}",
                      "base_health": r.choice([0.3, 0.4, 0.5])})
    bad = [w for w in wfs if "P2" in w["options"]["prompt_version"]]
    if bad:
        w = r.choice(bad)
        incidents.append({"type": "supervisor_edit", "workflow": w["id"], "at": f"D{r.randint(2, 5)} {r.randint(10, 16)}:30",
                          "patch": {"prompt_version": "P2"}, "note": "bad prompt"})
    w = r.choice(wfs)
    dim = r.choice(["voice", "welcome_message"])
    incidents.append({"type": "supervisor_edit", "workflow": w["id"], "at": f"D{r.randint(3, 6)} {r.randint(10, 17)}:00",
                      "patch": {"allocations": {"default": {dim: {r.choice(w["options"][dim]): 1}}}},
                      "note": "supervisor edits mid-experiment"})
    sc["effects"], sc["incidents"] = effects, incidents
    return sc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="scenarios/public_02_incidents.yaml")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--first", type=int, default=1)
    ap.add_argument("--out", default="evals/scenarios")
    a = ap.parse_args()
    base = yaml.safe_load(open(a.base))
    Path(a.out).mkdir(parents=True, exist_ok=True)
    for s in range(a.first, a.first + a.n):
        p = Path(a.out) / f"variant_{s:03d}.yaml"
        p.write_text(yaml.safe_dump(variant(base, s), sort_keys=False))
        print(p)
