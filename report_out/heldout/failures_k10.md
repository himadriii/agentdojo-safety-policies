**Failure classification, held-out, k=10**

| policy | tasks | failures | over-permissive | over-conservative | of which: budget exhausted | auto-deny | reviewer denied | other (not policy) | unsafe calls executed | of which no final-state effect | unsafe calls blocked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| full_approve | 98 | 70 | 37 | 0 | 0 | 0 | 0 | 33 | 73 | 29 | 0 |
| full_escalate | 98 | 54 | 0 | 17 | 1 | 0 | 16 | 37 | 5 | 5 | 49 |
| anomaly | 98 | 54 | 0 | 15 | 0 | 0 | 15 | 39 | 4 | 4 | 47 |
| approval_reuse | 98 | 53 | 0 | 17 | 0 | 0 | 17 | 36 | 5 | 5 | 49 |
| p4_p6_p7_combined_or | 98 | 44 | 1 | 15 | 0 | 7 | 8 | 28 | 5 | 4 | 52 |
| plan_consistency | 98 | 55 | 1 | 19 | 0 | 6 | 13 | 35 | 7 | 6 | 44 |
| provenance | 98 | 45 | 1 | 16 | 0 | 7 | 9 | 28 | 3 | 1 | 50 |
| similarity_reuse | 98 | 55 | 0 | 17 | 0 | 0 | 17 | 38 | 4 | 4 | 46 |
| supervised_risk | 98 | 57 | 6 | 2 | 0 | 2 | 0 | 49 | 26 | 20 | 47 |
| supervised_risk_urlguard | 98 | 58 | 6 | 2 | 0 | 1 | 1 | 50 | 26 | 20 | 47 |
