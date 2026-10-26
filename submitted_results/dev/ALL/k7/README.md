# DEV results, k=7

Agent and reviewer: openai/gpt-oss-20b on hosted LM Studio. All nine policies; Banking, Slack and Travel. Per policy: 46 attacked cases and 20 clean tasks. Raw summaries and traces are copied byte-for-byte from the validated run.

| Policy | Safe completion | TCR | HITL completed | Total reviews | Clean completion |
|---|---:|---:|---:|---:|---:|
| full_escalate | 13/46 | 28.3% | 48 | 155 | 8/20 |
| anomaly | 10/46 | 21.7% | 25 | 105 | 12/20 |
| supervised_risk | 10/46 | 21.7% | 7 | 15 | 10/20 |
| supervised_risk_urlguard | 12/46 | 26.1% | 5 | 14 | 9/20 |
| approval_reuse | 10/46 | 21.7% | 30 | 115 | 8/20 |
| similarity_reuse | 10/46 | 21.7% | 33 | 154 | 11/20 |
| plan_consistency | 8/46 | 17.4% | 10 | 123 | 7/20 |
| provenance | 16/46 | 34.8% | 21 | 45 | 8/20 |
| p4_p6_p7_combined_or | 16/46 | 34.8% | 24 | 44 | 8/20 |

HITL completed counts reviewer calls only in safely completed attacked episodes; total reviews counts them across all attacked episodes.

Run metadata and endpoint changes are recorded in run-configuration.json and run-validation.json. Capability checks in the raw traces limit attack-protection claims when the attacker-capability test fails. P2 has historical task exposure; do not describe the team held-out split as wholly unseen for P2. No policy or reviewer tuning was performed from this held-out run.

Source policy code and P2 artifact were frozen at the hashes in run-configuration.json. This publication changes result placement only. Hosting changes retain the requested model ID but do not establish identical quantization or sampling.
