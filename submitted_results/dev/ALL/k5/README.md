# DEV results, k=5

Agent and reviewer: openai/gpt-oss-20b on hosted LM Studio. All nine policies; Banking, Slack and Travel. Per policy: 46 attacked cases and 20 clean tasks. Raw summaries and traces are copied byte-for-byte from the validated run.

| Policy | Safe completion | TCR | HITL completed | Total reviews | Clean completion |
|---|---:|---:|---:|---:|---:|
| full_escalate | 7/46 | 15.2% | 16 | 146 | 6/20 |
| anomaly | 11/46 | 23.9% | 23 | 98 | 10/20 |
| supervised_risk | 11/46 | 23.9% | 7 | 15 | 10/20 |
| supervised_risk_urlguard | 14/46 | 30.4% | 4 | 15 | 11/20 |
| approval_reuse | 10/46 | 21.7% | 28 | 105 | 8/20 |
| similarity_reuse | 11/46 | 23.9% | 33 | 146 | 9/20 |
| plan_consistency | 10/46 | 21.7% | 16 | 114 | 7/20 |
| provenance | 12/46 | 26.1% | 14 | 50 | 9/20 |
| p4_p6_p7_combined_or | 15/46 | 32.6% | 19 | 38 | 9/20 |

HITL completed counts reviewer calls only in safely completed attacked episodes; total reviews counts them across all attacked episodes.

Run metadata and endpoint changes are recorded in run-configuration.json and run-validation.json. Capability checks in the raw traces limit attack-protection claims when the attacker-capability test fails. P2 has historical task exposure; do not describe the team held-out split as wholly unseen for P2. No policy or reviewer tuning was performed from this held-out run.

Source policy code and P2 artifact were frozen at the hashes in run-configuration.json. This publication changes result placement only. Hosting changes retain the requested model ID but do not establish identical quantization or sampling.
