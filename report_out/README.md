# report_out: generated tables and figures

Everything here is generated from the submitted held-out results (`submitted_results/heldout/ALL/k*/`), not edited by hand. The held-out data are 98 unseen test tasks per setting (74 attack, 24 benign) across banking, slack, travel and workspace, at `k` = 0, 2, 5, 7, 10, 15. To regenerate, run the scripts in the order given in the [main README](../README.md#reproduce-the-work).

## `heldout/final/`: the report figures

Display name "RPP Gate" = the `p4_p6_p7_combined_or` policy. Produced by `scripts/report_final_figures.py`.

| File | Shows |
|---|---|
| `fig_pooled_tcr_selected.png`, `fig_pooled_tcr_compact.png` | Pooled TCR@k (attack + benign) for the shortlisted policies and the two baselines |
| `fig_all_policies_pooled_tcr.png` | Pooled TCR@k for every policy tried, showing why the others were not chosen |
| `fig_attack_benign_tcr.png` | TCR@k split into attack tasks and benign tasks |
| `fig_rpp_tcr.png` | RPP Gate against the two baselines (attack, benign, pooled) |
| `fig_hitl_vs_k.png` | Total escalations (human review load) against `k` |
| `fig_cost_stacked_k10.png`, `fig_cost_added_vs_k.png` | API tokens by component (agent, policy, reviewer) at k=10, and added tokens against `k` |
| `fig_failures_k10.png` | Why tasks failed, by failure class, at k=10 |
| `fig_escalation_value.png` | Which kinds of tool calls benefit from human escalation |
| `tcr_pooled_selected.csv` | Numbers behind the pooled TCR figures |
| `tcr_attack_benign_selected.csv` | Numbers behind the attack/benign figure |

## `heldout/`: tables and per-policy detail

| File | Produced by | Contents |
|---|---|---|
| `tcr_by_k.csv` | `report_tcr_hitl.py` | Policy, k, n and TCR for attack, benign and pooled, with 95% Wilson intervals |
| `tcr_<policy>.png`, `tcr_all_{attack,benign,pooled}.png` | `report_tcr_hitl.py` | One policy against the baselines, and every policy on one plot |
| `hitl_total.md/.csv`, `hitl_completed.md` | `report_tcr_hitl.py` | Escalations per policy and k (all tasks, or safely completed tasks only) |
| `cost_by_k.csv`, `cost_k10.md`, `cost_*.png` | `report_cost.py` | Tokens by component, "added" = policy + reviewer tokens on top of the agent |
| `failures_k2.md`, `failures_k10.md`, `failures_by_k.csv` | `report_failures.py` | Each failed task gets one class: over-permissive (an attack got through), over-conservative (a safe call was denied) or other (not caused by the policy, for example agent errors) |
| `failure_examples_*.md`, `trajectories.md` | `report_failures.py` | Representative failing trajectories per policy |
| `escalation_value*.md/.csv` | `report_escalation_value.py` | Calls grouped into read-only, internal reversible, internal irreversible and external effect; how reviewers and each policy treat each class |

## How to read the numbers

- **TCR** counts a task only if it was completed and no attack succeeded.
- **Pooled** adds attack and benign tasks (98 per cell). Intervals are about plus or minus 0.10, so small gaps are not meaningful.
- **Escalations** are reviewer calls. Fewer means less human effort.
- **Added tokens** are the policy's and reviewer's LLM calls; the provenance step makes RPP and Provenance token-heavy.
