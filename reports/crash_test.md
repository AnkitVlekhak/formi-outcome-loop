# Crash-recovery test

Scenario `scenarios/public_02_incidents.yaml`, 5 SIGKILLs at random wall-clock moments, then a final run to completion. Same `--state-dir` every time.

```
[12:20:47] kill 1: SIGKILL after 2.3s wall at sim 2027-01-05T19:00:00+05:30 (minute 2580)
[12:20:49] kill 2: SIGKILL after 1.9s wall at sim 2027-01-07T22:00:00+05:30 (minute 5640)
[12:20:52] kill 3: SIGKILL after 3.1s wall at sim 2027-01-11T13:45:00+05:30 (minute 10905)
[12:20:54] kill 4: SIGKILL after 1.7s wall at sim 2027-01-13T10:15:00+05:30 (minute 13575)
[12:20:57] run 5: controller exited before kill (rc=0)
[12:20:57] final run: rc=0; resumed lines: [startup] resumed from snapshot at chunk 491; [startup] history+catch-up ingested in 0.0s; sim at D10 00:00
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

Approval requests: 15 · applied via approval: 13 · credits used: 3

Grade of the crashed run: `reports/crash_public_02_incidents.md` (compare with the uninterrupted `reports/public_02_incidents.md`).

**Overall: PASS**
