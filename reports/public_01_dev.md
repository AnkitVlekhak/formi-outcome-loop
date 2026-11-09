# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.388 | +13.7% | 0.263 | +7.5% | 0.516 | +4.8% | 20% | 63 (57) |
| nw_kyc | 0.422 | +15.1% | 0.275 | +13.6% | 0.601 | +0.6% | 6% | 28 (21) |
| nw_renewal | 0.444 | +6.6% | 0.280 | +5.9% | 0.541 | -0.1% | -7% | 48 (54) |
| ALL | 0.414 | +11.3% | 0.271 | +8.0% | 0.541 | +2.2% | 7% | 139 (132) |

## Changes applied by the controller

22 applied — neutral: 7, beneficial: 15

- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.011 → **neutral**
- ks_cancel v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.002 didΔ=+0.008 → **neutral**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.021 didΔ=+0.000 → **beneficial**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.041 → **beneficial**
- nw_kyc v2 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.015 didΔ=+0.061 → **beneficial**
- ks_cancel v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.035 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.012 → **neutral**
- nw_renewal v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.024 → **beneficial**
- ks_cancel v5 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.015 didΔ=+0.000 → **beneficial**
- ks_cancel v6 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- ks_cancel v7 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=-0.003 didΔ=+0.000 → **neutral**
- nw_renewal v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.014 didΔ=+0.000 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.112 → **beneficial**
- nw_renewal v7 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.023 didΔ=+0.000 → **beneficial**
- ks_cancel v8 (controller_auto) dims=['welcome_message', 'voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- nw_kyc v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.036 → **beneficial**
- nw_kyc v5 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.064 → **beneficial**
- ks_cancel v9 (controller_auto) dims=['voice'] engageΔ=+0.017 didΔ=+0.000 → **beneficial**
- ks_cancel v10 (controller_auto) dims=['voice'] engageΔ=+0.017 didΔ=+0.000 → **beneficial**
- ks_cancel v11 (controller_auto) dims=['voice'] engageΔ=+0.016 didΔ=+0.000 → **beneficial**
- ks_cancel v12 (controller_auto) dims=['voice'] engageΔ=+0.008 didΔ=+0.000 → **neutral**
- nw_kyc v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.015 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 10,
  "decisions": {
    "approved": 10,
    "expired": 0
  },
  "rejection_reasons": {},
  "applied_via_approval": 9,
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
    "3": 0.189,
    "4": 0.723,
    "5": 0.899,
    "6": 0.905,
    "7": 0.891
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0