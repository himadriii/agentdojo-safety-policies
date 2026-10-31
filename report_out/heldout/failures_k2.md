**Failure classification, held-out, k=2**

| policy | tasks | failures | over-permissive | over-conservative | of which: budget exhausted | auto-deny | reviewer denied | other (not policy) | unsafe calls executed | of which no final-state effect | unsafe calls blocked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| full_approve | 98 | 70 | 37 | 0 | 0 | 0 | 0 | 33 | 73 | 29 | 0 |
| full_escalate | 98 | 66 | 0 | 38 | 29 | 0 | 9 | 28 | 1 | 1 | 44 |
| anomaly | 98 | 65 | 0 | 40 | 32 | 0 | 8 | 25 | 1 | 1 | 47 |
| approval_reuse | 98 | 60 | 0 | 25 | 13 | 0 | 12 | 35 | 3 | 3 | 48 |
| p4_p6_p7_combined_or | 98 | 40 | 1 | 17 | 1 | 6 | 10 | 22 | 6 | 5 | 51 |
| plan_consistency | 98 | 63 | 1 | 35 | 20 | 5 | 10 | 27 | 5 | 4 | 43 |
| provenance | 98 | 41 | 0 | 18 | 2 | 5 | 11 | 23 | 5 | 5 | 52 |
| similarity_reuse | 98 | 64 | 0 | 38 | 28 | 0 | 10 | 26 | 1 | 1 | 46 |
| supervised_risk | 98 | 55 | 6 | 1 | 0 | 1 | 0 | 48 | 21 | 15 | 49 |
| supervised_risk_urlguard | 98 | 54 | 6 | 3 | 0 | 3 | 0 | 45 | 21 | 15 | 47 |
