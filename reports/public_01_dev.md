# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.383 | +12.1% | 0.259 | +5.7% | 0.518 | +5.4% | 23% | 62 (57) |
| nw_kyc | 0.449 | +22.5% | 0.290 | +19.8% | 0.605 | +1.4% | 7% | 31 (21) |
| nw_renewal | 0.450 | +8.1% | 0.278 | +5.4% | 0.551 | +1.7% | 9% | 44 (54) |
| ALL | 0.419 | +12.8% | 0.271 | +8.2% | 0.548 | +3.4% | 14% | 137 (132) |

## Changes applied by the controller

23 applied — neutral: 10, beneficial: 13

- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.011 → **neutral**
- ks_cancel v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.002 didΔ=+0.008 → **neutral**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.021 didΔ=+0.000 → **beneficial**
- nw_kyc v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.015 didΔ=+0.061 → **beneficial**
- ks_cancel v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.035 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.012 → **neutral**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.045 → **beneficial**
- nw_renewal v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.025 → **beneficial**
- ks_cancel v5 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.012 didΔ=+0.000 → **beneficial**
- ks_cancel v6 (controller_auto) dims=['welcome_message'] engageΔ=+0.010 didΔ=+0.000 → **beneficial**
- nw_renewal v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.015 didΔ=+0.000 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.363 → **beneficial**
- ks_cancel v7 (controller_auto) dims=['voice'] engageΔ=-0.008 didΔ=+0.000 → **neutral**
- nw_renewal v7 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.008 didΔ=+0.000 → **neutral**
- nw_kyc v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.000 → **neutral**
- ks_cancel v8 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.016 didΔ=+0.000 → **beneficial**
- ks_cancel v9 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.016 didΔ=+0.000 → **beneficial**
- ks_cancel v10 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.016 didΔ=+0.000 → **beneficial**
- ks_cancel v11 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.015 didΔ=+0.000 → **beneficial**
- nw_renewal v8 (controller_approved) dims=['welcome_message'] engageΔ=+0.005 didΔ=+0.000 → **neutral**
- ks_cancel v12 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- nw_renewal v9 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v5 (controller_approved) dims=['welcome_message', 'caller_id'] engageΔ=+0.008 didΔ=+0.015 → **neutral**

## Governance

```
{
  "approval_requests": 14,
  "decisions": {
    "approved": 11,
    "rejected": 3,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 3
  },
  "applied_via_approval": 10,
  "auto_applied": 13,
  "auto_apply_rejected": 0,
  "apply_conflicts": 1,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 1,
    "nw_kyc": 2,
    "ks_cancel": 1
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
  "nw_renewal:welcome_message=W3": {
    "3": 0.195,
    "4": 0.068,
    "5": 0.0,
    "6": 0.0,
    "7": 0.0
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0