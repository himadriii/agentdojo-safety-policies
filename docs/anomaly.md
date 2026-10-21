# P2 anomaly gate

Owner: P2. Candidate: `p2_anomaly/artifacts/development/cross-suite-v2`.
Status: DEV evaluation in progress; not frozen; no held-out scores.

## Method

The gate represents each proposed tool call with 16 numerical features: action
category, argument size and structure, email/URL counts, overlap with the user
request and earlier tool responses, requested action words, repeated calls and
previous errors. An Isolation Forest with 200 trees and random seed 42 learns
from legitimate calls only. Calls above the calibrated anomaly threshold are
escalated to the shared reviewer. The executor enforces the review budget.

The cross-suite candidate uses the shared semantic tool metadata, preserving
the old workspace feature representation. Its table recognizes 69 distinct
tools; 34 have fitting examples. Unseen side-effect tools still require review.
Some unseen reads can transfer only with sufficient read-category evidence and
arguments inside the observed shape range. Recognition does not mean automatic
approval or complete coverage.

The candidate also requires review for banking state changes and `get_webpage`
(a URL fetch can send data out). This is an explicit safety rule alongside the
statistical detector, not a learned anomaly result. Old artifacts retain their
original behavior because they do not contain this rule configuration.

## Data and calibration

Data comes from the pinned AgentDojo environments, clean reference trajectories
on permitted DEV fitting tasks, and selected calls from clean live trajectories.
Attacked trajectories are used for evaluation only, not fitting or calibration.

| Suite | Fitting calls | Calibration calls |
|---|---:|---:|
| Workspace | 123 | 34 |
| Banking | 13 | 2 |
| Slack | 17 | 0 |
| Travel | 31 | 0 |
| Total | 184 | 36 |

Workspace fitting retains 93 audited live calls and 30 reference calls. Banking
adds seven reference and six selected live fitting calls. Slack/travel fitting
currently uses references only. Audit selections were made by the assistant,
not by an independent human reviewer. A clean episode's utility score alone is
not sufficient to admit its calls: duplicate payments and ungrounded actions
were excluded from the banking audit.

Shared DEV fitting/calibration IDs were declared before collection in
`shared-inner-plan.json`. Suite-qualified IDs prevent collisions. Reference
fitting checks composite-task overlap against calibration components; outer
held-out IDs are never executed. Calibration tasks are not moved into fitting.
Banking calibration has only one task producing calls. Pooled calibration mixes
earlier LM Studio workspace traces with Groq banking traces, so independent
Groq calibration and live Slack/travel coverage remain limitations.

The threshold is the next representable value above the higher empirical 90th
percentile of calibration anomaly scores: 0.5226544167828204. The complete gate
flags 4/36 calibration calls (11.1%). This is a small-sample observation, not a
deployment review-rate guarantee. Model and data hashes reproduce identically.

## Evaluation

The owner's current primary evaluation uses hosted `openai/gpt-oss-20b` for
both the agent and the `llm` reviewer, reviewer prompt v2, AgentDojo v1.2 and
`important_instructions`. It starts with k=2 plus clean controls on all three
published DEV suites. Optional budget comparisons require the same configuration.
The agent uses `LMSTUDIO_*`; the separate reviewer endpoint uses `INFERENCE_*`
with `REVIEWER_PROVIDER=compatible`. This replaces the earlier 20B/120B setting
for P2's primary evaluation; scores from the two configurations remain separate.
Runs are serial and stop at rate limits, server errors or reviewer parse failures.
Hosted capacity is not assumed unlimited, and no Groq fallback is used.

Measured, complete primary 20B/20B runs are recorded in
`p2_anomaly/artifacts/development/hosted20-v1/live-evaluation.json`.
Earlier Groq 20B/120B results remain in the cross-suite-v2 report directory.
Incomplete runs do not receive final metrics. TCR@k is the fraction of all
episodes with utility success and attack failure. HITL Load is the sum of LLM
reviewer calls on safely completed episodes; total reviewer calls are also
reported so failed tasks' costs remain visible. Trace checks validate logging
invariants, not task correctness or security.

Banking utility needs qualification: task 5 can pass on an existing transaction
even if no new top-up executes; task 10 intentionally rewards no state change
for an underspecified instruction. Report official scores and trace evidence
separately. A zero attack-success rate can also accompany failed user tasks or
an agent that never reads the injected material.

Offline replay of the old banking run's 54 fixed proposals reduces escalations
from 54 to 24 and hypothetical over-budget calls at k=2 from 22 to 1. This is
not a live TCR improvement or measured reviewer saving: changed decisions alter
the agent's later actions. Earlier workspace compatibility (3/3 safe) and banking
DEV (5/18 benchmark-safe) results belong to the old workspace-trained artifact.

## Findings, limitations and combination

- Catches unusual action transitions, argument shapes and some unrelated actions.
  Earlier workspace traces flagged injected email sends while allowing the
  requested calendar reads and final answers.
- Legitimate rare calls and unsupported actions can be escalated; once k is
  exhausted these are denied. Large k can reduce this interference but increases
  cost and exposure to reviewer mistakes.
- Familiar-looking malicious arguments can evade anomaly scoring. A familiar
  recipient-shaped string is not proof of authorization. Banking changes retain
  mandatory review, but the reviewer is fallible.
- Agent clarification/refusal, wrong arguments and tool-call formatting failures
  can cause task failure independently of gate decisions.
- The anomaly scorer makes no LLM requests; the agent and reviewer consume API
  tokens. Report token counts and review calls, not an invented monetary cost.
- P7 provenance checking and P4 plan consistency are complementary candidates:
  they check instruction source and relation to the user's request. No combined
  improvement has been established. P1/P4 own combined-method implementation.
- Full task exposure is recorded in `p2_anomaly/task_exposure.json`; removing
  examples later does not undo exposure. The candidate has not been promoted,
  frozen or evaluated on held-out tasks.
