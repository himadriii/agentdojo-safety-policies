**API cost by component, held-out, k=10** (input + output tokens; 98 tasks per policy)

| policy | agent tokens | policy tokens | reviewer tokens | added (policy + reviewer) | added / task | added vs agent | policy calls | reviewer calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| full_approve | 945,632 | 0 | 0 | 0 | 0 | 0% | 0 | 0 |
| full_escalate | 825,730 | 0 | 220,566 | 220,566 | 2,251 | 27% | 0 | 264 |
| anomaly | 801,224 | 0 | 207,841 | 207,841 | 2,121 | 26% | 0 | 252 |
| approval_reuse | 810,797 | 0 | 158,660 | 158,660 | 1,619 | 20% | 0 | 196 |
| p4_p6_p7_combined_or | 883,588 | 1,001,023 | 55,288 | 1,056,311 | 10,779 | 120% | 524 | 66 |
| plan_consistency | 812,206 | 0 | 153,498 | 153,498 | 1,566 | 19% | 0 | 183 |
| provenance | 1,001,052 | 1,085,079 | 69,394 | 1,154,473 | 11,780 | 115% | 497 | 82 |
| similarity_reuse | 799,739 | 0 | 195,929 | 195,929 | 1,999 | 24% | 0 | 239 |
| supervised_risk | 915,485 | 0 | 5,542 | 5,542 | 57 | 1% | 0 | 5 |
| supervised_risk_urlguard | 903,533 | 0 | 5,543 | 5,543 | 57 | 1% | 0 | 5 |
