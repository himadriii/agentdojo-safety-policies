# Run Reports

This folder contains status reports for local benchmark runs. It is separate from
`submitted_results/`, which contains reviewed result sets intended for submission.

## 2026-10-25 — ALL policies, dev split, k=0 and k=2

**Status: incomplete. Do not use this run as a complete comparison or submit it as
the final result set.**

### Configuration

- Provider: LM Studio
- Model: `openai/gpt-oss-20b`
- Owner directory: `ALL`
- Policies: `full_escalate`, `anomaly`, `supervised_risk`,
  `supervised_risk_urlguard`, `approval_reuse`, `similarity_reuse`,
  `plan_consistency`, `provenance`, `p4_p6_p7_combined_or`
- k values: 0 and 2
- Suites: banking, Slack, and travel
- Benign runs: enabled

### Coverage

There are **104 of 108 expected summaries** under the local ignored directory
`results/dev/ALL/`. All 104 existing summaries pass the repository's summary
configuration checker and report zero task errors. Four benign travel summaries
are missing:

| Policy | k | Missing summary |
|---|---:|---|
| `supervised_risk` | 2 | `summary_travel_none.json` |
| `supervised_risk_urlguard` | 0 | `summary_travel_none.json` |
| `supervised_risk_urlguard` | 2 | `summary_travel_none.json` |
| `approval_reuse` | 2 | `summary_travel_none.json` |

### Run notes

- Smoke contract tests passed: 178 tests.
- The LM Studio endpoint intermittently returned HTTP 503 and a 400 error with
  `The model produced output that does not match the expected peg-native format`.
- These errors caused some commands to exit nonzero after writing partial results.
- Heldout was not run: the original `&&` command chain stopped when dev returned
  nonzero.
- Raw results and logs remain local under `results/dev/ALL/` and `logs/`; they are
  git-ignored or untracked and are not copied here.

### Before treating this as complete

Rerun the four missing benign travel cases after stabilizing the LM Studio server,
then verify all 108 summaries and rerun `python scripts/check_summaries.py
results/dev/ALL`.
