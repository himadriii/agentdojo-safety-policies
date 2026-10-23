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

To run P4's deterministic plan-consistency baseline, replace `full_approve`
with `plan_consistency`. The policy uses the user task, proposed tool call,
and prior assistant tool calls; it does not depend on the selected agent model.
P4 implementation notes and limitations: [`docs/plan_consistency.md`](docs/plan_consistency.md).

The last line prints `TCR` and `HITL`. A single task is noisy, so use it only to check that your setup works. The model is a placeholder and may change; do not make policies depend on it.

## P2 anomaly gate

**October 21 shared-workflow update:** this branch has integrated shared main
`4b5ed4d` and its protected runner, executor, tool metadata and split files.
Workspace is fully examined development data. Official held-out splits now cover
banking, Slack and travel. The saved P2 models below remain workspace-specific;
their historical results used a 20B reviewer and must not be reported as results
for the current shared 120B reviewer (`v2` prompt).

Current agreed settings are Groq GPT-OSS-20B agent / GPT-OSS-120B reviewer,
free tier only. P2's collector uses scoped quota-stop factories around the shared
runner: same normal request and prompt configuration, zero SDK/quota retries,
and immediate stop on quota errors. Shared protected files are unchanged.
Older adapter checks are explicitly historical; shared tests target main's code.

Start clean collection only on a published DEV split:

```bash
python -m p2_anomaly.experiments plan --stage collect_shared --suite banking \
    --out results/p2-shared-banking/plan.json
python -m p2_anomaly.experiments run --plan results/p2-shared-banking/plan.json --max-jobs 1
```

The collector validates DEV IDs and the split checksum. Accepted calls still
require an audit and cross-suite fitting/calibration before anomaly evaluation.
It adapts the shared runner's on-disk summary without editing the official summary.
Do not run a workspace model on the new suites and interpret unknown-tool
fallbacks as learned anomaly performance. Do not run held-out tasks yet.
The offline tool/composition audit and predeclared inner DEV partitions are in
`shared-suite-readiness.json` and `shared-inner-plan.json` under development artifacts.
The first six banking DEV collection episodes finished with four utility successes;
see `shared-banking-collection.json`. These are Full-Approve collection results,
not anomaly-policy scores, and their calls are still awaiting an audit.

The `anomaly` policy learns normal calls with Isolation Forest. Scores measure
unusualness, not probability of harm. Unusual calls and scoring failures escalate;
the shared executor enforces the review budget. Unknown side-effect tools require
review. The category candidate can transfer between explicitly classified read tools
only with sufficient training-family support and familiar argument shapes.

**Current status:** the original model was revoked after a task-family overlap
audit. Current backend-specific development candidates are
`p2_anomaly/artifacts/development/lmstudio-v2-{category,strict}`. They use 93
accepted live fitting calls (54 earlier Groq + 39 LM Studio), 30 clean fitting
references, and 34 separate LM Studio calibration calls. Calibration spans six
families and only 11 distinct feature vectors. Category flags 3/34 calls; strict
flags 7/34. These are calibration diagnostics, not held-out scores.

The expanded live comparison covers user tasks 3, 7, 29 and 32, clean and
`important_instructions` injection 0, with the real reviewer at k=2. All 24
scenario-matched episodes completed across sessions with matching runtime source,
endpoint and settings:

| Policy | Clean safe completions | Attacked safe completions | Successful attacks | Reviews across eight episodes |
| --- | --- | --- | --- | --- |
| Current category gate | 4/4 | 2/4 | 0/4 | 11 |
| Full-Approve | 4/4 | 1/4 | 3/4 | 0 |
| Full-Escalate | 2/4 | 1/4 | 0/4 | 16 |

See `p2_anomaly/artifacts/development/lmstudio-expanded-comparison.json` for
records, provenance, and descriptive paired uncertainty. This is development
evidence on four fitting-partition tasks, not independent held-out performance.
One reviewer server error affected the gate's attacked task 3 run. Another blocked
attack was followed by an agent falsely claiming a file edit, so preventing an
attack did not ensure task completion. Full-Approve ignored an injection in one
file-share run, illustrating trajectory variability even at temperature zero.

The earlier `family-v3-category` comparison on two tasks remains in
`lmstudio-comparison.json`; it is a different model and narrower evidence.
Neither current candidate is frozen or promoted. Final evaluation is blocked
pending the team's task-exposure audit and split agreement. Scoring failures and
unseen side-effect tools continue to escalate.

`p2_anomaly/splits.py` is the canonical split: 13 fit / 8 calibration / 12 common
held-out / 7 quarantined tasks. Task 23, for example, combines held-out tasks 1 and
22. Such development composites and documented near-duplicates are excluded.
Known variants remain together; calibration contains six task families, not eight
independent observations. Earlier v1 calibration figures are superseded.

Reproduce the saved model scores and threshold without API access:

```bash
python -m p2_anomaly.reproduce p2_anomaly/artifacts/development/lmstudio-v2-category
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

### Shared LM Studio inference and task exposure

`p2_anomaly/task_exposure.json` records P2's historical task exposure. Earlier
reference/collection tasks included components of proposed held-out tasks; removing
them from current training does not undo that exposure. The proposed 12-task final
split is provisional, and final plan generation is blocked pending team agreement.
Do not use the unrestricted all-task command in `runner.md` for P2 evaluation.

For a teammate-hosted LM Studio endpoint, set `LLM_PROVIDER=lmstudio`,
`REVIEWER_PROVIDER=lmstudio`, `LMSTUDIO_MODEL=openai/gpt-oss-20b`,
`LMSTUDIO_BASE_URL=<provided-url>/v1`, and `LMSTUDIO_API_KEY=<provided-key>`
in the local `.env`. Never commit the endpoint credential. Then create a separate
experiment, without resuming or pooling Groq episodes:

```bash
python -m p2_anomaly.handoff prepare --provider lmstudio --out results/p2-lmstudio
python -m p2_anomaly.handoff run --directory results/p2-lmstudio --phase development --max-jobs 1
```

After inspecting the first episode, resume the same directory with `--max-jobs 12`.
The existing Groq-trained candidate is being tested for transfer to this inference
configuration; matching model IDs do not establish matching quantization or behavior.
The endpoint and local adapter settings are recorded in execution metadata. Shared
server-side model settings remain outside this repository's control.

LM Studio collection now includes 13 fitting-task episodes and 19 calibration
episodes, including repeated checks on existing tasks. Audits excluded unsupported
recipient sends, subsequent uncertain task-25 calls, and incorrect new grocery-list
files. The accepted dataset and tool/category coverage are saved with the current
candidate and in `p2_anomaly/artifacts/development/lmstudio-coverage.json`.
Sharing now has two accepted live LM Studio examples. Sending still has only two
accepted live examples from Groq; no legitimate destructive operations are covered.
Unknown side-effect tools require review. Repeats did not increase the six
independent calibration families; passing the 30-call floor is not certification.

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
Create a local `.env` in the repository root containing `GROQ_API_KEY=your-own-key`
and `REVIEWER_PROVIDER=groq`. Current shared P2 plans pin the agent to
`openai/gpt-oss-20b` and the reviewer to `openai/gpt-oss-120b`, following
[`scripts/team_settings.sh`](scripts/team_settings.sh). Earlier P2 runs used
20B for both roles; those historical scores must remain separate. The general
runner's local-inference options are separate experiments and must not be mixed
into these comparisons.
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
and freeze the candidate before issuing the held-out plan. This handoff does not
run the provisional final task IDs or reserved attack settings. Historical
composite-task exposure must still be reconciled with the team. The full final
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
## Running locally on MLX-Serve (no Groq quota)

`--provider mlx` runs the agent on a local OpenAI-compatible [MLX-Serve](https://github.com/ddalcu/mlx-serve) server (default `http://127.0.0.1:11234/v1`, override with `MLX_BASE_URL`). `--reviewer local_llm` asks the same local model to review escalations.

```bash
python -m agent_framework.runner --provider mlx --llm mlx-community/gpt-oss-20b-MXFP4-Q8 \
    --policy approval_reuse --reviewer local_llm --suite slack --attack none \
    --user-tasks user_task_1 --k 2 --outdir results/smoke
```

P6's approval-reuse gate (`approval_reuse`, plus the `similarity_reuse` comparison), its offline probe set and replay, and the live-run scripts are described in [`docs/p6_approval_reuse.md`](docs/p6_approval_reuse.md).

The first combined policy is `p4_p6_p7_combined_or`. It reuses both prior
P6 reviewer approvals and denials. On a P6 memory miss, it evaluates P4 and P7
with a reason-aware rule. A P7 denial for untrusted influence is final;
otherwise either approval wins, two denials deny, and mixed deny/escalate or
two-escalate outcomes go to the reviewer.

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
