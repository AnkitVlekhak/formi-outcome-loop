# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.360 | +53.0% | 0.249 | +37.5% | 0.494 | +5.6% | 35% | 76 (348) |
| nw_kyc | 0.453 | +21.3% | 0.282 | +20.1% | 0.605 | -0.5% | -4% | 38 (29) |
| nw_renewal | 0.483 | +11.5% | 0.290 | +10.6% | 0.554 | -0.1% | 13% | 53 (54) |
| ALL | 0.421 | +27.3% | 0.270 | +22.8% | 0.539 | +1.1% | 24% | 167 (431) |

## Changes applied by the controller

25 applied — beneficial: 11, neutral: 14

- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.020 → **beneficial**
- ks_cancel v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.008 didΔ=+0.009 → **neutral**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.010 didΔ=+0.000 → **beneficial**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.038 → **beneficial**
- nw_renewal v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.019 → **neutral**
- ks_cancel v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.035 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.012 → **neutral**
- nw_kyc v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=-0.004 didΔ=+0.045 → **beneficial**
- nw_renewal v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.015 → **neutral**
- ks_cancel v5 (controller_auto) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.170 → **beneficial**
- ks_cancel v7 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.097 → **beneficial**
- ks_cancel v8 (controller_auto) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v7 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.015 didΔ=+0.000 → **beneficial**
- ks_cancel v10 (controller_approved) dims=['prompt_version'] engageΔ=+0.102 didΔ=+0.000 → **beneficial**
- ks_cancel v11 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.002 didΔ=+0.000 → **neutral**
- nw_renewal v8 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.023 didΔ=+0.000 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.240 → **beneficial**
- ks_cancel v12 (controller_auto) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v9 (controller_approved) dims=['welcome_message'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v11 (controller_approved) dims=['welcome_message'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v5 (controller_approved) dims=['voice', 'caller_id'] engageΔ=+0.004 didΔ=+0.010 → **neutral**
- ks_cancel v13 (controller_auto) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.008 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 14,
  "decisions": {
    "approved": 13,
    "rejected": 1,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 12,
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
[
  {
    "type": "did_flagged",
    "workflow": "ks_cancel",
    "at": "D2 10:00",
    "flagged_did_share_by_day": {
      "2": 0.083,
      "3": 0.0,
      "4": 0.0,
      "5": 0.0,
      "6": 0.0,
      "7": 0.0,
      "8": 0.0,
      "9": 0.0
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": 135,
    "fixed_by": "controller_approved"
  },
  {
    "type": "supervisor_edit",
    "workflow": "nw_renewal",
    "at": "D5 15:00"
  }
]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{
  "nw_renewal:welcome_message=W3": {
    "2": 0.098,
    "3": 0.17,
    "4": 0.066,
    "5": 0.0,
    "6": 0.0,
    "7": 0.0,
    "8": 0.0,
    "9": 0.0
  }
}
```

Credits used: 3 · validation runs: 1 · LLM fix calls: 0