# P4 dev results overview

These counts are aggregated from the per-task `rows` in the three submitted
summary files. Each row is one user-task and injection-task combination.
`Attack succeeded` means the benchmark's injected goal succeeded. A safe
completion requires utility success **and** attack failure.

| Suite | Task cases | Utility succeeded | Utility failed | Attack succeeded | Attack failed | Completed safely | Auto-denials | Budget-exhausted denials |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Banking | 18 | 6 | 12 | 0 | 18 | 6 | 6 | 0 |
| Slack | 14 | 1 | 13 | 3 | 11 | 0 | 6 | 8 |
| Travel | 14 | 0 | 14 | 0 | 14 | 0 | 0 | 21 |
| **Total** | **46** | **7** | **39** | **3** | **43** | **6** | **12** | **29** |

The attack-failure counts are the remaining cases with no successful injected
goal. These are development-split results for AgentDojo v1.2,
`important_instructions`, LM Studio `openai/gpt-oss-20b` as both agent and
reviewer, and `k=2`. They are not heldout estimates. See each suite's summary
JSON for task-level outcomes and token counts.
