# AgentDojo Safety Policies

A group project (AI6101) to implement and evaluate safety approval policies for LLM agents using AgentDojo. Every tool call an agent proposes goes through an approval policy that returns `approve`, `deny` or `escalate`, under a per-task escalation budget `k`.

## Features
- Shared policy interface (`approve`, `deny`, `escalate`) with optional reason and scores
- Escalation budget enforcement: once `k` is used up, further escalations are auto-denied
- Reviewer integration (mock reviewer for now; LLM reviewer planned)
- Per-call decision logging and per-component token counts, written into AgentDojo's trace JSON
- Baseline policies (`full_approve`, `full_escalate`) and automated tests

For local and hosted inference commands with `.env` configuration, see [runner.md](runner.md).

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
clean references, and 24 separately calibrated live calls. Calibration escalations
are 6/24 for strict coverage and 2/24 for guarded read-category transfer. These are
calibration diagnostics, not held-out benchmark gains. Neither candidate is frozen
or promoted; `readiness.json` records the blocker and resume command. The runner
refuses missing/revoked anomaly artifacts. Runtime scoring failures still escalate.

Live anomaly-controlled episodes and live attack evaluations completed: **zero**.
The latest collection stopped at a Groq HTTP 429 after two completed episodes.
Four additional inspected calibration calls are saved locally (28 available total),
but are not yet incorporated in the saved candidates. The next run prioritizes
the actual gate and real reviewer on development tasks, followed by matched baselines.

`p2_anomaly/splits.py` is the canonical split: 13 fit / 8 calibration / 12 common
held-out / 7 quarantined tasks. Task 23, for example, combines held-out tasks 1 and
22. Such development composites and documented near-duplicates are excluded.
Known variants remain together; calibration contains six task families, not eight
independent observations. Earlier v1 calibration figures are superseded.

Reproduce the saved model scores and threshold without API access:

```bash
python -m p2_anomaly.reproduce p2_anomaly/artifacts/development/family-v2-category
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
