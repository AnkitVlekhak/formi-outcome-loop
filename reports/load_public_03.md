# Load test — public_03_load (12 workflows, ~840k events/day)

Measured on an Apple-silicon laptop (single process, 1 core busy). Numbers from the controller's own `metrics` table and `/usr/bin/time -l`.

| sim day | events | wall s (whole tick loop) | of which simulator advance | controller ingest | controller decide+govern | snapshot | ingest events/s |
|---|---|---|---|---|---|---|---|
| D0 | 840,053 | 12.6 | 6.3 | 5.0 | 1.07 | 0.3 | 168,823 |
| D1 | 840,037 | 13.2 | 6.7 | 5.3 | 0.86 | 0.3 | 158,559 |
| D2 | 840,041 | 13.6 | 6.9 | 5.5 | 0.94 | 0.3 | 153,841 |
| D3 | 840,031 | 13.5 | 7.0 | 5.5 | 0.73 | 0.3 | 152,314 |
| D4 | 840,025 | 13.5 | 7.0 | 5.6 | 0.65 | 0.3 | 150,689 |

- **Wall-clock per simulated day: 13.3 s** (budget 600 s) — including the simulator's own compute.
- Whole run incl. startup (7 history days ingested): 88 s · **peak RSS 686 MB** (budget 8 GB).
- Decision lag per tick (detect+decide+govern after ingest): p50 11 ms, p99 67 ms, max 93 ms.
- Tick (advance+ingest+decide) p50 0.23 s, max 1.22 s (max = 08:00 batch upload, 192k lead events in one tick).
- Store after 5 days: ctl.db 187 MB (call_log 3,240,000 rows), snapshot 32 MB.
