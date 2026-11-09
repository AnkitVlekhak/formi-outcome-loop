# Robustness eval — hidden-like variants

Each variant re-draws the hidden truth (effects, decays, incidents, caller-ID health, approver noise). Graded against its own no-op baseline with the official grader.

| scenario | conclusion Δ | applied | harmful | beneficial | requests | rejected | expired | lapsed | prompt MTTR (min) | flagged DID share next day | decaying-variant share, last day | credits | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| variant_001 | +20.9% | 25 | 1 | 11 | 15 | 2 | 0 | 0 | [1440] | [0.0] | {} | 3 | 8.2 |
| variant_002 | +18.3% | 20 | 0 | 12 | 14 | 4 | 0 | 0 | [7080] | [0.0] | {} | 13 | 7.5 |
| variant_003 | +16.9% | 23 | 2 | 13 | 12 | 1 | 0 | 0 | [None] | [0.881] | {} | 0 | 7.6 |
| variant_004 | +12.0% | 23 | 2 | 12 | 12 | 0 | 0 | 0 | [None] | [0.0] | {'nw_kyc:voice=V2': 0.071, 'nw_kyc:welcome_message=W2': 0.103} | 0 | 7.6 |
| variant_005 | +18.9% | 20 | 2 | 8 | 8 | 0 | 0 | 0 | [1260] | [0.0] | {'nw_renewal:welcome_message=W2': 0.0} | 3 | 9.0 |
| variant_006 | +21.4% | 22 | 0 | 15 | 11 | 1 | 0 | 0 | [None] | [0.0] | {'nw_renewal:voice=V4': 0.0} | 0 | 9.1 |

**Mean conclusion Δ +18.0%** · harmful changes 7 of 133 applied · lapsed 0 · expired 0

Per-workflow pickup / engagement deltas (guardrail check):

- variant_001: ks_cancel pickup +7.9% eng +5.4%, nw_kyc pickup +10.7% eng +0.7%, nw_renewal pickup +30.6% eng +0.2%
- variant_002: ks_cancel pickup +6.1% eng -0.4%, nw_kyc pickup +15.9% eng +4.1%, nw_renewal pickup +28.8% eng +0.9%
- variant_003: ks_cancel pickup +4.8% eng +5.4%, nw_kyc pickup +72.0% eng +2.1%, nw_renewal pickup +6.4% eng +1.5%
- variant_004: ks_cancel pickup +8.4% eng +1.6%, nw_kyc pickup +9.5% eng -1.6%, nw_renewal pickup +9.6% eng +2.6%
- variant_005: ks_cancel pickup +28.8% eng -0.4%, nw_kyc pickup +18.8% eng -3.2%, nw_renewal pickup +9.1% eng -0.7%
- variant_006: ks_cancel pickup +6.4% eng +4.1%, nw_kyc pickup +19.3% eng -1.5%, nw_renewal pickup +23.7% eng +7.1%
