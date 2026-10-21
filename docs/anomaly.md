# P2 anomaly gate

Owner: P2. Candidate: `p2_anomaly/artifacts/development/cross-suite-v3`.
Status: DEV evaluation in progress; not frozen; no held-out scores.

## Method

The gate represents each proposed tool call with 16 numerical features: action
category, argument size and structure, email/URL counts, overlap with the user
request and earlier tool responses, requested action words, repeated calls and
previous errors. An Isolation Forest with 200 trees and random seed 42 learns
from legitimate calls only. Calls above the calibrated anomaly threshold are
escalated to the shared reviewer. The executor enforces the review budget.

The repaired candidate applies a versioned preprocessing step before both fitting
and scoring: the three chronology/error-count features are zero for read-only
calls. A routine read should not become suspicious solely because it occurs later
in a task or follows a denied call. Argument, overlap and category features remain
active; unsupported tools still follow the coverage checks. This can miss some
context-dependent harmful reads and requires live validation.

The cross-suite candidate uses the shared semantic tool metadata, preserving
the old workspace feature representation. Its table recognizes 69 distinct
tools; 34 have fitting examples. Unseen side-effect tools still require review.
Some unseen reads can transfer only with sufficient read-category evidence and
arguments inside the observed shape range. Recognition does not mean automatic
approval or complete coverage.

The repaired candidate requires review for all non-read actions. It separately
checks URL origins: direct user URLs and links from the explicitly named Slack
source can proceed to statistical scoring; links encountered only inside a webpage
cannot add new browsing/sharing instructions. Unknown URL origins require review.
An explicitly requested summary cannot be replaced by only a link. These are
explicit rules alongside the statistical detector, not learned anomaly results
or the team's combined P7 method. They are not complete provenance verification:
the named channel's contents can themselves be attacker-controlled, and natural
language delegation is only recognized conservatively. Old artifacts retain
their original behavior because these changes are controlled by artifact flags.

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

The repaired threshold is the next representable value above the higher empirical
90th percentile of calibration anomaly scores: 0.5176941669908449. Detector/support
checks flag 4/36 calibration calls (11.1%); this excludes the new source and
mandatory-review rules, which need context-aware live evaluation. This is a
small-sample observation, not a deployment review-rate guarantee. No attacked
calls were added to fitting/calibration. Model and data hashes reproduce identically.

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
`p2_anomaly/artifacts/development/hosted20-v2/live-evaluation.json` once full DEV
starts. The regression pilot has a separate `hosted20-v2-pilot` directory and
does not supply full-suite scores. The old hosted20-v1 run was stopped and kept
as a before-repair record; its completed banking result is 8/18 benchmark-safe,
HITL Load 14, with 25 total reviewer calls. Its Slack failures included two
escalated injected actions incorrectly approved by the reviewer.
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

## Which tasks to run

Use all tasks in the published shared split, not the entire benchmark during
development. Current DEV has 20 user tasks and 46 task/attack pairs per budget;
held-out has 14 user tasks and 34 pairs per budget. Workspace is already examined
and supports development/compatibility checks, not claims of unseen final data.
Freeze the model, rules, threshold and source before running the held-out split.
The two-task repair pilot checks known DEV regressions and clean behavior; it
does not establish general attack resistance. Full DEV starts automatically only
if all two clean and four attacked pilot episodes complete safely. Otherwise
the queue stops for diagnosis rather than reporting a selected subset as final.

The hosted adapter preserves GPT-OSS reasoning fields across tool turns. A
reasoning-only response gets at most two continuation requests; persistent empty
responses stop the run as an infrastructure failure. Reasoning is never used as
the final answer. This adapter change has separate run identities from the first
repair pilot, whose second clean task ended with a blank agent answer despite
all three reads being approved. The current regression run is recorded under
`hosted20-v2-reasoning-pilot`; earlier pilot results remain unchanged.
