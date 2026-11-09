# Robustness eval — hidden-like variants

Each variant re-draws the hidden truth (effects, decays, incidents, caller-ID health, approver noise). Graded against its own no-op baseline with the official grader.

| scenario | conclusion Δ | applied | harmful | beneficial | requests | rejected | expired | lapsed | prompt MTTR (min) | flagged DID share next day | decaying-variant share, last day | credits | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| variant_001 | +24.1% | 25 | 0 | 13 | 14 | 1 | 1 | 0 | [1485] | [0.0] | {} | 3 | 7.5 |
| variant_002 | +20.3% | 17 | 0 | 12 | 13 | 3 | 0 | 0 | [1305] | [0.0] | {} | 13 | 7.3 |
| variant_003 | +24.3% | 21 | 1 | 9 | 11 | 1 | 0 | 0 | [2805] | [0.577] | {} | 3 | 7.6 |
| variant_004 | +13.5% | 20 | 0 | 11 | 13 | 1 | 0 | 0 | [1530] | [0.0] | {'nw_kyc:voice=V2': 0.11, 'nw_kyc:welcome_message=W2': 0.098} | 3 | 7.6 |
| variant_005 | +18.9% | 25 | 1 | 8 | 13 | 1 | 1 | 0 | [1275] | [0.0] | {'nw_renewal:welcome_message=W2': 0.0} | 3 | 9.1 |
| variant_006 | +22.0% | 20 | 0 | 15 | 11 | 1 | 0 | 0 | [2805] | [0.0] | {'nw_renewal:voice=V4': 0.0} | 13 | 9.0 |

**Mean conclusion Δ +20.5%** · harmful changes 2 of 128 applied · lapsed 0 · expired 2

Per-workflow pickup / engagement deltas (guardrail check):

- variant_001: ks_cancel pickup +7.3% eng +6.8%, nw_kyc pickup +14.2% eng -1.0%, nw_renewal pickup +35.4% eng +1.0%
- variant_002: ks_cancel pickup +4.6% eng +4.7%, nw_kyc pickup +12.7% eng +4.2%, nw_renewal pickup +30.7% eng +1.3%
- variant_003: ks_cancel pickup +7.3% eng +1.9%, nw_kyc pickup +132.1% eng +3.7%, nw_renewal pickup +8.0% eng +1.9%
- variant_004: ks_cancel pickup +8.6% eng +1.3%, nw_kyc pickup +8.2% eng +6.9%, nw_renewal pickup +11.7% eng +0.2%
- variant_005: ks_cancel pickup +29.7% eng -0.3%, nw_kyc pickup +14.8% eng -2.8%, nw_renewal pickup +10.3% eng -0.4%
- variant_006: ks_cancel pickup +6.1% eng +3.3%, nw_kyc pickup +17.6% eng +2.4%, nw_renewal pickup +25.7% eng +6.8%
