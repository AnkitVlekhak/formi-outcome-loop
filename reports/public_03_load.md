# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.397 | +17.8% | 0.262 | +7.8% | 0.533 | +7.5% | 42% | 419 (409) |
| arav_kyc_1 | 0.487 | +35.7% | 0.274 | +27.4% | 0.610 | +1.6% | 14% | 429 (352) |
| arav_renewal_0 | 0.469 | +15.8% | 0.283 | +7.1% | 0.585 | +6.7% | 37% | 445 (408) |
| kest_cancel_2 | 0.394 | +17.0% | 0.262 | +8.2% | 0.529 | +6.1% | 43% | 433 (418) |
| kest_kyc_1 | 0.433 | +21.9% | 0.251 | +17.3% | 0.601 | +0.7% | 2% | 435 (370) |
| kest_renewal_0 | 0.451 | +12.3% | 0.285 | +7.6% | 0.562 | +3.1% | 17% | 459 (403) |
| nort_cancel_2 | 0.389 | +14.7% | 0.263 | +7.9% | 0.523 | +4.9% | 34% | 430 (368) |
| nort_kyc_1 | 0.485 | +36.2% | 0.274 | +27.3% | 0.608 | +2.1% | 10% | 414 (318) |
| nort_renewal_0 | 0.470 | +15.9% | 0.283 | +7.0% | 0.586 | +6.9% | 37% | 411 (419) |
| tide_cancel_2 | 0.387 | +12.7% | 0.261 | +6.7% | 0.523 | +4.3% | 36% | 413 (401) |
| tide_kyc_1 | 0.478 | +34.2% | 0.271 | +26.0% | 0.607 | +1.5% | 10% | 442 (376) |
| tide_renewal_0 | 0.468 | +15.8% | 0.285 | +7.9% | 0.581 | +6.5% | 35% | 458 (425) |
| ALL | 0.442 | +20.6% | 0.271 | +12.6% | 0.571 | +4.7% | 25% | 5188 (4667) |

## Changes applied by the controller

76 applied — neutral: 26, beneficial: 50

- nort_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.012 → **neutral**
- nort_cancel_2 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- kest_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.012 → **neutral**
- arav_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.012 → **neutral**
- arav_cancel_2 v2 (controller_auto) dims=['welcome_message', 'voice', 'caller_id'] engageΔ=+0.001 didΔ=+0.006 → **neutral**
- tide_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.012 → **neutral**
- tide_cancel_2 v2 (controller_auto) dims=['welcome_message', 'voice', 'caller_id'] engageΔ=+0.001 didΔ=+0.006 → **neutral**
- arav_cancel_2 v3 (controller_auto) dims=['welcome_message', 'voice', 'caller_id'] engageΔ=+0.001 didΔ=+0.003 → **neutral**
- tide_cancel_2 v3 (controller_auto) dims=['welcome_message', 'voice', 'caller_id'] engageΔ=+0.001 didΔ=+0.003 → **neutral**
- kest_renewal_0 v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.056 → **beneficial**
- nort_renewal_0 v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.057 → **beneficial**
- arav_renewal_0 v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.057 → **beneficial**
- tide_renewal_0 v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.057 → **beneficial**
- arav_cancel_2 v4 (controller_approved) dims=['cohorts', 'schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.025 → **beneficial**
- tide_cancel_2 v4 (controller_approved) dims=['cohorts', 'caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.035 → **beneficial**
- arav_cancel_2 v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- nort_cancel_2 v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.002 didΔ=+0.035 → **beneficial**
- arav_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.015 didΔ=+0.063 → **beneficial**
- kest_cancel_2 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.002 didΔ=+0.008 → **neutral**
- kest_cancel_2 v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.027 → **beneficial**
- kest_cancel_2 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.010 → **neutral**
- nort_renewal_0 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.021 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.015 didΔ=+0.080 → **beneficial**
- arav_renewal_0 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.021 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.015 didΔ=+0.082 → **beneficial**
- arav_cancel_2 v7 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v5 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.019 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v5 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.451 → **beneficial**
- tide_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.460 → **beneficial**
- nort_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.015 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.071 → **beneficial**
- nort_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.483 → **beneficial**
- kest_renewal_0 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.021 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v8 (controller_auto) dims=['voice'] engageΔ=+0.017 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v6 (controller_auto) dims=['voice'] engageΔ=+0.017 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v9 (controller_auto) dims=['voice'] engageΔ=+0.016 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v7 (controller_auto) dims=['voice'] engageΔ=+0.016 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v10 (controller_auto) dims=['voice'] engageΔ=+0.016 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v8 (controller_auto) dims=['voice'] engageΔ=+0.016 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v11 (controller_auto) dims=['voice'] engageΔ=+0.008 didΔ=+0.000 → **neutral**
- tide_cancel_2 v9 (controller_auto) dims=['voice'] engageΔ=+0.008 didΔ=+0.000 → **neutral**
- kest_cancel_2 v6 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.023 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v7 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.023 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.094 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v8 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v9 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.011 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v5 (controller_approved) dims=['voice'] engageΔ=+0.060 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.111 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.010 didΔ=+0.000 → **neutral**
- kest_kyc_1 v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.015 didΔ=+0.473 → **beneficial**
- tide_renewal_0 v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.090 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v4 (controller_approved) dims=['welcome_message', 'caller_id'] engageΔ=+0.008 didΔ=+0.003 → **neutral**
- arav_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice', 'caller_id'] engageΔ=+0.015 didΔ=+0.003 → **beneficial**
- arav_cancel_2 v12 (controller_auto) dims=['welcome_message'] engageΔ=+0.006 didΔ=+0.000 → **neutral**
- arav_cancel_2 v13 (controller_auto) dims=['welcome_message'] engageΔ=+0.006 didΔ=+0.000 → **neutral**
- arav_cancel_2 v14 (controller_auto) dims=['welcome_message'] engageΔ=+0.006 didΔ=+0.000 → **neutral**
- arav_cancel_2 v15 (controller_auto) dims=['welcome_message'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- tide_kyc_1 v4 (controller_approved) dims=['voice'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- tide_renewal_0 v7 (controller_approved) dims=['voice'] engageΔ=+0.023 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v7 (controller_approved) dims=['voice'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v5 (controller_approved) dims=['welcome_message'] engageΔ=+0.061 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v7 (controller_approved) dims=['voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- arav_kyc_1 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.102 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v5 (controller_approved) dims=['voice'] engageΔ=+0.054 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.128 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v8 (controller_approved) dims=['voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- kest_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.015 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v8 (controller_approved) dims=['voice'] engageΔ=+0.005 didΔ=+0.000 → **neutral**
- nort_kyc_1 v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.052 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v8 (controller_approved) dims=['voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 51,
  "decisions": {
    "approved": 46,
    "rejected": 5,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 5
  },
  "applied_via_approval": 40,
  "auto_applied": 36,
  "auto_apply_rejected": 0,
  "apply_conflicts": 6,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nort_renewal_0": 2,
    "nort_kyc_1": 2,
    "nort_cancel_2": 1,
    "arav_renewal_0": 2,
    "arav_kyc_1": 2,
    "arav_cancel_2": 1,
    "tide_renewal_0": 2,
    "tide_kyc_1": 2,
    "tide_cancel_2": 1,
    "kest_renewal_0": 1,
    "kest_kyc_1": 2,
    "kest_cancel_2": 1
  }
}
```

## Incidents

```
[]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{
  "nort_renewal_0:welcome_message=W3": {
    "3": 0.899,
    "4": 0.898
  },
  "arav_renewal_0:welcome_message=W3": {
    "3": 0.896,
    "4": 0.898
  },
  "tide_renewal_0:welcome_message=W3": {
    "3": 0.901,
    "4": 0.901
  },
  "kest_renewal_0:welcome_message=W3": {
    "4": 0.899
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0