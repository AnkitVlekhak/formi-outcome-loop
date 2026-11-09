# Outcome-First Agent Loop — Submission

**Name:** Ankit Lekhak · **Date:** 2026-11-09 · **Hours actually spent:** _fill in honestly_ (built with Claude Code as a pair; every decision below is one I can defend) · **Language / storage:** Python 3.12, SQLite (WAL) + one numpy snapshot file. No new infrastructure. Postgres slots in behind `controller/store.py` in production.

---

## 0. TL;DR

1. **What it does:** an always-on controller that detects caller-ID degradation, hallucination spikes and KPI drift from per-cohort counters. It fits cohort call times from pre-D0 history, runs welcome×voice experiments with deterministic stopping and decay rollback, and sends every change as one batched, evidenced proposal through approval or policy-permitted auto-apply.
2. **public_01:** business outcome **+12.8%**, 0 harmful changes. **public_02:** **+27.3%**, 0 harmful. The bad prompt was fixed in 135 min, and the flagged caller ID was off traffic in 2h 15m.
3. **public_03_load:** **+20.6%**, 0 harmful of 76. A simulated day takes 13.3 s against a 600 s budget. Six hidden-like variants: mean **+20.5%**, 2 harmful of 128.
4. **Reliability:** SIGKILL at 6 targeted crash points plus random moments; the run still finishes with no lost or doubled approvals.
5. **Not built:** per-person call time, cross-tenant fairness, a UI (there's a JSON supervisor view), and promoting winners across clients.

## 1. Assumptions

1. Guardrail `*_max_drop: 0.02` is an **absolute** drop in the rate (e.g. pickup 0.28 → 0.26). I check it as a non-inferiority bound on the arm comparison.
2. "Leads concluded ÷ leads uploaded" is the business outcome. **Impact score** is expected extra concluded leads per day, normalised to [0,1] as `x/(x+25)`. Incident fixes count each avoided hallucinated call as 5 concluded leads.
3. Welcome message and voice are heard only after pickup, so they cannot move pickup. Their metric is engagement. Pickup is still checked as a guardrail on every promotion.
4. Caller-ID rotation and call timing are "operational" and may auto-apply **where the workflow policy allows**. Compliance's letter grants this, but the `nw_kyc` policy does not (see §3).
5. The pre-D0 history ran the business default with no schedule. That makes it an unbiased (cohort × hour) pickup table, but it carries no welcome/voice variant evidence.
6. A supervisor edit is a decision by the client. I lock the dimension they touched, stop experiments on it, and only revert it through an approval labelled "REVERTS A SUPERVISOR EDIT (with evidence)".
7. One controller instance per simulator world. Running two writers against one state dir is out of scope; production would use a leader lease.
8. The stakeholder agreements (Kestrel's 2 requests/day from 11:00, Northwind's approval for anything customer-facing) are keyed by tenant id in `config/tenant_overrides.json`. They're data, not code. Each one can only tighten policy, and a typo or unknown key stops startup. If a hidden scenario uses other tenant ids, plain policy applies, so the controller is never *less* safe. If it reuses these ids, Kestrel gets 2 requests a day instead of the 4 its policy allows. That's deliberate: the agreement was made with the client, not with a scenario.
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
| C13 | Crash recovery | **Built** | Snapshot + replay + reconciliation; SIGKILL test at 6 named crash points + random kills | Idempotency key on validation runs (needs an API change) |
| C14 | Loop observability | **Partial** | `metrics` table / `GET /metrics`, alert table with runbook text | Prometheus exporter |
| C15 | Fair credits / attention across tenants | **Cut** | Credits were never the binding constraint (≤13 per scenario) | Per-tenant credit buckets + request quota |

**Principle:** build what the hidden scenarios grade *and* what can't be bolted on later: correctness under governance, crash safety, auditability. After that, the levers with the largest expected effect per unit of risk: caller ID, schedule, incident response. Then experiments, which have real lift but high variance at dev volume. Cut what nothing depends on.

## 3. Stakeholders

### 01 — Nikhil Rao, Sales
- **Accepted:** speed where it's free. Auto-apply wherever policy allows (Kestrel caller ID, schedule, welcome, voice). Urgent fixes go out on the best-case approver latency.
- **Declined:**
  - A blended score: pickup and engagement stay separate (non-negotiable 3 / Product).
  - "Winner by lunch, live for everyone by evening": a winner needs ≥2 days, ≥400 connected calls per arm and z ≥ 2.9. Kestrel moves at most 0.2 total-variation per auto change.
  - Rolling out "persuasive" P4 everywhere. Prompt changes go through validation and approval like any other change.
- **Wrong claims:**
  - "Kestrel turned on auto-apply for everything": prompts are **not** in `allowed_dims`, and every auto change is capped at `max_shift 0.2`.
  - "Northwind is fine with auto-apply on KYC": `nw_kyc.auto_apply.enabled: false`.
  - "Wherever it's available": P4 is only in the catalog for `nw_renewal` and `ks_cancel`, not `nw_kyc` (`GET /workflows` → `prompt_catalog`).
  - "Tested well": the only safety signal the API gives is `/validation/runs`. I measured it on a throwaway simulator (not part of any graded run). P4 failed 91 of 4,000 conversations (2.3%), against 24 of 2,000 for P1 (1.2%). That's about twice the failure rate, and only just over the 0.97 bar: one of five n=300 runs came in at 0.967. The controller requires the one-sided 95% Wilson lower bound to clear the bar. At P4's rate the bound is 0.953 at n=300 and 0.968 at the one allowed escalation to n=1000, so P4 fails.
- **Reply:** "Nikhil — you'll get a per-client lift number, pickup and engagement shown separately (blending them hides which lever worked). Kestrel's caller ID and timing go live without an approval round, and opener/voice changes go live after a 60-minute heads-up to their supervisor. No client's policy lets prompts skip approval, and Northwind KYC has auto-apply off. 'Persuasive' fails safety validation twice as often as the current prompt, so it won't ship to regulated clients. Winners need two days: peeking hourly for one day picks a false 'winner' 3 times in 10, and our rule under 5%."

### 02 — Meera Iyer, Compliance (Northwind)
- **Accepted, all of it:**
  - Every customer-facing change on Northwind goes through approval (`config/tenant_overrides.json` → `northwind_life`).
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
- **Reply:** "Kabir — SQLite in WAL mode inside the process plus a snapshot file; no new servers. In prod it's your Postgres behind the same store class. SIGKILL test is in `reports/crash_test.md`: kills at the 6 worst moments (e.g. after an apply, before we record it) plus random ones; no lost or doubled approvals. One load day is 13.3s wall-clock on a laptop. At 10× the Python ingest loop is first to break; the fix is per-workflow shards (plan in §8). Pages only for lapsed approvals, credits, unresolvable incidents and controller bugs, each with what to look at."

### 04 — Anita Desai, Ops Supervisor (Kestrel)
- **Accepted:**
  - ≤2 requests/day and nothing before 11:00 (stricter than policy's 4 from 10:00; `config/tenant_overrides.json` → `kestrel_finance`).
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
- **Reply:** "Tara — cohort = a set of feature cells; detection, experiments and the supervisor view use the same ids. Minimum: 400 connected calls per arm and 2 days; once an arm is ramped to 20% that detects ~11% lifts (80% power) in a week at dev volume with a ≤4.5% false-winner rate (measured, not assumed). Impact score = expected extra concluded leads/day, so ranking is meaningful. I cut per-person call time: most people get 2–8 attempts, and wrong per-person hours suppress them 4× elsewhere. Cohort-level timing already moves pickup +6–16%."

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

  - On public_01, decaying W3 was never promoted. The novelty rule (lift trending down with no recent advantage) stopped it; its share after decay began went 20% → 7% → 0% by day 2.

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
  - Result: **0 lapsed across all 9 graded runs**; 2 expiries, both urgent best-case gambles that were resubmitted.
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
| D3 13:45 | approved and applied (v10) — **MTTR 135 min** |
| D3 17:00 | verified: flag rate back to baseline → RESOLVED |
| D5 15:00 | supervisor sets `nw_renewal` voice to 100% V2 mid-experiment → v10. Voice is locked and the voice experiment stops. The welcome-message experiment keeps running on the supervisor's config |
| D7 09:00 | daily look: W2's lift is fading (recent z −0.25) → arm dropped. The proposal is built **on v10**, so it keeps the supervisor's V2 voice |
| D7 11:30 | approved at 11:08, applied as v11 (welcome W1 100%, voice V2 untouched) |

The grader lists the D5 edit without an MTTR. It's a client decision, not an incident, so nothing was "fixed". The test is that it survived: v11 still has V2 (`sqlite3 state/public_02_incidents/ctl.db "select version, actor, dims from config_versions where workflow_id='nw_renewal'"`).

## 8. Scale (public_03_load, 12 workflows, ~800k events/day, M-series laptop)

Measured on an Apple M-series laptop, not the 4-vCPU / 8 GB Linux grading box. The controller is single-process and uses one core, so core count doesn't matter. Per-core speed on a typical cloud vCPU is perhaps 1.5–2× slower. At that rate a simulated day would take ~20–30 s against the 600 s budget, and memory (686 MB peak) is unaffected. I haven't measured it on Linux.

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

**Method** (`make crash`, full output in `reports/crash_test.md`): one public_02 run, one `--state-dir`, killed 8 times, then run to completion.
- **6 targeted kills.** `controller/crashpoint.py` has named crash points at the moments where a crash is most dangerous: the simulator has accepted a side effect, but our store hasn't recorded it yet. With `CTL_CRASH_AT=<point>` set, the controller SIGKILLs itself there. When the variable isn't set, the hook does nothing.
- **2 random kills** from outside, at random wall-clock moments (a third attempt found the run already finished).

| crash point (sim time of the kill) | what is half-done | how restart recovers |
|---|---|---|
| `chunk_ingested` (D1 11:00) | counters updated in memory, chunk not committed | resume from the last hourly snapshot and replay later chunks; `call_log` is `insert or ignore` on `event_id` |
| `snapshot_tmp_written` (D1 13:00) | new snapshot fsynced as `.tmp`, not renamed | `os.replace` is atomic, so the previous snapshot is intact; replay from it |
| `auto_step_put` (D1 16:00) | auto-apply `PUT` accepted, step not recorded | `reconcile()` finds `<pid>.s<k>` in the config history and restores the step count. A retried `PUT` gets 409 duplicate, which is adopted |
| `approval_posted` (D3 10:00) | approval request accepted, proposal still `SUBMITTING` | `reconcile()` finds the approval by `proposal_id` and moves it to `PENDING`. Nothing is re-submitted |
| `apply_posted` (D3 12:45) | approved change applied, store still says `APPROVED` | the next poll sees status `applied`, reads the version from the config history and records it. Nothing is re-applied |
| `validation_spent` (D3 13:00) | validation paid for, result not recorded | the credit row stays `reserved` and the run is repeated: **3 credits re-spent** (known weakness 7) |

| check | result |
|---|---|
| scenario finished | PASS |
| every simulator approval request maps to exactly one proposal in our store | PASS |
| no approval applied twice · none stuck in `SUBMITTING` · none lapsed | PASS |
| no auto-apply duplicates | PASS |
| every controller config version explained by the audit store | PASS |
| all 6 crash points fired | PASS |

**Cost of the 8 crashes vs the uninterrupted run:**
- Approvals: 14 requests and 12 applied, the same as the uninterrupted run.
- Bad-prompt fix: 150 minutes vs 135, because the validation crash landed mid-incident.
- Credits: 6 vs 3, which is the re-spent validation run.

Grade of the crashed run: `reports/crash_public_02_incidents.md`.

- **Idempotency keys:**
  - `proposal_id = ctl-<wf>-v<base>-<sha(target, intents)>`; auto steps are `<pid>.s<k>`.
  - Decisions: `sha(kind, wf, minute, subject)`.
  - Intents: `sha(wf, kind, subject, minute, patch)`.
  - `call_log`: `event_id`.
- **4xx/5xx handling:**
  - 5xx and transport errors: retry with backoff.
  - `/sim/advance`: never blindly retried; re-read state first.
  - 409 duplicate → adopt. 409 stale → rebuild. 410 → re-propose and page. 403 → re-route to approval. 402 → freeze spend and page. 422 → drop and page.
- **Lost on crash:** at most one hour of aggregates, rebuilt by replay. An in-flight LLM/validation call is repeated and paid for again (the row stays `reserved` in `credits`). The crash test shows this happening.

## 10. Audit & observability

`python -m controller why --state-dir state/public_02_incidents --wf ks_cancel --at "D3 16:00"` (abridged real output):

```json
{ "live_version": 10, "actor": "controller_approved", "changed_at": "D3 13:45", "changed_dims": ["prompt_version"],
  "answer": "REVERTS A SUPERVISOR EDIT (with evidence): switch prompt P2 -> P1: hallucination flags 9.0% vs baseline 1.5%",
  "proposal_id": "ctl-ks_cancel-v9-b85046757e7c7377", "route": "approval", "approval_id": "apr_00006",
  "approved_by": "client approver (approval path)", "submitted_at": "D3 13:00",
  "impact_score": 0.9481, "affected_leads": 3641, "diff": {"prompt_version": {"from": "P2", "to": "P1"}},
  "rationale": "[incident] CUSUM alarm confirmed (exact p=3.4e-06); candidate from own data (known-good prompts); validation pass rate 0.9867 on n=300 (decision d375622c60848cfeb318)",
  "evidence_decisions": [{"kind": "incident_fix", "at": "D3 13:00", "rule": "known-good prompt first, then LLM; validated before proposing", ...}],
  "lifecycle": [{"kind": "submit", "at": "D3 13:00"}, {"kind": "applied", "at": "D3 13:45"}, {"kind": "post_apply", "at": "D4 14:00"}],
  "what_happened_next": [{"24h_before": {"halluc_flag_rate": 0.0238, "engagement": 0.4926, "pickup": 0.2537},
                          "24h_after":  {"halluc_flag_rate": 0.0186, "engagement": 0.5,    "pickup": 0.2585}}] }
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

### public_01 (dev)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.383 | +12.1% | 0.259 | +5.7% | 0.518 | +5.4% | 23% | 62 (57) |
| nw_kyc | 0.449 | +22.5% | 0.290 | +19.8% | 0.605 | +1.4% | 7% | 31 (21) |
| nw_renewal | 0.450 | +8.1% | 0.278 | +5.4% | 0.551 | +1.7% | 9% | 44 (54) |
| ALL | 0.419 | +12.8% | 0.271 | +8.2% | 0.548 | +3.4% | 14% | 137 (132) |

23 applied — neutral: 10, beneficial: 13

### public_02 (incidents)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.360 | +53.0% | 0.249 | +37.5% | 0.494 | +5.6% | 35% | 76 (348) |
| nw_kyc | 0.453 | +21.3% | 0.282 | +20.1% | 0.605 | -0.5% | -4% | 38 (29) |
| nw_renewal | 0.483 | +11.5% | 0.290 | +10.6% | 0.554 | -0.1% | 13% | 53 (54) |
| ALL | 0.421 | +27.3% | 0.270 | +22.8% | 0.539 | +1.1% | 24% | 167 (431) |

25 applied — beneficial: 11, neutral: 14

Prompt incident MTTR 135 min (fixed by `controller_approved`); flagged caller-ID share: 8% on the flag day, 0% after; credits used 3.

### public_03 (load) — all 12 workflows

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ALL | 0.442 | +20.6% | 0.271 | +12.6% | 0.571 | +4.7% | 25% | 5188 (4667) |

76 applied — neutral: 26, beneficial: 50

### Robustness eval — 6 hidden-like variants (re-drawn truth, `reports/eval_variants.md`)

| scenario | conclusion Δ | applied | harmful | beneficial | requests | rejected | expired | lapsed | prompt MTTR (min) | flagged DID share next day | decaying-variant share, last day | credits | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| variant_001 | +24.1% | 25 | 0 | 13 | 14 | 1 | 1 | 0 | [1485] | [0.0] | {} | 3 | 7.5 |
| variant_002 | +20.3% | 17 | 0 | 12 | 13 | 3 | 0 | 0 | [1305] | [0.0] | {} | 13 | 7.3 |
| variant_003 | +24.3% | 21 | 1 | 9 | 11 | 1 | 0 | 0 | [2805] | [0.577] | {} | 3 | 7.6 |
| variant_004 | +13.5% | 20 | 0 | 11 | 13 | 1 | 0 | 0 | [1530] | [0.0] | {'nw_kyc:voice=V2': 0.11, 'nw_kyc:welcome_message=W2': 0.098} | 3 | 7.6 |
| variant_005 | +18.9% | 25 | 1 | 8 | 13 | 1 | 1 | 0 | [1275] | [0.0] | {'nw_renewal:welcome_message=W2': 0.0} | 3 | 9.1 |
| variant_006 | +22.0% | 20 | 0 | 15 | 11 | 1 | 0 | 0 | [2805] | [0.0] | {'nw_renewal:voice=V4': 0.0} | 13 | 9.0 |

**Mean conclusion Δ +20.5%** · harmful changes 2 of 128 applied · lapsed 0 · expired 2

**Interpretation.**
- **Where we helped:**
  - **Pickup:** caller-ID spreading plus cohort call-timing drives most of the lift. KYC workflows gain the most because their default dials everything from one number.
  - **Incident response:** hallucinated calls on public_02 fell from 431 to under 200.
  - **Engagement:** gains on the cancellation and renewal flows come from experiments that concluded (load) or harm-stopped bad arms (dev).
- **Where we were harmful:**
  - No harmful change on the public scenarios.
  - Variants: 2 of 128, both exploration bundles that put 10% on arms that turned out bad.
- **Where we were slow:**
  - Prompt fixes on low-volume KYC (2,805 min in the slowest variant): detection of a mild ~2× flag-rate shift and KYC's 2-requests/day budget.
  - Flagged caller IDs on KYC keep dialling old campaigns (`next_campaign_only`).
- **Engagement as a guardrail:**
  - KYC engagement (its guardrail) moved between −2.8% and +6.9% relative across all runs. The worst case is variant_005 `nw_kyc`: 0.575 vs 0.592, i.e. **−0.017 absolute against a 0.02 limit**. That's inside the guardrail, but it used 84% of the budget, closer than I'd like. The likely cause is pickup-driven dilution (known weakness 5): pickup rose 15% there, which brings in less-engaged people. I haven't isolated it.
  - public_02: `nw_kyc` engagement −0.5% and `nw_renewal` −0.1% relative, while their pickup rose 20% and 11% and conclusions 21% and 12%.
- **Hallucinated calls on public_03 rose in count** (5,188 vs 4,667), but the rate per connected call didn't (5.91 vs 5.98 per 1,000). Dials are identical (3.24M), so the extra flagged calls come from more people picking up, not from a worse prompt. Per workflow the rate ranges from −0.5 to +0.5 per 1,000.
- **What I'd change next:** start challengers at 5% with harm-gated ramp-up to cut exploration harm, and pre-commit a prompt-rollback path for KYC so it doesn't compete for the 2-request budget.


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

1. **Exploration can be judged harmful.** With random truths, about 1 in 6 scenarios has an exploration bundle whose expected engagement falls >1%, from bad arms at 10% each. Measured: 2 harmful of 128 changes across the six variants (variant_003 and variant_005). A smaller start share would cut that but slow learning further.
2. **Dev-volume power.** Experiments rarely conclude within 8–10 days. Most experiment value appears at load volume. Cohort-level winners almost never qualify at dev scale.
3. **Caller ID:** "burned by our own volume" and "spam-flagged" aren't distinguished. A flagged number is retired for the rest of the run, even if it would recover.
4. **KYC (`next_campaign_only`):** allocation changes, caller-ID retirement included, only reach new campaigns. A flagged number keeps dialling old campaigns for up to 3 days (variant_003: 58% next day).
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
