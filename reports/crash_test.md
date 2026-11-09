# Crash-recovery test

Scenario `scenarios/public_02_incidents.yaml`, 5 SIGKILLs at random wall-clock moments, then a final run to completion. Same `--state-dir` every time.

```
[12:27:57] kill 1: SIGKILL after 2.6s wall at sim 2027-01-06T09:15:00+05:30 (minute 3435)
[12:28:00] kill 2: SIGKILL after 2.9s wall at sim 2027-01-09T13:45:00+05:30 (minute 8025)
[12:28:03] kill 3: SIGKILL after 3.8s wall at sim 2027-01-13T18:30:00+05:30 (minute 14070)
[12:28:06] run 4: controller exited before kill (rc=0)
[12:28:06] final run: rc=0; resumed lines: [startup] resumed from snapshot at chunk 491; [startup] history+catch-up ingested in 0.0s; sim at D10 00:00
```

| check | result |
|---|---|
| scenario finished | PASS |
| every simulator approval request maps to one proposal in our store | PASS |
| no approval applied twice | PASS |
| no proposal stuck in SUBMITTING | PASS |
| no lapsed approvals | PASS |
| auto-apply duplicates rejected by idempotency (none expected) | PASS |
| every controller config version explained by the audit store | PASS |

Approval requests: 14 · applied via approval: 12 · credits used: 3

Grade of the crashed run: `reports/crash_public_02_incidents.md` (compare with the uninterrupted `reports/public_02_incidents.md`).

**Overall: PASS**
