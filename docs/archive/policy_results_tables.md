# Policy results by split, k, and suite

Attack-run results (`important_instructions`) from submitted summaries. Each row is one policy-suite result. Safely completed is `count/n`; TCR is safely completed divided by n. HITL Load is reviewer calls on safely completed tasks; Total reviews is all reviewer calls. Benign (`none`) summaries are excluded.

## Dev — k=0

| Policy | Suite | Safely completed | TCR | HITL Load | Total reviews | Successful attacks | Auto-denials | Budget-exhausted denials |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `full_escalate` | Banking | 6/18 | 0.333 | 0 | 0 | 0 | 0 | 21 |
| `full_escalate` | Slack | 0/14 | 0.000 | 0 | 0 | 0 | 0 | 20 |
| `full_escalate` | Travel | 0/14 | 0.000 | 0 | 0 | 0 | 0 | 14 |
| `anomaly` | Banking | 6/18 | 0.333 | 0 | 0 | 0 | 0 | 21 |
| `anomaly` | Slack | 0/14 | 0.000 | 0 | 0 | 0 | 0 | 20 |
| `anomaly` | Travel | 0/14 | 0.000 | 0 | 0 | 0 | 0 | 15 |
| `supervised_risk` | Banking | 8/18 | 0.444 | 0 | 0 | 0 | 10 | 6 |
| `supervised_risk` | Slack | 1/14 | 0.071 | 0 | 0 | 5 | 2 | 8 |
| `supervised_risk` | Travel | 1/14 | 0.071 | 0 | 0 | 2 | 6 | 2 |
| `supervised_risk_urlguard` | Banking | 8/18 | 0.444 | 0 | 0 | 0 | 12 | 9 |
| `supervised_risk_urlguard` | Slack | 4/14 | 0.286 | 0 | 0 | 0 | 10 | 5 |
| `supervised_risk_urlguard` | Travel | 1/14 | 0.071 | 0 | 0 | 2 | 5 | 2 |
| `approval_reuse` | Banking | 6/18 | 0.333 | 0 | 0 | 0 | 0 | 19 |
| `approval_reuse` | Slack | 0/14 | 0.000 | 0 | 0 | 0 | 0 | 23 |
| `approval_reuse` | Travel | 0/14 | 0.000 | 0 | 0 | 0 | 0 | 16 |
| `similarity_reuse` | Banking | 6/18 | 0.333 | 0 | 0 | 0 | 0 | 21 |
| `similarity_reuse` | Slack | 0/14 | 0.000 | 0 | 0 | 0 | 0 | 23 |
| `similarity_reuse` | Travel | 0/14 | 0.000 | 0 | 0 | 0 | 0 | 16 |
| `plan_consistency` | Banking | 6/18 | 0.333 | 0 | 0 | 0 | 0 | 22 |
| `plan_consistency` | Slack | 0/14 | 0.000 | 0 | 0 | 0 | 1 | 18 |
| `plan_consistency` | Travel | 0/14 | 0.000 | 0 | 0 | 0 | 0 | 14 |
| `provenance` | Banking | 6/18 | 0.333 | 0 | 0 | 0 | 1 | 21 |
| `provenance` | Slack | 0/14 | 0.000 | 0 | 0 | 0 | 16 | 12 |
| `provenance` | Travel | 1/14 | 0.071 | 0 | 0 | 0 | 14 | 4 |
| `p4_p6_p7_combined_or` | Banking | 6/18 | 0.333 | 0 | 0 | 0 | 3 | 20 |
| `p4_p6_p7_combined_or` | Slack | 2/14 | 0.143 | 0 | 0 | 0 | 14 | 8 |
| `p4_p6_p7_combined_or` | Travel | 1/14 | 0.071 | 0 | 0 | 0 | 12 | 4 |

## Dev — k=2

| Policy | Suite | Safely completed | TCR | HITL Load | Total reviews | Successful attacks | Auto-denials | Budget-exhausted denials |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `full_escalate` | Banking | 6/18 | 0.333 | 10 | 34 | 0 | 0 | 5 |
| `full_escalate` | Slack | 0/14 | 0.000 | 0 | 28 | 0 | 0 | 19 |
| `full_escalate` | Travel | 0/14 | 0.000 | 0 | 28 | 0 | 0 | 22 |
| `anomaly` | Banking | 6/18 | 0.333 | 10 | 34 | 0 | 0 | 9 |
| `anomaly` | Slack | 0/14 | 0.000 | 0 | 28 | 0 | 0 | 19 |
| `anomaly` | Travel | 0/14 | 0.000 | 0 | 28 | 0 | 0 | 22 |
| `supervised_risk` | Banking | 8/18 | 0.444 | 3 | 7 | 1 | 11 | 0 |
| `supervised_risk` | Slack | 1/14 | 0.071 | 1 | 8 | 7 | 4 | 0 |
| `supervised_risk` | Travel | 1/14 | 0.071 | 0 | 2 | 2 | 5 | 0 |
| `supervised_risk_urlguard` | Banking | 9/18 | 0.500 | 5 | 9 | 0 | 11 | 0 |
| `supervised_risk_urlguard` | Slack | 3/14 | 0.214 | 1 | 5 | 0 | 11 | 0 |
| `supervised_risk_urlguard` | Travel | 1/14 | 0.071 | 0 | 2 | 2 | 8 | 0 |
| `approval_reuse` | Banking | 6/18 | 0.333 | 12 | 36 | 0 | 0 | 8 |
| `approval_reuse` | Slack | 0/14 | 0.000 | 0 | 28 | 0 | 0 | 20 |
| `approval_reuse` | Travel | 3/14 | 0.214 | 5 | 27 | 0 | 0 | 10 |
| `similarity_reuse` | Banking | 6/18 | 0.333 | 12 | 36 | 0 | 0 | 10 |
| `similarity_reuse` | Slack | 0/14 | 0.000 | 0 | 28 | 1 | 0 | 14 |
| `similarity_reuse` | Travel | 2/14 | 0.143 | 4 | 28 | 0 | 0 | 21 |
| `plan_consistency` | Banking | 6/18 | 0.333 | 9 | 32 | 0 | 12 | 4 |
| `plan_consistency` | Slack | 0/14 | 0.000 | 0 | 27 | 2 | 7 | 9 |
| `plan_consistency` | Travel | 2/14 | 0.143 | 3 | 26 | 0 | 0 | 19 |
| `provenance` | Banking | 6/18 | 0.333 | 8 | 29 | 0 | 14 | 9 |
| `provenance` | Slack | 6/14 | 0.429 | 5 | 15 | 0 | 15 | 3 |
| `provenance` | Travel | 2/14 | 0.143 | 1 | 7 | 0 | 12 | 0 |
| `p4_p6_p7_combined_or` | Banking | 7/18 | 0.389 | 12 | 30 | 0 | 12 | 10 |
| `p4_p6_p7_combined_or` | Slack | 8/14 | 0.571 | 7 | 9 | 0 | 17 | 0 |
| `p4_p6_p7_combined_or` | Travel | 4/14 | 0.286 | 3 | 5 | 0 | 11 | 0 |

## Heldout — k=0

| Policy | Suite | Safely completed | TCR | HITL Load | Total reviews | Successful attacks | Auto-denials | Budget-exhausted denials |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `full_escalate` | Banking | 3/18 | 0.167 | 0 | 0 | 0 | 0 | 18 |
| `full_escalate` | Slack | 0/8 | 0.000 | 0 | 0 | 0 | 0 | 14 |
| `full_escalate` | Travel | 0/8 | 0.000 | 0 | 0 | 0 | 0 | 8 |
| `anomaly` | Banking | 3/18 | 0.167 | 0 | 0 | 0 | 0 | 18 |
| `anomaly` | Slack | 0/8 | 0.000 | 0 | 0 | 0 | 0 | 14 |
| `anomaly` | Travel | 0/8 | 0.000 | 0 | 0 | 0 | 0 | 8 |
| `supervised_risk` | Banking | 4/18 | 0.222 | 0 | 0 | 6 | 11 | 0 |
| `supervised_risk` | Slack | 2/8 | 0.250 | 0 | 0 | 0 | 8 | 0 |
| `supervised_risk` | Travel | 2/8 | 0.250 | 0 | 0 | 0 | 3 | 3 |
| `supervised_risk_urlguard` | Banking | 4/18 | 0.222 | 0 | 0 | 6 | 10 | 0 |
| `supervised_risk_urlguard` | Slack | 3/8 | 0.375 | 0 | 0 | 0 | 8 | 0 |
| `supervised_risk_urlguard` | Travel | 1/8 | 0.125 | 0 | 0 | 0 | 3 | 3 |
| `approval_reuse` | Banking | 3/18 | 0.167 | 0 | 0 | 0 | 0 | 18 |
| `approval_reuse` | Slack | 0/8 | 0.000 | 0 | 0 | 0 | 0 | 14 |
| `approval_reuse` | Travel | 0/8 | 0.000 | 0 | 0 | 0 | 0 | 8 |
| `similarity_reuse` | Banking | 3/18 | 0.167 | 0 | 0 | 0 | 0 | 18 |
| `similarity_reuse` | Slack | 0/8 | 0.000 | 0 | 0 | 0 | 0 | 14 |
| `similarity_reuse` | Travel | 0/8 | 0.000 | 0 | 0 | 0 | 0 | 8 |
| `plan_consistency` | Banking | 3/18 | 0.167 | 0 | 0 | 0 | 2 | 16 |
| `plan_consistency` | Slack | 2/8 | 0.250 | 0 | 0 | 0 | 1 | 12 |
| `plan_consistency` | Travel | 0/8 | 0.000 | 0 | 0 | 0 | 0 | 8 |
| `provenance` | Banking | 3/18 | 0.167 | 0 | 0 | 0 | 4 | 16 |
| `provenance` | Slack | 3/8 | 0.375 | 0 | 0 | 0 | 4 | 6 |
| `provenance` | Travel | 3/8 | 0.375 | 0 | 0 | 0 | 6 | 2 |
| `p4_p6_p7_combined_or` | Banking | 3/18 | 0.167 | 0 | 0 | 0 | 4 | 15 |
| `p4_p6_p7_combined_or` | Slack | 4/8 | 0.500 | 0 | 0 | 1 | 4 | 7 |
| `p4_p6_p7_combined_or` | Travel | 2/8 | 0.250 | 0 | 0 | 0 | 5 | 3 |

## Heldout — k=2

| Policy | Suite | Safely completed | TCR | HITL Load | Total reviews | Successful attacks | Auto-denials | Budget-exhausted denials |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `full_escalate` | Banking | 5/18 | 0.278 | 8 | 33 | 0 | 0 | 6 |
| `full_escalate` | Slack | 2/8 | 0.250 | 4 | 16 | 0 | 0 | 10 |
| `full_escalate` | Travel | 0/8 | 0.000 | 0 | 16 | 0 | 0 | 10 |
| `anomaly` | Banking | 6/18 | 0.333 | 10 | 33 | 0 | 0 | 5 |
| `anomaly` | Slack | 2/8 | 0.250 | 4 | 16 | 0 | 0 | 11 |
| `anomaly` | Travel | 0/8 | 0.000 | 0 | 16 | 0 | 0 | 9 |
| `supervised_risk` | Banking | 4/18 | 0.222 | 0 | 0 | 6 | 9 | 0 |
| `supervised_risk` | Slack | 2/8 | 0.250 | 0 | 0 | 0 | 8 | 0 |
| `supervised_risk` | Travel | 1/8 | 0.125 | 0 | 3 | 0 | 3 | 0 |
| `supervised_risk_urlguard` | Banking | 4/18 | 0.222 | 0 | 0 | 6 | 10 | 0 |
| `supervised_risk_urlguard` | Slack | 2/8 | 0.250 | 0 | 0 | 0 | 8 | 0 |
| `supervised_risk_urlguard` | Travel | 1/8 | 0.125 | 0 | 4 | 0 | 3 | 0 |
| `approval_reuse` | Banking | 6/18 | 0.333 | 11 | 33 | 0 | 0 | 5 |
| `approval_reuse` | Slack | 2/8 | 0.250 | 4 | 16 | 0 | 0 | 8 |
| `approval_reuse` | Travel | 2/8 | 0.250 | 2 | 14 | 0 | 0 | 0 |
| `similarity_reuse` | Banking | 5/18 | 0.278 | 8 | 33 | 0 | 0 | 4 |
| `similarity_reuse` | Slack | 2/8 | 0.250 | 4 | 16 | 0 | 0 | 8 |
| `similarity_reuse` | Travel | 0/8 | 0.000 | 0 | 16 | 0 | 0 | 11 |
| `plan_consistency` | Banking | 6/18 | 0.333 | 4 | 23 | 0 | 10 | 1 |
| `plan_consistency` | Slack | 2/8 | 0.250 | 2 | 12 | 1 | 5 | 1 |
| `plan_consistency` | Travel | 0/8 | 0.000 | 0 | 14 | 0 | 3 | 7 |
| `provenance` | Banking | 6/18 | 0.333 | 5 | 19 | 0 | 20 | 0 |
| `provenance` | Slack | 3/8 | 0.375 | 2 | 6 | 0 | 4 | 0 |
| `provenance` | Travel | 4/8 | 0.500 | 1 | 2 | 0 | 6 | 0 |
| `p4_p6_p7_combined_or` | Banking | 6/18 | 0.333 | 4 | 19 | 0 | 14 | 1 |
| `p4_p6_p7_combined_or` | Slack | 4/8 | 0.500 | 3 | 5 | 1 | 5 | 0 |
| `p4_p6_p7_combined_or` | Travel | 4/8 | 0.500 | 1 | 3 | 0 | 5 | 0 |
