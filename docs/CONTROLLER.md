# Controller — operator's guide

For the engineer who gets paged. Design rationale lives in `SUBMISSION.md`; this is how to run, debug and extend it.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # adds only orjson to the given deps
./run.sh http://127.0.0.1:8700                     # runs until the scenario ends; resumes if restarted
CTL_API_PORT=8800 ./run.sh http://127.0.0.1:8700   # + read API at http://127.0.0.1:8800/docs
CTL_STATE_DIR=state/x ./run.sh <url>               # state dir (default ./state)
CTL_NO_CALL_LOG=1 ./run.sh <url>                   # skip the per-call audit table (saves ~30% ingest time at 10x)
```

Full local loop for one scenario (baseline, serve, controller, grade): `scripts/run_scenario.sh scenarios/public_02_incidents.yaml`.

| Command | What it is for |
|---|---|
| `make test` / `.venv/bin/python -m pytest` | 61 controller tests + simulator smoke tests (~25 s) |
| `scripts/crash_test.py --kills 3` | SIGKILL/restart test: 6 targeted crash points (`controller/crashpoint.py`) then random kills; writes `reports/crash_test.md` |
| `python evals/make_variants.py --n 6 && python evals/run_evals.py evals/scenarios/*.yaml` | hidden-like robustness eval → `reports/eval_variants.md` |
| `python -m controller why --wf ks_cancel --at "D3 16:00"` | why is this config live, who approved it, what happened next |
| `python -m controller heard --wf nw_kyc --lead 123` | what a customer heard on each call and why it was live (IRDAI question) |
| `python -m controller status` | proposals by state, incidents, experiments, latest alerts |

## State and restart

```
state/
  ctl.db          SQLite (WAL). Decisions, intents, proposals, experiments, incidents, caller-ID status,
                  credits, call_log, metrics, alerts. The audit trail. Never edit by hand.
  snapshot.npz    numpy aggregates + detector state, written every simulated hour, atomic (tmp + rename).
```

On start the controller:

1. Fingerprints the simulator world (scenario name, end minute, history chunks). If the fingerprint differs, or the simulator's clock is behind ours, it is a **new world**: the old state dir is archived to `state.old-<ts>` and we start clean.
2. Loads `snapshot.npz` and replays every event chunk after the snapshot's chunk from the simulator. Ingestion is idempotent, so a replay rebuilds identical arrays.
3. Reconciles in-flight proposals against `GET /approvals` and `/config/history`:
   - A `SUBMITTING` proposal whose POST landed is adopted.
   - An auto rollout's completed steps are counted.
4. Only then resumes ticking.

**Reproducing a crash by hand:** `CTL_CRASH_AT=apply_posted ./run.sh <SIM_URL>` kills the controller right after an approved change lands on the simulator, before the store records it. Run `./run.sh <SIM_URL>` again to watch it recover. Point names and their meanings are listed in `controller/crashpoint.py`. Add `CTL_CRASH_NTH=n` to crash on the n-th hit instead of the first.

**What is lost on SIGKILL:** at most one hour of aggregates, which are rebuilt by replay. An LLM or validation call that was in flight may be re-run; that costs credits, and the `credits` table marks it `reserved` with no result. Nothing else.

## Alerts

| Severity | Message starts with | Meaning / what to do |
|---|---|---|
| **page** | `approval ... lapsed` | We missed a 2h apply window. Check tick cadence and crash timing. The change was re-queued. |
| **page** | `hallucination spike with no prompt change` | Flags rose without a prompt change. Listen to flagged calls (`call_log.flag=1`) and check the QA detector. The controller will not touch a prompt without a cause. |
| **page** | `no safe prompt candidate` / `prompt fix did not reduce` | A human must choose a prompt. Validation evidence is required for approval. |
| **page** | `out of credits` | Incidents can't be validated. Top up credits. |
| **page** | `approval POST failed: 422` | Controller bug (bad proposal body). The body is in `proposals.request_json`. |
| warn | `KPI drift` | Yesterday vs the previous 3 days at \|z\|≥3. Morning review. Check `why` for that workflow. |
| warn | `auto-apply refused` | Our routing disagreed with policy. The change was re-queued via approval. |
| info | `caller ID Dx flagged` | Already handled: traffic was moved off the number. Ask telecom ops to check its reputation. |

Loop health is at `GET /metrics` (API) or in the `metrics` table:
- `ingest_s`
- `events_per_s`
- `decide_s`
- `tick_s`
- `credits_remaining`
- `open_intents`
- `in_flight`
- `decisions_last_hour`

## Debugging recipes

```sql
-- what did the controller decide for a workflow today, with the rule it applied
select sim_minute, kind, subject, rule, outcome from decisions where workflow_id='ks_cancel' order by sim_minute;
-- why is a change not going out?  (gate reasons are logged as 'skip' decisions; budget/timing are in proposals)
select proposal_id, route, state, reasons, approval_id from proposals where workflow_id='nw_kyc';
select * from intents where workflow_id='nw_kyc' and status='open';
-- caller-ID status
select * from did_status;
```

## Extending

- **New detector:** read the arrays on `State.wfs[wid]` (per-cell, per-hour counters). Write a `decisions` row with the inputs and the rule. Emit an intent with `Store.add_intent(...)`, giving it a patch op (`alloc`, `prompt`, `partition`, `hour_weights`), a priority (0 = incident … 5 = exploration) and evidence: `summary`, `rationale`, `dry_run`, `gain_per_day`. The builder and governance do the rest (batching, routing, gates, retries, audit).
- **New counter:** add the array to `WfState.ARRAYS` and fill it in `Ingestor._flush`. Snapshots pick it up automatically.
- **New stakeholder rule:** add it to `config/tenant_overrides.json` (per tenant, with a `_source` line naming the memo or agreement). Supported keys are listed in `governance.OVERRIDE_KEYS`; a new kind of rule needs a key there plus the check that uses it. Every override must be stricter than policy. Startup logs the overrides in force and stores them in `meta.tenant_overrides`; `CTL_TENANT_OVERRIDES=<file>|none` swaps them.
- **Thresholds:** each module documents its constants at the top. The evals in `tests/ctl/test_decide.py` assert their error rates; change a constant and the eval tells you what it cost.
