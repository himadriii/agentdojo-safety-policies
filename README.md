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

## Running locally on MLX-Serve (no Groq quota)

`--provider mlx` runs the agent on a local OpenAI-compatible [MLX-Serve](https://github.com/ddalcu/mlx-serve) server (default `http://127.0.0.1:11234/v1`, override with `MLX_BASE_URL`). `--reviewer local_llm` asks the same local model to review escalations.

```bash
python -m agent_framework.runner --provider mlx --llm mlx-community/gpt-oss-20b-MXFP4-Q8 \
    --policy approval_reuse --reviewer local_llm --suite slack --attack none \
    --user-tasks user_task_1 --k 2 --outdir results/smoke
```

P6's approval-reuse gate (`approval_reuse`, plus the `similarity_reuse` comparison), its offline probe set and replay, and the live-run scripts are described in [`docs/p6_approval_reuse.md`](docs/p6_approval_reuse.md).

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
- Rate limits on Groq's free tier cause `429` retries; use small task subsets.
- Results are cached per pipeline name under `--outdir`; use `--force` to rerun.
- Interface changes go through P1.
