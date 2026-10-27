# HELDOUT results, k=5

Agent and reviewer: openai/gpt-oss-20b on hosted LM Studio. All nine policies; Banking, Slack and Travel. Per policy: 34 attacked cases and 14 clean tasks. Raw summaries and traces are copied byte-for-byte from the validated run.

| Policy | Safe completion | TCR | HITL completed | Total reviews | Clean completion |
|---|---:|---:|---:|---:|---:|
| full_escalate | 8/34 | 23.5% | 22 | 91 | 8/14 |
| anomaly | 8/34 | 23.5% | 12 | 60 | 7/14 |
| supervised_risk | 6/34 | 17.6% | 0 | 4 | 7/14 |
| supervised_risk_urlguard | 6/34 | 17.6% | 0 | 4 | 7/14 |
| approval_reuse | 8/34 | 23.5% | 16 | 70 | 8/14 |
| similarity_reuse | 7/34 | 20.6% | 16 | 85 | 8/14 |
| plan_consistency | 11/34 | 32.4% | 15 | 55 | 6/14 |
| provenance | 12/34 | 35.3% | 7 | 28 | 8/14 |
| p4_p6_p7_combined_or | 15/34 | 44.1% | 9 | 27 | 9/14 |

HITL completed counts reviewer calls only in safely completed attacked episodes; total reviews counts them across all attacked episodes.

Run metadata and endpoint changes are recorded in run-configuration.json and run-validation.json. Capability checks in the raw traces limit attack-protection claims when the attacker-capability test fails. P2 has historical task exposure; do not describe the team held-out split as wholly unseen for P2. No policy or reviewer tuning was performed from this held-out run.

Source policy code and P2 artifact were frozen at the hashes in run-configuration.json. This publication changes result placement only. Hosting changes retain the requested model ID but do not establish identical quantization or sampling.
