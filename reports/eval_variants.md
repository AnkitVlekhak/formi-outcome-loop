# Robustness eval — hidden-like variants

Each variant re-draws the hidden truth (effects, decays, incidents, caller-ID health, approver noise). Graded against its own no-op baseline with the official grader.

| scenario | conclusion Δ | applied | harmful | beneficial | requests | rejected | expired | lapsed | prompt MTTR (min) | flagged DID share next day | decaying-variant share, last day | credits | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| variant_001 | +25.2% | 24 | 0 | 12 | 12 | 1 | 1 | 0 | [1410] | [0.0] | {} | 3 | 7.4 |
| variant_002 | +20.1% | 18 | 0 | 11 | 13 | 3 | 0 | 0 | [1290] | [0.0] | {} | 13 | 7.3 |
| variant_003 | +24.4% | 23 | 1 | 12 | 12 | 1 | 0 | 0 | [345] | [0.564] | {} | 3 | 7.5 |
| variant_004 | +13.9% | 23 | 1 | 11 | 13 | 1 | 0 | 0 | [1650] | [0.0] | {'nw_kyc:voice=V2': 0.062, 'nw_kyc:welcome_message=W2': 0.14} | 3 | 7.6 |
| variant_005 | +19.3% | 24 | 1 | 9 | 12 | 1 | 0 | 0 | [225] | [0.0] | {'nw_renewal:welcome_message=W2': 0.0} | 3 | 9.1 |
| variant_006 | +22.0% | 20 | 0 | 15 | 11 | 1 | 0 | 0 | [2805] | [0.0] | {'nw_renewal:voice=V4': 0.0} | 13 | 9.0 |

**Mean conclusion Δ +20.8%** · harmful changes 3 of 132 applied · lapsed 0 · expired 1

Per-workflow pickup / engagement deltas (guardrail check):

- variant_001: ks_cancel pickup +6.7% eng +8.3%, nw_kyc pickup +15.7% eng -2.6%, nw_renewal pickup +36.8% eng +1.7%
- variant_002: ks_cancel pickup +5.5% eng +4.6%, nw_kyc pickup +13.2% eng +2.9%, nw_renewal pickup +31.4% eng +0.1%
- variant_003: ks_cancel pickup +7.5% eng +3.5%, nw_kyc pickup +132.1% eng +2.4%, nw_renewal pickup +7.7% eng +1.1%
- variant_004: ks_cancel pickup +7.6% eng +0.9%, nw_kyc pickup +10.5% eng +5.9%, nw_renewal pickup +12.7% eng +0.8%
- variant_005: ks_cancel pickup +31.5% eng +0.4%, nw_kyc pickup +15.6% eng -1.8%, nw_renewal pickup +8.0% eng -0.8%
- variant_006: ks_cancel pickup +6.1% eng +3.3%, nw_kyc pickup +17.6% eng +2.4%, nw_renewal pickup +25.7% eng +6.8%
