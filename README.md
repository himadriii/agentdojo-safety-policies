# AgentDojo Safety Policies

A group project (AI6101) to implement and evaluate safety approval policies for LLM agents using AgentDojo. Every tool call an agent proposes goes through an approval policy that returns `approve`, `deny` or `escalate`, under a per-task escalation budget `k`.

## Features
- Shared policy interface (`approve`, `deny`, `escalate`) with optional reason and scores
- Escalation budget enforcement: once `k` is used up, further escalations are auto-denied
- Reviewer integration (mock reviewer for now; LLM reviewer planned)
- Per-call decision logging and per-component token counts, written into AgentDojo's trace JSON
- Baseline policies (`full_approve`, `full_escalate`) and automated tests

## Setup

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and add your own Groq key (never commit it; `.env` is git-ignored):

```
GROQ_API_KEY=gsk_your_key_here
```

To check which models your key can use:

```bash
set -a; source .env; set +a
curl -s https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY" | python -m json.tool | grep '"id"'
```

## Run Tests (no API key needed)

```bash
python -m pytest tests -q
```

Expected: all tests pass (12 at v0).

## Quick smoke run

```bash
python -m agent_framework.runner --provider groq --policy full_approve \
    --llm openai/gpt-oss-20b --attack none --user-tasks user_task_0 \
    --k 0 --outdir results/smoke
```

The last line prints `TCR` and `HITL`. A single task is noisy, so use it only to check that your setup works. The model is a placeholder and may change; do not make policies depend on it.

## P2 anomaly gate

The `anomaly` policy learns normal calls with Isolation Forest. Scores measure
unusualness, not probability of harm. Unusual calls and scoring failures escalate;
the shared executor enforces the review budget. Unknown side-effect tools require
review. The category candidate can transfer between explicitly classified read tools
only with sufficient training-family support and familiar argument shapes.

**Current status:** the original reference-only model is revoked after a task-family
overlap audit. Two development candidates are saved under
`p2_anomaly/artifacts/development/`. They use 54 audited live fitting calls plus 30
clean references, and 28 separately calibrated live calls. Current `family-v3-*`
calibration escalations are 7/28 for strict coverage and 2/28 for guarded read-category transfer. These are
calibration diagnostics, not held-out benchmark gains. Neither candidate is frozen
or promoted; `readiness.json` records the blocker and resume command. The runner
refuses missing/revoked anomaly artifacts. Runtime scoring failures still escalate.

Live anomaly-controlled episodes and live attack evaluations completed: **zero**.
The latest collection stopped at a Groq HTTP 429 after two completed episodes.
Four additional inspected calibration calls are incorporated in the portable v3 candidates;
one comes from a quota-interrupted episode and does not establish task completion. The next run prioritizes
the actual gate and real reviewer on development tasks, followed by matched baselines.

`p2_anomaly/splits.py` is the canonical split: 13 fit / 8 calibration / 12 common
held-out / 7 quarantined tasks. Task 23, for example, combines held-out tasks 1 and
22. Such development composites and documented near-duplicates are excluded.
Known variants remain together; calibration contains six task families, not eight
independent observations. Earlier v1 calibration figures are superseded.

Reproduce the saved model scores and threshold without API access:

```bash
python -m p2_anomaly.reproduce p2_anomaly/artifacts/development/family-v3-category
python -m pytest tests -q
```

The tested environment is captured in
`p2_anomaly/artifacts/development/environment-lock.txt`. Saved numeric features allow
offline model reproduction; raw traces and detailed audit ledgers remain in the local
git-ignored `results/` directory. Audit decisions are LLM-assisted or assistant-inspected,
not independent human ground truth. Questionable recipients are excluded.

Training takes no API calls. Pass `--audit-manifest <file>` to add hash-checked live
examples; its format is in `p2_anomaly/traces.py`. With an audit manifest, calibration
defaults to real calls only. `--calibration-source mixed` is available for diagnostics.
Held-out/quarantined tasks and injected traces are rejected. Audited partial episodes
require explicit status metadata; their calls never establish episode completion.
Use `--outdir <new-directory>` for candidates; do not overwrite frozen artifacts.

Select an explicit development model through `P2_ANOMALY_MODEL` when experimenting.
The default production path is `p2_anomaly/artifacts/current/model.joblib`, reserved
for a validated promotion. Use the integrated P1 `llm` reviewer for safety evaluation;
the shared low-level runner's default `mock` reviewer approves all escalations.

Real collection and matched evaluation are managed by `python -m p2_anomaly.experiments`:

```bash
python -m p2_anomaly.experiments plan --stage collect --repeats 3 \
    --out results/p2/new-collection/plan.json
python -m p2_anomaly.experiments run --plan results/p2/new-collection/plan.json --max-jobs 5
python -m p2_anomaly.experiments audit --plan results/p2/new-collection/plan.json \
    --out results/p2/new-collection/audit.json --max-calls 25
python -m p2_anomaly.train --audit-manifest results/p2/new-collection/audit.json \
    --support-mode strict --outdir results/p2/candidates/live-strict
```

`run` and `audit` make actual API calls with pacing and automatic retries disabled.
A quota error stops the batch; `--resume-after-quota` is required to resume after reset.
Rejected requests stay failed on resume; a later planned repetition is a separate episode.
The audit records every reviewer decision and error; automated approvals remain
LLM-assisted labels, not verified human ground truth. Inspect representative accepted
calls and all questionable side effects before relying on the dataset.
`--support-mode category` is a candidate comparison: unseen read tools require category
and argument-shape support; unseen side-effect tools still escalate.
Coverage and descriptive task-family bootstrap intervals are saved with each model.
Repeats improve behavioural coverage but do not increase independent family count.

Create `--stage development` plans for candidate runs. Freeze a selected candidate with
`experiments freeze --candidate <directory> --out <new-directory>`, then create a
`--stage final --frozen <directory>` plan. Freezing requires live audited evidence in
both partitions and rejects source/model/data mismatches. This evidence requirement
does not certify production readiness. Final plans compare Full-Approve, Full-Escalate
and the frozen anomaly gate with the LLM reviewer at k=0,2,5. The full default final
matrix contains 972 episodes, plus possible auxiliary benchmark runs; budget it first.
`experiments summarize --plan <path>` reports planned/completed coverage, common-pair
comparisons, uncertainty, review load and response token usage including auxiliary runs.
Missing runs and API errors are never presented as successful safety evaluations.
The 30-call live-calibration floor is a project readiness guard, not production certification.

### Run the P2 handoff on another machine

The course evaluation is the current target. No API calls are needed for setup,
tests, model reproduction, plan creation, or result packaging. Use Python 3.14
(the tested version), check out `p2/anomaly-gate`, and create a virtual environment.
On macOS/Linux:

```bash
git clone --branch p2/anomaly-gate https://github.com/himadriii/agentdojo-safety-policies.git
cd agentdojo-safety-policies
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r p2_anomaly/artifacts/development/environment-lock.txt
python -m pip check
python -m pytest tests -q
python -m p2_anomaly.handoff prepare --out results/p2-teammate
```

If the repository is already cloned, switch to `p2/anomaly-gate` and pull instead.
On Windows activate the environment with `.venv\Scripts\Activate.ps1` in PowerShell.
Create a local `.env` in the repository root containing `GROQ_API_KEY=your-own-key`.
Never send or commit this file. A new key in the same Groq organization shares
the organization's rate limits; do not rotate keys to retry a quota failure.

Run one development episode first to check connectivity and integration. These
are real evaluations, not mock/demo runs. Then resume the same plan:

```bash
python -m p2_anomaly.handoff run --directory results/p2-teammate --phase development --max-jobs 1
python -m p2_anomaly.handoff run --directory results/p2-teammate --phase development --max-jobs 12
```

This runs 12 development episodes: two fit-partition user tasks, clean and
`important_instructions` attack conditions, three policies, and k=2. The anomaly
gate runs first in each matched triplet. All escalations use the real LLM reviewer.
The default candidate is explicitly `family-v3-category`; it is not frozen.
Stochastic single runs and two tasks cannot establish a general benchmark gain.
Do not change source, model, dependencies, or plan while resuming an experiment.

If development finishes without a quota stop, collect additional clean calibration
trajectories (eight planned episodes, never final-test tasks):

```bash
python -m p2_anomaly.handoff run --directory results/p2-teammate --phase calibration --max-jobs 8
```

HTTP 429 stops the current batch. If it occurs, stop all live commands, including
the other phase. Only use `--resume-after-quota` after the provider limit resets.
No paid fallback is configured. Full collection/review/evaluation can exceed a
free-tier allowance; the commands promise resumability, not completion in one quota window.

Package whatever completed, even if quota interrupted the run:

```bash
python -m p2_anomaly.handoff bundle --directory results/p2-teammate --out results/p2-teammate-return.zip
```

Send that ZIP to P2 within the project team. It includes benchmark traces,
ledgers, source snapshots and summaries, excluding `.env` and unrelated files.
Do not manually delete failed episodes or report incomplete plans as successes.
P2 will inspect new clean calls, extend the numeric dataset, retrain/recalibrate,
and freeze the candidate before issuing the held-out plan. Final held-out tasks
and reserved attack settings remain untouched by this handoff. The full final
matrix is 972 episodes. A predeclared `--profile course` final plan provides
108 episodes: all 12 held-out user tasks, clean plus both reserved attack styles,
three policies, and k=2. Each task receives one reserved injection assigned by a
fixed rotation (2/7/9/10), shared across policies. It does not claim full-matrix
coverage, multiple-budget results, or repeated-run reliability. After audit,
recalibration and freeze, P2 can issue that plan with:

```bash
python -m p2_anomaly.experiments plan --stage final --profile course \
    --frozen p2_anomaly/artifacts/frozen/course-v1 --out results/p2-final/plan.json
python -m p2_anomaly.experiments run --plan results/p2-final/plan.json --max-jobs 3
python -m p2_anomaly.experiments summarize --plan results/p2-final/plan.json
```

The freeze directory does not exist yet; these commands are for the next stage,
not part of the initial teammate handoff. Final evidence remains necessary before
claiming improvements; there is no guaranteed AgentDojo score or pass threshold.

## Adding a policy

1. Create `agent_framework/policies/<your_policy>.py` that subclasses `Policy`.
2. Add one line to `agent_framework/registry.py`.
3. Run it with `--policy <your_name>`.

Full contract, context fields, logging and examples: see [`docs/policy_interface.md`](docs/policy_interface.md) (sections 2, 3 and 9).

## Repository layout

```
agent_framework/
  budget.py          escalation budget
  policy.py          Policy interface and baseline policies
  reviewer.py        reviewer interface and mock reviewer
  tools_executor.py  the approval gate (P1ToolsExecutor)
  usage.py           token accounting
  llm_providers.py   Groq adapter
  registry.py        POLICIES / REVIEWERS
  runner.py          benchmark entry point
  policies/          one file per team member's policy
docs/policy_interface.md
tests/
results/             run outputs (git-ignored)
```

## Notes
- P2 experiments stop on `429`; the low-level shared runner may retry unless configured otherwise.
- Results are cached per pipeline name under `--outdir`; use `--force` to rerun.
- Interface changes go through P1.
