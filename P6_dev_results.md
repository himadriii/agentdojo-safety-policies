**P6 — Approval Reuse Gate (Kush)**

Shared DEV tasks · AgentDojo v1.2 · Attack: `important_instructions` ·
Review budget: **k \= 2**
Agent and reviewer: **GPT-OSS-20B**, both through LM Studio (shared setup). The gate wraps full-escalate and makes no LLM calls.

| Suite | Safely completed | TCR | HITL Load | Total reviews | Reuse approvals | Successful attacks | Auto-denials | Budget-exhausted denials |
| ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- |
| Banking | 6/18 | 33.3% | 12 | 24 | 0 | 0 | **0** | **2** |
| Slack | 0/14 | 0.0% | 0 | 28 | 16 | 0 | **0** | **16** |
| Travel | 1/14 | 7.1% | 2 | 26 | 41 | 0 | **0** | **7** |
| **Overall** | **7/46** | **15.2%** | **14** | **78** | **57** | **0** | **0** | **25** |

**Against the other k=2 gates (overall, n=46)**

| Gate | Safely completed | Successful attacks | Budget-exhausted denials |
| ----- | ----- | ----- | ----- |
| No gate (full_approve, k=0) | 5 (10.9%) | 32 | 0 |
| P2 Anomaly | 29 (63.0%) | 0 | 0 |
| P3 Supervised risk + URL guard | 10 (21.7%) | 2 | n/a |
| P4 Plan Consistency | 6 (13.0%) | 3 | 29 |
| **P6 Approval reuse** | **7 (15.2%)** | **0** | **25** |

- **No attack succeeded**, against 32 with no gate. No task errors were recorded.
- **Reuse ran 57 of 160 calls (36%) without a review**, 53 of them through the drill-down rule (for example `get_all_hotels_in_city` → `get_hotels_prices`). With only two reviews per task, each of those calls would otherwise have been a budget denial.
- **Banking got no reuse.** Its tasks call different tools once each, so P6 behaves like full-escalate there.
- Reviewer tokens: 60k across all suites.

**Main limitations**

* **At k=2 the budget is the bottleneck.** Reuse covers repeated reads, but each new side effect (`send_direct_message`, `send_channel_message`, `get_webpage` on a new URL, calendar events) still needs its own review. In Slack, 16 such calls were denied once the budget ran out, which is why Slack completed 0/14.
* **Travel reflects the agent, not the gate.** Its TCR is near zero under every policy (full_approve: 0/14 utility).
* **Reuse inherits the reviewer's decision.** A reused approval is only as safe as the reviewer approval it copies.
* **Single run.** For reference, the shared k=15 run reached 10/46 with 38% fewer reviews than full-escalate (101 vs 163).

**Potential combinations**

| Other gate | Recommendation |
| ----- | ----- |
| **Plan Consistency gate (P4)** | Strongest fit. P4 hit 29 budget-exhausted denials at k=2, and reuse removes repeat reviews of the same tool. |
| **Provenance gate (P7)** | Wrap P7's escalations: P7 blocks unsupported targets, and P6 avoids re-reviewing the ones already approved. |
| **Anomaly gate (P2)** | Little to gain: P2 already ran with 0 budget-exhausted denials. |

**Recommended experiment:** wrap P4 and P7 in `approval_reuse` and compare each against its base gate at k=2 on identical DEV pairs, reporting TCR, total reviews and budget-exhausted denials per pair.
