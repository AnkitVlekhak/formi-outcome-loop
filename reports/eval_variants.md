# Robustness eval — hidden-like variants

Each variant re-draws the hidden truth (effects, decays, incidents, caller-ID health, approver noise). Graded against its own no-op baseline with the official grader.

| scenario | conclusion Δ | applied | harmful | beneficial | requests | rejected | expired | lapsed | prompt MTTR (min) | flagged DID share next day | decaying-variant share, last day | credits | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| variant_001 | +24.4% | 24 | 0 | 12 | 13 | 1 | 0 | 0 | [1455] | [0.0] | {} | 3 | 7.5 |
| variant_002 | +20.1% | 18 | 0 | 11 | 13 | 3 | 0 | 0 | [1290] | [0.0] | {} | 13 | 7.3 |
| variant_003 | +24.4% | 23 | 1 | 12 | 12 | 1 | 0 | 0 | [405] | [0.564] | {} | 3 | 7.5 |
| variant_004 | +11.0% | 20 | 2 | 9 | 12 | 2 | 0 | 0 | [None] | [0.0] | {'nw_kyc:voice=V2': 0.108, 'nw_kyc:welcome_message=W2': 0.102} | 3 | 7.5 |
| variant_005 | +18.4% | 26 | 1 | 9 | 13 | 2 | 0 | 0 | [1485] | [0.0] | {'nw_renewal:welcome_message=W2': 0.0} | 3 | 9.2 |
| variant_006 | +20.7% | 23 | 0 | 15 | 13 | 2 | 0 | 0 | [4245] | [0.0] | {'nw_renewal:voice=V4': 0.0} | 13 | 9.2 |

**Mean conclusion Δ +19.8%** · harmful changes 4 of 134 applied · lapsed 0 · expired 0

Per-workflow pickup / engagement deltas (guardrail check):

- variant_001: ks_cancel pickup +7.1% eng +6.9%, nw_kyc pickup +14.2% eng -1.0%, nw_renewal pickup +35.8% eng +1.5%
- variant_002: ks_cancel pickup +5.5% eng +4.6%, nw_kyc pickup +13.2% eng +2.9%, nw_renewal pickup +31.4% eng +0.1%
- variant_003: ks_cancel pickup +7.5% eng +3.5%, nw_kyc pickup +132.1% eng +2.4%, nw_renewal pickup +7.7% eng +1.1%
- variant_004: ks_cancel pickup +7.5% eng +1.4%, nw_kyc pickup +8.6% eng -2.3%, nw_renewal pickup +11.6% eng +0.6%
- variant_005: ks_cancel pickup +29.8% eng -1.4%, nw_kyc pickup +16.3% eng -2.0%, nw_renewal pickup +9.6% eng -0.9%
- variant_006: ks_cancel pickup +5.7% eng +2.6%, nw_kyc pickup +16.4% eng +1.7%, nw_renewal pickup +24.6% eng +7.2%
