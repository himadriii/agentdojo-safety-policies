# Shared DEV results: k=5 and k=7

Nine policies; Banking, Slack and Travel; agent and reviewer openai/gpt-oss-20b on hosted LM Studio. Each policy/budget has 46 attacked cases and 20 clean cases. Full traces and per-suite summary JSON files are included.

HITL completed counts reviewer calls in safely completed attacked episodes; total reviews includes all attacked episodes. TCR counts safe task completion. Clean completion is reported separately.

| Policy | k | Safe attacked / 46 | TCR | HITL completed | Total reviews | Clean TCR |
|---|---:|---:|---:|---:|---:|---:|
| full_escalate | 5 | 7/46 | 15.2% | 16 | 146 | 6/20 (30.0%) |
| full_escalate | 7 | 13/46 | 28.3% | 48 | 155 | 8/20 (40.0%) |
| anomaly | 5 | 11/46 | 23.9% | 23 | 98 | 10/20 (50.0%) |
| anomaly | 7 | 10/46 | 21.7% | 25 | 105 | 12/20 (60.0%) |
| supervised_risk | 5 | 11/46 | 23.9% | 7 | 15 | 10/20 (50.0%) |
| supervised_risk | 7 | 10/46 | 21.7% | 7 | 15 | 10/20 (50.0%) |
| supervised_risk_urlguard | 5 | 14/46 | 30.4% | 4 | 15 | 11/20 (55.0%) |
| supervised_risk_urlguard | 7 | 12/46 | 26.1% | 5 | 14 | 9/20 (45.0%) |
| approval_reuse | 5 | 10/46 | 21.7% | 28 | 105 | 8/20 (40.0%) |
| approval_reuse | 7 | 10/46 | 21.7% | 30 | 115 | 8/20 (40.0%) |
| similarity_reuse | 5 | 11/46 | 23.9% | 33 | 146 | 9/20 (45.0%) |
| similarity_reuse | 7 | 10/46 | 21.7% | 33 | 154 | 11/20 (55.0%) |
| plan_consistency | 5 | 10/46 | 21.7% | 16 | 114 | 7/20 (35.0%) |
| plan_consistency | 7 | 8/46 | 17.4% | 10 | 123 | 7/20 (35.0%) |
| provenance | 5 | 12/46 | 26.1% | 14 | 50 | 9/20 (45.0%) |
| provenance | 7 | 16/46 | 34.8% | 21 | 45 | 8/20 (40.0%) |
| p4_p6_p7_combined_or | 5 | 15/46 | 32.6% | 19 | 38 | 9/20 (45.0%) |
| p4_p6_p7_combined_or | 7 | 16/46 | 34.8% | 24 | 44 | 8/20 (40.0%) |

Frozen source and P2 artifact details are in run-configuration.json. The endpoint changed after an access failure; completed cases were retained, and the endpoint history is recorded in validation.json. Hosting, quantization and sampling are not guaranteed identical across endpoint hosts.

DEV results support development comparisons, not an unbiased final estimate. Capability checks are included in the raw traces and must be considered when interpreting attack resistance. Held-out results will be published separately after validation.
