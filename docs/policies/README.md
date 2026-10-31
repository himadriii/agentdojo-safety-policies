# Policy notes

One entry per policy. All policies follow the contract in [`../policy_interface.md`](../policy_interface.md). For how they plug into AgentDojo see [`../architecture.md`](../architecture.md). Results for all of them are in the [main README](../../README.md#main-results).

| Policy (CLI name) | Owner | One-line idea | Notes |
|---|---|---|---|
| `full_approve`, `full_escalate` | P1 | Baselines: approve everything, escalate everything | defined in `agent_framework/policy.py` |
| `anomaly` | P2 | Isolation Forest on call features, plus generic guards | [anomaly.md](anomaly.md); historical plan and handoff in [`../archive/`](../archive/) |
| `supervised_risk`, `supervised_risk_urlguard` | P3 | Classifier risk score with two thresholds; the second variant adds URL and reservation guards | [supervised_risk.md](supervised_risk.md), [p3_supervised_risk.md](p3_supervised_risk.md) (technical write-up); earlier report drafts in [`../archive/`](../archive/) |
| `plan_consistency` | P4 | Lexical relevance of the call to the user's task; approve if high, deny if very low, else escalate | [plan_consistency.md](plan_consistency.md) |
| `approval_reuse`, `similarity_reuse` | P6 | Reuse earlier reviewer decisions within a task (`similarity_reuse` is a comparison variant) | [p6_approval_reuse.md](p6_approval_reuse.md); original plan in [`../archive/`](../archive/) |
| `provenance` | P7 | An LLM extracts the authorization and argument provenance; untrusted influence is vetoed | [provenance.md](provenance.md) |
| `p4_p6_p7_combined_or` (**RPP Gate**) | P1 and P4 | Reuse first, then Plan Consistency or Provenance, escalate the rest | [combined_p4_p6_p7_v1.md](combined_p4_p6_p7_v1.md) |

Notes on dates and status: several files record development-time results (the `dev` split, early budgets such as k=5) and some mention hosted-model providers used before the team settled on one shared LM Studio setup. The final held-out numbers are in `report_out/` and the main README; where a policy note disagrees with them, the held-out results are authoritative.

Superseded drafts, development fixtures and historical plans are kept in [`docs/archive/`](../archive/) for reference.
