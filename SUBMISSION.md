# Outcome-First Agent Loop — Submission

**Name:** Ankit Lekhak · **Date:** 2026-11-09 · **Hours actually spent:** _fill in honestly_ (built with Claude Code as a pair; every decision below is one I can defend) · **Language / storage:** Python 3.12, SQLite (WAL) + one numpy snapshot file. No new infrastructure. Postgres slots in behind `controller/store.py` in production.

---

## 0. TL;DR

- **What it does:** an always-on controller ingests events into per-cell counters. It detects caller-ID degradation, hallucination spikes and KPI drift. It runs factorial welcome×voice experiments with deterministic stopping, holdouts and decay rollback, and fits per-cohort call-time weights from pre-D0 history. Every change goes out as one batched, evidenced proposal through approval or policy-permitted auto-apply.
- **Results:**
  - public_01: business outcome **+13.3%**, 0 harmful changes.
  - public_02: business outcome **+27.6%**, 0 harmful changes. The bad prompt was fixed in **225 min** (detected 34 min after it shipped), and the flagged caller ID was off traffic within 2h 15m.
  - Six hidden-like variants: mean **+20.8%**, 3 harmful out of 132 applied changes.
- **Scale:** one simulated day of public_03_load takes **__LOAD_DAY__ s** wall-clock against a 10-minute budget. Crash-safe under repeated SIGKILL.
- **Not built:** per-person call time, cross-tenant fairness, a UI (there is a JSON supervisor view), and promoting winners across clients.

## 1. Assumptions

1. Guardrail `*_max_drop: 0.02` is an **absolute** drop in the rate (e.g. pickup 0.28 → 0.26). I check it as a non-inferiority bound on the arm comparison.
2. "Leads concluded ÷ leads uploaded" is the business outcome. **Impact score** is expected extra concluded leads per day, normalised to [0,1] as `x/(x+25)`. Incident fixes count each avoided hallucinated call as 5 concluded leads.
3. Welcome message and voice are heard only after pickup, so they cannot move pickup. Their metric is engagement. Pickup is still checked as a guardrail on every promotion.
4. Caller-ID rotation and call timing are "operational" and may auto-apply **where the workflow policy allows**. Compliance's letter grants this, but the `nw_kyc` policy does not (see §3).
5. The pre-D0 history ran the business default with no schedule. That makes it an unbiased (cohort × hour) pickup table, but it carries no welcome/voice variant evidence.
6. A supervisor edit is a decision by the client. I lock the dimension they touched, stop experiments on it, and only revert it through an approval labelled "REVERTS A SUPERVISOR EDIT (with evidence)".
7. One controller instance per simulator world. Running two writers against one state dir is out of scope; production would use a leader lease.
8. The tenant ids in hidden scenarios match the public ones, for the stakeholder overrides. If they don't, policy defaults apply, so the controller is never *less* safe.
9. An expired proposal is a rejection (Product). Its intents are re-queued and **rebuilt from fresh data and the live config**, never resubmitted as-is.

## 2. Scope decisions

| # | Capability | Built / Partial / Cut | Why | What it would take to finish |
|---|---|---|---|---|
| C1 | Ingestion | **Built** | Everything depends on it; load proof required | Columnar parse for 10× (§8) |
| C2 | Shared cohort object | **Built** | 252 feature cells; a cohort is a cell set; stats per cell, so any cohort is evaluable after the fact | — |
| C3 | Bootstrap from history | **Built** | Calibrates CUSUM baselines and false-alarm thresholds, plus cohort × hour pickup for scheduling | Use history for engagement priors (none exist: default only) |
| C4 | Call-time optimisation | **Partial** (cohort only) | Cohort level gives most of the gain at no risk | Per-person: returning people only, with shrinkage (§5) |
| C5 | Caller-ID health | **Built** | Biggest pickup lever; spreading load is the industry rule | Model load → health to separate "burned by volume" from "spam-flagged" |
| C6 | Experiments | **Built** | Factorial, deterministic stopping, Bonferroni, cohort split | Bayesian hierarchical model across workflows |
| C7 | Promotion / decay / rollback | **Built** | Holdout + within-arm decay test with drift guard | Always-on small holdout per cohort |
| C8 | Hallucination incident | **Built** | Detect → candidate → validate → propose → verify | Learn the LLM's candidate quality over time |
| C9 | Governance client | **Built** | State machine, batching, timing, budgets, stale/expired/lapsed, auto-apply stepping | Approver-fatigue model per person |
| C10 | Impact / affected leads / dry runs | **Built** | Dry run replays history (schedule) or arm posteriors (experiments) | Off-policy replay with importance weights |
| C11 | Supervisor view | **Partial** | JSON `GET /supervisor/{tenant}`, one screen per tenant | Minimal UI over that endpoint |
| C12 | Audit store | **Built** | `ctl why` / `ctl heard`; every decision stored with inputs and rule | — |
| C13 | Crash recovery | **Built** | Snapshot + replay + reconciliation; SIGKILL test | — |
| C14 | Loop observability | **Partial** | `metrics` table / `GET /metrics`, alert table with runbook text | Prometheus exporter |
| C15 | Fair credits / attention across tenants | **Cut** | Credits were never the binding constraint (≤13 per scenario) | Per-tenant credit buckets + request quota |

**Principle:** build what the hidden scenarios grade *and* what can't be bolted on later: correctness under governance, crash safety, auditability. After that, the levers with the largest expected effect per unit of risk: caller ID, schedule, incident response. Then experiments, which have real lift but high variance at dev volume. Cut what nothing depends on.

## 3. Stakeholders

### 01 — Nikhil Rao, Sales
- **Accepted:** speed where it's free. Auto-apply wherever policy allows (Kestrel caller ID, schedule, welcome, voice). Urgent fixes go out on the best-case approver latency.
- **Declined:**
  - A blended score: pickup and engagement stay separate (non-negotiable 3 / Product).
  - "Winner by lunch, live for everyone by evening": a winner needs ≥2 days, ≥400 connected calls per arm and z ≥ 2.9. Kestrel moves at most 0.2 total-variation per auto change.
  - Rolling out "persuasive" P4 everywhere.
- **Wrong claims:**
  - "Kestrel turned on auto-apply for everything": prompts are **not** in `allowed_dims`, and every auto change is capped at `max_shift 0.2`.
  - "Northwind is fine with auto-apply on KYC": `nw_kyc.auto_apply.enabled: false`.
  - P4 hallucinates at ~2.5%. Its validation pass rate sits on the 0.97 bar (expected ~0.9725), so it passes small runs by luck. My lower-bound rule rejects it.
- **Reply:** "Nikhil — you'll get a per-client lift number, pickup and engagement shown separately (blending them hides which lever worked). Kestrel's caller-ID, timing and opener/voice changes already go live without waiting, within their policy limits. Prompts aren't auto-approvable for anyone, and Northwind KYC has auto-apply off in its signed policy. 'Persuasive' hallucinates about 4× our current prompt and barely scrapes validation, so it won't ship to regulated clients. Winners need two days of evidence; a one-day 'winner' is wrong about 1 time in 5 at our volumes."

### 02 — Meera Iyer, Compliance (Northwind)
- **Accepted, all of it:**
  - Every customer-facing change on Northwind goes through approval (`OVERRIDES.northwind_life`).
  - Prompt changes carry a validation run id plus our own observed flag rates.
  - The IRDAI question is answered by `ctl heard --lead N`: every call with its variant, config version, proposal, approver and rationale.
  - Approvals are timed inside 10–19 (KYC 10–18) and never sent when they'd expire overnight.
- **Wrong claim:** "timing and caller-ID rotation are covered by the policy we signed". That's true for renewal, but **`nw_kyc` has auto-apply disabled**, so even caller-ID moves there go to an approver.
- **Reply:** "Meera — confirmed: nothing a customer hears changes without your named approver, and script changes always attach a validation run. For any customer and day we can produce the exact opener, voice, prompt and caller ID they got, the change that made it live, who approved it and why — in minutes, not 24 hours. One correction: on KYC your policy does not allow auto-apply at all, so timing and caller-ID changes there also come to your approvers. The weekly summary will list renewal's auto changes."

### 03 — Kabir Menon, Platform/SRE
- **Accepted:**
  - Kill/restart test (§9).
  - Idempotency: deterministic proposal ids, adopt-on-duplicate, reconcile on boot.
  - No new stateful infrastructure: SQLite + one file now, Postgres in production.
  - Actionable alerts only, each carrying runbook text (§10).
  - Loop health in `/metrics`.
  - One load day in well under 10 minutes.
- **Pushed back:** nothing material. The one dependency added is `orjson` (stateless; about 5× faster parsing on the hot path).
- **Reply:** "Kabir — SQLite in WAL mode inside the process plus a snapshot file; no new servers. In prod it's your Postgres behind the same store class. SIGKILL test is in `reports/crash_test.md`: five kills, no lost or doubled approvals. One load day is __LOAD_DAY__s wall-clock on a laptop. At 10× the Python ingest loop is first to break; the fix is per-workflow shards (plan in §8). Pages only for lapsed approvals, credits, unresolvable incidents and controller bugs, each with what to look at."

### 04 — Anita Desai, Ops Supervisor (Kestrel)
- **Accepted:**
  - ≤2 requests/day and nothing before 11:00 (stricter than policy's 4 from 10:00; `OVERRIDES.kestrel_finance`).
  - One batched request per slot.
  - Her prompt edits are never undone silently: a revert is a labelled, evidenced request she approves.
  - Customer-facing auto changes are announced and applied only after 60 min notice, inside 11–19.
  - A one-screen view: `/supervisor/kestrel_finance`.
  - The "compliance-script" trap: P5 (strict) is never chosen by safety alone. Candidates are ranked by **observed engagement** among known-safe prompts, and post-apply engagement is recorded.
- **Tension (not a false claim):** policy lets us auto-change a running campaign (`mid_flight: allowed`). I chose announce-then-apply over asking for approval every time, so we keep the speed and she still hears first.
- **Reply:** "Anita — you'll get at most two requests a day, never before 11, each one bundling everything. Your prompt edits stay unless you approve a revert; if we think one is causing hallucinations you'll see the numbers and the validation result in the request. Opener/voice tests change on running campaigns only after a 60-minute heads-up on your screen. That screen shows what's being tested, what's winning, what we need from you and what changed today."

### 05 — Tara Kulkarni, Product
- **Accepted:**
  - Separate KPIs.
  - One cohort object (cells, §5).
  - Proposals carrying impact, diff, affected leads and dry run.
  - Expired = rejected and rebuilt fresh.
  - **Only actual traffic counts:** stats are keyed on the variant each call event really had, from the version that started the experiment (so locked `next_campaign_only` campaigns don't pollute it).
  - Winners stay inside their workflow.
- **Pushed back:** of three P0s I built caller-ID health and a JSON supervisor view, and cut per-person call time:
  - most leads get 2–8 attempts;
  - 20–40% are returning;
  - a wrong `lead_preferred_hour` multiplies weight by 0.25 in every other hour.

  The minimum cohort and window answers are in §5.
- **Reply:** "Tara — cohort = a set of feature cells; detection, experiments and the supervisor view use the same ids. Minimum: 400 connected calls per arm and 2 days; that detects ~12% lifts in a week at dev volume with a ≤4.5% false-winner rate (measured, not assumed). Impact score = expected extra concluded leads/day, so ranking is meaningful. I cut per-person call time: most people get 2–8 attempts, and wrong per-person hours suppress them 4× elsewhere. Cohort-level timing already moves pickup +6–16%."

### 06 — Aryamann, CTO
- **Accepted:**
  - Explainability over raw lift, and the asymmetric cost of hurting a cohort (aggressive harm stops, per-cohort protection).
  - "No compute": known-good prompts from our own data before any LLM call. Public scenarios used 0–3 credits.
  - Scale-first design and honest breakpoints (§8, §13).
- **Wrong claims across the memos:** the four above (Kestrel "everything", Northwind KYC auto-apply, Compliance's KYC latitude, P4).
- **Reply:** "Choices: caller ID, schedule and incidents first (biggest, safest effect), experiments second. Cut per-person timing, cross-tenant fairness and UI. Every decision is in the store with its inputs and rule. The weakest part is experiments at dev volume: 10% challenger arms need days to separate, so most experiment value shows up at load-scenario volumes."

## 4. Architecture

```
        Simulator (HTTP)                       controller process (single writer)
 ┌────────────────────────┐   advance   ┌──────────────────────────────────────────────────────────────┐
 │ /sim/advance           │◄────────────│ Loop: advance → ingest → detect → decide → govern → verify   │
 │ /events/chunks/{n}     │────chunks──►│  Ingestor (orjson) ─► lead→cell map ─► counters per cell:      │
 │ /workflows/{id}/config │             │     pick[day,hour,cell], did[hour,D], kpi[hour], prompt[day,P], │
 │ /approvals  /apply     │◄─proposals──│     exp[day,arm,cell]   + Bernoulli CUSUM per workflow          │
 │ PUT /config (auto)     │             │  Detectors: caller-ID health · hallucination CUSUM · KPI drift  │
 │ /validation  /llm      │             │  Deciders: schedule fit · caller-ID allocation · experiments ·  │
 └────────────────────────┘             │            decay · incident manager      ─► intents (DB)        │
                                        │  Builder: merge intents on live config → diff, affected leads,  │
                                        │           dry run, impact, rationale                            │
                                        │  Governance: gate (hours/TTL/budget/precedence) → approval or  │
                                        │              auto stepping → poll → apply → hooks               │
                                        │  Read API thread: /supervisor /why /heard /metrics /alerts      │
                                        └───────┬─────────────────────────────────────┬────────────────────┘
                                                │ SQLite WAL (ctl.db)                  │ snapshot.npz (hourly)
                                                ▼                                      ▼
                     decisions · intents · proposals · experiments · incidents · did_status ·
                     credits · config_versions · call_log · metrics · alerts
```

**Restart:**
1. Fingerprint the world; archive the state if it's a new world.
2. Load the snapshot.
3. Replay chunks after the snapshot's chunk from `GET /events/chunks/{n}`; ingestion is idempotent.
4. Reconcile `SUBMITTING`/`STEPPING` proposals against the simulator.
5. Resume.

## 5. The learning loop

- **Cohorts.**
  - The atom is a feature **cell** (7 lang × 3 tier × 4 age × 3 value = 252). A cohort is a rectangle of cells, so it's expressible as a `where` clause.
  - The partition feature is chosen from history by a χ² test of hour × level pickup (p < 1e-3). The data pick `age_band`; nothing is hard-coded.
  - At most ~16 cohorts. Cohort-level experiment decisions need ≥400 connected calls per arm *inside* the cohort and a stricter z ≥ 3.2. Small cohorts never fragment traffic; they inherit `default`.

- **Experiment design.**
  - Welcome and voice are randomised independently per call, so they run as a **factorial**: each dimension's arms are compared marginalising the other, and one approval tests both.
  - Exploration starts with challengers at 10% each and the incumbent at ≥40%. Sized so that a −10% arm costs <1% expected engagement, the grader's "harmful" line.
  - Arms that look good ramp to 20%.
  - Allocation updates are a **batched bandit**: about one update per day, because governance allows 2–4 requests per day. A continuous bandit can't run under this approval regime.

- **Deciding a winner.**
  - Deterministic test: two-proportion z on engagement, counted by actual variant since the experiment's start version.
  - Daily looks, z ≥ 2.9, ≥400 connected calls per arm, ≥2 days, plus four extra conditions:
    - the last day not reversed;
    - **trend test**: lift not significantly fading, which guards against novelty effects;
    - pickup guardrail;
    - Bonferroni over ≤8 looks × 3 challengers.
  - **Measured A/A false-winner rate < 5%** (`test_aa_false_winner_rate_under_threshold`).
  - **Harm stop:** z ≤ −1.28 over the test, or z ≤ −1.64 over the last 2 days, with ≥200 connected calls. Deliberately asymmetric: dropping a neutral arm costs nothing, keeping a bad one costs engagement.

- **Decay and rollback.**
  - Promotion keeps a 10% holdout on the old incumbent.
  - Daily check: the winner's engagement now vs during its test.
  - With no observable global change (prompt change or supervisor edit) in between, a significant drop (z ≤ −2.58) is enough. Otherwise the holdout must confirm it (difference-in-differences z ≤ −1.64). A winner significantly behind its concurrent holdout is rolled back regardless.
  - Measured over seeds, two daily looks:

    | Case | Rolled back |
    |---|---|
    | Decay to well below incumbent | 99% |
    | Decay to just below incumbent | 82% |
    | Winner fades but stays ahead (correctly kept) | 3.5% |
    | Stable winner | 0% |
    | Global drift with a known cause | ≤10% (test-asserted) |

  - On public_01, decayed W3 was off traffic two days after promotion.

- **Call time and caller ID.**
  - **Call time:** per-cohort hour weights are the relative pickup advantage, shrunk (200 dials), clipped to [0.3, 3]. All window hours are kept positive. Dry-run replay on history predicts the pickup change.
  - **Per person:** cut (see Tara's reply).
  - **Caller ID:** because caller IDs are randomised per dial, siblings are directly comparable in the same window. Flag when ratio < 0.8 **and** z ≤ −3.5. The window grows until both the number and its reference have ≥120 dials.
  - **New numbers:** probed at 6%, and graduate only when **confidently** above 0.8× their siblings.
  - **Volume:** spread evenly over healthy numbers.
  - **Measured false-flag rate:** <0.5% per assessment in control.

- **Guardrail KPI.** Every promotion checks the arm's pickup z > −2.33 against the incumbent. Per-workflow pickup and engagement deltas are tracked in every eval.

## 6. Governance

```
approval: SUBMITTING ─POST─► PENDING ─approved─► apply ─► APPLIED ─► (24h) post_apply record
              │dup→adopt          ├─rejected→ REJECTED   (reopen: fatigue +6h, judgement +12h, incident 0)
              │422→DROPPED+page   ├─expired → EXPIRED    (= rejection; reopened, rebuilt from fresh data)
                                  ├─apply 409→ STALE     (reopened, rebuilt on the live config)
                                  ├─apply 410→ LAPSED    (page: we missed the window)
                                  └─routine approved while an incident fix is pending on the same base → DEFERRED
auto:     STEPPING ─PUT ≤max_shift─► … ─► APPLIED;  live version moved by someone else → STALE;  403 → via approval
```

- **Batching:**
  - All open intents for a workflow merge into **one** config on top of the live one. A higher priority wins a (cohort, dimension) conflict.
  - Priorities: incident 0, caller-ID flag 1, rollback 2, rebalance 3, schedule 4, exploration 5.
  - At most one request in flight per workflow.
- **Timing gate:**
  - Inside approver hours (and stakeholder hours).
  - Worst-case decision time before the TTL. Urgent changes use the best-case latency instead: an expiry costs one request, waiting overnight costs a day of harm.
  - Rolling 24h budget = policy (or stricter override) minus one slot reserved for incidents.
  - Result: **0 lapsed and 0–1 expired across 8 scenarios.**
- **Auto-apply:** used only when every changed dimension is allowed **and** no stakeholder rule needs a human. It is voluntarily *not* used for:
  - Northwind customer-facing dimensions;
  - anything touching a supervisor edit;
  - Kestrel customer-facing changes before the notice period.
  
  Shifts above `max_shift` are applied as multiple TV-bounded steps.
- **Honesty of numbers:**
  - *Affected leads* = active leads (uploaded in the cadence window minus concluded) in the cells whose experience changes. For `next_campaign_only` allocation changes: the next batch × the share of affected cells.
  - *Dry run:* schedule = replay of the pre-D0 cohort × hour table, pool depletion ignored and stated. Experiments = shrunk per-arm posteriors under current vs proposed allocation. Caller ID = relative pickup per number.
  - *Impact score:* expected extra concluded leads per day, normalised as x/(x+25).
- **Supervisor edits mid-experiment:**
  - Detected from `config_changed` (actor supervisor).
  - The dimension is locked, experiments on it are INTERRUPTED (data closed at the version boundary), and their open intents are superseded.
  - A pending proposal built on the old base fails stale and is rebuilt on the supervisor's config. Their edit stays.

## 7. Incidents

- **Detection:** a Bernoulli CUSUM on the QA hallucination flag over connected calls.
  - p₀ comes from history (1.4–1.9%); p₁ = 3p₀.
  - `h = max(5, 1.3 × max in-control S over history)`, about 5–8. History is in-control by definition, so it produces **0 false alarms over 14 days** by construction.
  - For 48h after a supervisor prompt edit, h drops to 0.6h (watch mode).
- **Confirmation:** exact binomial tail since the live prompt started. Threshold p < 1e-3, or p < 1e-2 within 72h of a prompt change.
  - Needs a cause: a prompt change, or the live prompt's own rate ≥ 2p₀. Otherwise page a human and spend nothing.
- **Fix:**
  - Known-good prompts from **our own data** first (flag rate ≤ 1.5p₀, ranked by engagement). The LLM is only called when there is none.
  - Validation n=300 (3 credits). Accept only if the one-sided 95% Wilson lower bound ≥ the policy bar. Borderline results get exactly one n=1000 run, never repeated small runs (that would be p-hacking).
  - Proposed at priority 0 with the validation id.
- **Verify:** post-fix hours only; flag rate ≤ 2p₀ on ≥200 connected calls → RESOLVED. Otherwise try the next candidate and page.
- **Credits used:** public_01: 0 · public_02: 3 · variants: 3–13.

**public_02 timeline (from `ctl why` / decisions):**

| Sim time | Event |
|---|---|
| D2 10:00 | (hidden) caller ID D2 on `ks_cancel` degrades |
| D2 12:00 | `did_flag` D2: ratio 0.53, z −5.7 vs D1/D3 → urgent intent; auto-steps v6, v7 |
| D2 12:15 | D2 at 0% (flagged-number share: day 2 8%, day 3+ 0%) |
| D3 11:30 | supervisor ships P2 → dimension locked, CUSUM watch mode |
| D3 12:04 | CUSUM alarm |
| D3 13:00 | confirmed (exact p = 3e-6 since the edit) → candidate P1 (own data, flag 1.5%, engagement 0.50) → validation 0.987 @ n=300 → proposal "REVERTS A SUPERVISOR EDIT (with evidence)" |
| D3 15:15 | approved and applied (v10) — **MTTR 225 min** |
| D3 19:00 | verified: flag rate back to baseline → RESOLVED |

## 8. Scale (public_03_load, 12 workflows, ~800k events/day, M-series laptop)

__LOAD_TABLE__

**What breaks at 10× (8M events a day, 500k+ dials an hour):**
1. **The Python per-event ingest loop.** It runs at about 150k events/s, i.e. ~1 min of CPU per 10× day. That's fine for throughput, but it's single-core and blocks decisions while it runs.
2. **`call_log` inserts.** About 6.5M rows a day in SQLite → move to Parquet/object storage, or `--no-call-log`.
3. **The `lead_preferred_hour` 200k cap,** if per-person timing is ever built.
4. **Approver attention,** which doesn't scale with dials at all.

**Partitioning:**
- Shard workflows by `hash(workflow_id)` across ingest+decide workers. Every state array is already per workflow, with no cross-workflow reads.
- Events on Kafka keyed by workflow, with the offset committed alongside the snapshot.
- Governance per tenant behind a leader lease.
- Store moves to Postgres; snapshots go to object storage.

## 9. Reliability

__CRASH__

- **Idempotency keys:**
  - `proposal_id = ctl-<wf>-v<base>-<sha(target, intents)>`; auto steps are `<pid>.s<k>`.
  - Decisions: `sha(kind, wf, minute, subject)`.
  - Intents: `sha(wf, kind, subject, minute, patch)`.
  - `call_log`: `event_id`.
- **4xx/5xx handling:**
  - 5xx and transport errors: retry with backoff.
  - `/sim/advance`: never blindly retried; re-read state first.
  - 409 duplicate → adopt. 409 stale → rebuild. 410 → re-propose and page. 403 → re-route to approval. 402 → freeze spend and page. 422 → drop and page.
- **Lost on crash:** at most one hour of aggregates, rebuilt by replay. An in-flight LLM/validation call may be repeated (marked `reserved` in `credits`).

## 10. Audit & observability

`python -m controller why --state-dir state/public_02_incidents --wf ks_cancel --at "D3 16:00"` (abridged real output):

```json
{ "live_version": 10, "actor": "controller_approved", "changed_at": "D3 15:15", "changed_dims": ["prompt_version"],
  "answer": "REVERTS A SUPERVISOR EDIT (with evidence): switch prompt P2 -> P1: hallucination flags 9.0% vs baseline 1.5%",
  "proposal_id": "ctl-ks_cancel-v9-7675a1f3124cc1ce", "route": "approval", "approval_id": "apr_00006",
  "approved_by": "client approver (approval path)", "submitted_at": "D3 13:00",
  "impact_score": 0.9481, "affected_leads": 3641, "diff": {"prompt_version": {"from": "P2", "to": "P1"}},
  "rationale": "[incident] CUSUM alarm confirmed (exact p=3.4e-06); candidate from own data (known-good prompts); validation pass rate 0.9867 on n=300 (decision a5cff76afe7b1267bba3)",
  "evidence_decisions": [{"kind": "incident_fix", "at": "D3 13:00", "rule": "known-good prompt first, then LLM; validated before proposing", ...}],
  "lifecycle": [{"kind": "submit", "at": "D3 13:00"}, {"kind": "applied", "at": "D3 15:15"}, {"kind": "post_apply", "at": "D4 15:00"}],
  "what_happened_next": [{"24h_before": {"halluc_flag_rate": ...}, "24h_after": {...}}] }
```

- **Page on:**
  - a lapsed approval;
  - credits below cost;
  - a hallucination spike with no cause;
  - no safe prompt;
  - a fix that didn't work;
  - 422 from the simulator.
- **Don't page** (morning digest instead):
  - rejections and expiries (handled);
  - caller-ID flags (handled automatically);
  - KPI drift;
  - experiments with no difference.

## 11. Results

__RESULTS__

## 12. Trade-offs & rejected alternatives

| Option | Why considered | Why rejected / what instead |
|---|---|---|
| Continuous Thompson-sampling bandit | Industry default (GrowthBook, Stitch Fix) | Each reallocation is a governance request (2–4/day). Used a **batched**, deterministic schedule; TS-style probability matching is noted as future work |
| Always-valid / mSPRT inference | Peeking-safe | With ≤8 pre-planned looks, Bonferroni-adjusted fixed z is simpler, auditable, and A/A-verified |
| Raw event store + SQL aggregation | Flexible | 850k events/day → per-cell counters in numpy are ~100× smaller and replayable from the simulator |
| Postgres/Redis now | SRE already runs them | Embedded SQLite is zero-ops for a single writer; same store interface ports to Postgres |
| Rotating to the healthiest caller ID | Common practice | Concentration burns numbers (volume is the cause); spread evenly instead |
| Calling the LLM on every incident | Spec mentions it | Our own data already knows which prompts are safe; LLM only when no known-good prompt exists (0 LLM calls in public runs) |
| Per-person preferred hours | Product's summit headline | Sparse data, 0.25× penalty off-hour; cohort timing already captures most of the gain |
| Holdout-only decay test | Textbook | Too noisy at 10% holdout and dev volume; use within-arm test when no observable global change |

## 13. Known weaknesses

1. **Exploration can be judged harmful.** With random truths, about 1 in 6 scenarios has an exploration bundle whose expected engagement falls >1%, from bad arms at 10% each. Measured: 3 harmful of 132 changes across the variants. A smaller start share would cut that but slow learning further.
2. **Dev-volume power.** Experiments rarely conclude within 8–10 days. Most experiment value appears at load volume. Cohort-level winners almost never qualify at dev scale.
3. **Caller ID:** "burned by our own volume" and "spam-flagged" aren't distinguished. A flagged number is retired for the rest of the run, even if it would recover.
4. **KYC (`next_campaign_only`):** allocation changes, caller-ID retirement included, only reach new campaigns. A flagged number keeps dialling old campaigns for up to 3 days (variant_003: 56% next day).
5. **Call-level engagement dilution.** Higher pickup re-connects people who previously didn't engage. Small (measured ~0.1pp) but real.
6. **Slow detection for mild prompt issues.** A bad prompt at ~2× baseline on a low-volume workflow can take 6–20h to detect.
7. **Credits re-spend after a crash.** An in-flight validation may run twice; the API has no idempotency key for it.
8. **Single writer.** No leader election.

## 14. If this went to production at Formi next month

1. **Week 1:**
   - Shadow mode on 3 real workflows: compute decisions and proposals, apply nothing.
   - Compare the caller-ID and incident detectors to on-call history to calibrate thresholds on real false-alarm rates.
2. Move the store to Postgres and events to the Kafka consumer (offset with snapshot). Add a leader lease and Prometheus metrics.
3. Ship caller-ID load spreading and hallucination incident response first: highest value, lowest risk, clear audit story for compliance.
4. Supervisor view UI over `/supervisor`, plus a weekly auto-change summary for Northwind compliance.
5. **Week 2:** experiments on two consenting workflows with a pre-registered analysis plan; review every promotion with the client for the first month.
6. A per-tenant credit and request quota (C15) before onboarding the next 10 tenants.
