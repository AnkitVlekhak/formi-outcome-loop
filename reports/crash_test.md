# Crash-recovery test

Scenario `scenarios/public_02_incidents.yaml`, same `--state-dir` throughout. 6 targeted SIGKILLs (the controller kills itself at a named crash point, see `controller/crashpoint.py`), then 2 SIGKILLs from outside at random wall-clock moments, then a final run to completion.

| crash point | the moment it kills |
|---|---|
| `chunk_ingested` | counters updated in memory, chunk not yet committed to the store |
| `snapshot_tmp_written` | snapshot .tmp fsynced, not yet renamed over the live snapshot |
| `auto_step_put` | auto-apply PUT accepted, step not yet recorded |
| `approval_posted` | POST /approvals accepted, proposal still SUBMITTING in our store |
| `apply_posted` | approved change applied on the simulator, not yet APPLIED in our store |
| `validation_spent` | validation run paid for, result not yet recorded |

```
[13:55:44] crash point chunk_ingested (hit #60): SIGKILL at sim 2027-01-05T11:00:00+05:30 (minute 2100) — counters updated in memory, chunk not yet committed to the store
[13:55:44] crash point snapshot_tmp_written (hit #3): SIGKILL at sim 2027-01-05T13:00:00+05:30 (minute 2220) — snapshot .tmp fsynced, not yet renamed over the live snapshot
[13:55:45] crash point auto_step_put (hit #1): SIGKILL at sim 2027-01-05T16:00:00+05:30 (minute 2400) — auto-apply PUT accepted, step not yet recorded
[13:55:46] crash point approval_posted (hit #1): SIGKILL at sim 2027-01-07T10:00:00+05:30 (minute 4920) — POST /approvals accepted, proposal still SUBMITTING in our store
[13:55:46] crash point apply_posted (hit #1): SIGKILL at sim 2027-01-07T12:45:00+05:30 (minute 5085) — approved change applied on the simulator, not yet APPLIED in our store
[13:55:47] crash point validation_spent (hit #1): SIGKILL at sim 2027-01-07T13:00:00+05:30 (minute 5100) — validation run paid for, result not yet recorded
[13:55:49] random kill 1: SIGKILL after 2.3s wall at sim 2027-01-09T19:45:00+05:30 (minute 8385)
[13:55:51] random kill 2: SIGKILL after 1.9s wall at sim 2027-01-11T18:30:00+05:30 (minute 11190)
[13:55:54] random kill 3: controller had already finished (rc=0); no kill
[13:55:54] final run: rc=0; resumed lines: [startup] resumed from snapshot at chunk 491; [startup] history+catch-up ingested in 0.0s; sim at D10 00:00
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
| crash point `chunk_ingested` fired | PASS |
| crash point `snapshot_tmp_written` fired | PASS |
| crash point `auto_step_put` fired | PASS |
| crash point `approval_posted` fired | PASS |
| crash point `apply_posted` fired | PASS |
| crash point `validation_spent` fired | PASS |

Approval requests: 14 · applied via approval: 12 · credits used (simulator): 6 · credits in our ledger: 3

A crash at `validation_spent` loses the result of a paid validation run (the validation API has no idempotency key), so the run is paid for again after restart; the gap between the two credit numbers is that re-spend.

Grade of the crashed run: `reports/crash_public_02_incidents.md` (compare with the uninterrupted `reports/public_02_incidents.md`).

**Overall: PASS**
