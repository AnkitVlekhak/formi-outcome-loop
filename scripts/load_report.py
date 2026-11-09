"""Summarise a load run from the controller's own metrics table → reports/load_public_03.md

    .venv/bin/python scripts/load_report.py state/public_03_load logs/ctl_public_03_load.time
"""
import re
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

state, timef = Path(sys.argv[1]), Path(sys.argv[2])
c = sqlite3.connect(f"file:{state / 'ctl.db'}?mode=ro", uri=True)
by = defaultdict(dict)
for m, k, v in c.execute("select sim_minute, k, v from metrics"):
    by[m][k] = v
days = defaultdict(lambda: defaultdict(float))
for m, d in by.items():
    for k, v in d.items():
        days[(m - 1) // 1440][k] += v
t = timef.read_text()
real = float(re.search(r"([\d.]+) real", t).group(1))
rss = int(re.search(r"(\d+)\s+maximum resident set size", t).group(1)) / 2 ** 20
dec = sorted(d["decide_s"] for d in by.values() if "decide_s" in d)
tick = sorted(d["tick_s"] for d in by.values() if "tick_s" in d)
L = ["| sim day | events | wall s (whole tick loop) | of which simulator advance | controller ingest | controller decide+govern | snapshot | ingest events/s |",
     "|---|---|---|---|---|---|---|---|"]
for d in sorted(days):
    x = days[d]
    L.append(f"| D{d} | {int(x['events']):,} | {x['tick_s']:.1f} | {x['advance_s']:.1f} | {x['ingest_s']:.1f} | "
             f"{x['decide_s']:.2f} | {x['snapshot_s']:.1f} | {int(x['events'] / max(x['ingest_s'], 1e-9)):,} |")
day_wall = statistics.mean(days[d]["tick_s"] for d in days)
L += ["", f"- **Wall-clock per simulated day: {day_wall:.1f} s** (budget 600 s) — including the simulator's own compute.",
      f"- Whole run incl. startup (7 history days ingested): {real:.0f} s · **peak RSS {rss:.0f} MB** (budget 8 GB).",
      f"- Decision lag per tick (detect+decide+govern after ingest): p50 {statistics.median(dec) * 1000:.0f} ms, "
      f"p99 {dec[int(len(dec) * .99)] * 1000:.0f} ms, max {dec[-1] * 1000:.0f} ms.",
      f"- Tick (advance+ingest+decide) p50 {statistics.median(tick):.2f} s, max {tick[-1]:.2f} s "
      f"(max = 08:00 batch upload, 192k lead events in one tick).",
      f"- Store after 5 days: ctl.db {Path(state / 'ctl.db').stat().st_size / 2 ** 20:.0f} MB "
      f"(call_log {c.execute('select count(*) from call_log').fetchone()[0]:,} rows), "
      f"snapshot {Path(state / 'snapshot.npz').stat().st_size / 2 ** 20:.0f} MB."]
out = "\n".join(["# Load test — public_03_load (12 workflows, ~840k events/day)", "",
                 "Measured on an Apple-silicon laptop (single process, 1 core busy). Numbers from the controller's own "
                 "`metrics` table and `/usr/bin/time -l`.", ""] + L) + "\n"
Path("reports/load_public_03.md").write_text(out)
print(out)
