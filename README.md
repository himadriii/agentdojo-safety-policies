# AgentDojo Safety Policies

AI6101 Group Project 1. We implement and evaluate approval policies for LLM agents on AgentDojo. Every tool call the agent proposes goes through one policy that returns `approve`, `deny` or `escalate`, under a per-task escalation budget `k`. Escalated calls go to an LLM-simulated human reviewer. The metric is TCR@k: the fraction of tasks completed without a successful attack when at most `k` calls per task can be escalated.

## Features

- Shared policy interface (`approve`, `deny`, `escalate`) with an optional reason and scores
- Escalation budget: once `k` is used up, further escalations are auto-denied
- Reviewers: `mock` (approves or denies everything, for tests) and `llm` (the simulated human reviewer used for all reported results)
- Per-call decision logging and per-component token counts (agent, policy, reviewer), written into AgentDojo's trace JSON
- Baselines `full_approve` and `full_escalate`, plus the team's policies (see below)
- Automated tests that run offline

Hosting the shared model: [P5 Inference Gateway](p5_inferencing/README.md) documents
LM Studio model loading, the authenticated gateway, ngrok tunneling, client IP
restrictions, and host/client configuration using `.env.example` files.

## Shared setup (read this before running anything for results)

All results that go into the report must use **one** setup, so that policies are compared fairly:

| Item | Value |
|---|---|
| Inference | LM Studio server on a teammate's laptop |
| Agent model | `openai/gpt-oss-20b` |
| Reviewer model | `openai/gpt-oss-20b` (same model, same server) |
| Policy LLM (P7 only) | `openai/gpt-oss-20b` (same model, same server) |
| Reviewer | `llm` |
| Benchmark | AgentDojo `v1.2`, attack `important_instructions` |
| Suites and splits | `banking`, `slack`, `travel`; `splits/<suite>_v1.2.json` |
| Escalation budgets | `k` = 0 1 2 3 5 10 |

Rules:

- Do not set `REVIEWER_PROVIDER`, `REVIEWER_MODEL`, `PROVENANCE_PROVIDER` or `PROVENANCE_MODEL` in `.env`. Leaving them unset makes the reviewer and P7's policy use the agent's model.
- Do not use Groq, Ollama, MLX or another model for reported results. Those runs are development-only and must not be pooled with shared results.
- `results/` is local and git-ignored. Never `git add -f` anything from it. Only what you copy into `submitted_results/<split>/<name>/` is shared (see "Where results go").
- Do not change the agent system prompt or the reviewer prompt for a reported run. Prompt changes go through P1 and bump the reviewer prompt version.
- The `heldout` split is for the final frozen run only. The runner refuses it unless `FINAL_RUN=1`. Do not tune on it.

## Setup

```bash
git checkout main && git pull
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` (git-ignored; never commit it):

```
LLM_PROVIDER=lmstudio
LMSTUDIO_MODEL=openai/gpt-oss-20b
LMSTUDIO_BASE_URL=<url from the host>/v1
LMSTUDIO_API_KEY=<key from the host>
```

Ask the host for the URL and key. Never put them in a commit, issue or pull request. The URL may change when the host restarts the tunnel, so update `.env` when that happens.

Check that the server answers and lists the model:

```bash
set -a; source .env; set +a
curl -s -H "Authorization: Bearer $LMSTUDIO_API_KEY" -H "ngrok-skip-browser-warning: 1" \
    "$LMSTUDIO_BASE_URL/models" | python -m json.tool | grep '"id"'
```

If you get an HTML page or a 502, the server or tunnel is down: ask the host to check that the model is loaded and the server is running.

Host checklist (everyone's results depend on it): the same loaded model and quantization all the time, a context length large enough for the long tasks, KV-cache quantization **off** (it causes `RotatingKVCache Quantization NYI` errors), and a fixed reasoning-effort setting. Tell the team if any of these change.

## Run the tests (offline, no server needed)

```bash
python -m pytest tests -q
```

`tests/test_p2_handoff.py` fails with "openai version mismatch" unless you install the P2 environment lock. This is known and unrelated to your policy.

## Smoke test

One task, to check that your setup works. A single task is noisy, so never report it.

```bash
python -m agent_framework.runner --provider lmstudio --llm openai/gpt-oss-20b \
    --policy full_approve --attack none --user-tasks user_task_0 --k 0 --outdir results/smoke
```

The last line prints `TCR` and `HITL`.

## How to do a dev run

1. Update: `git checkout main && git pull`, activate the venv, reinstall requirements if they changed.
2. Check `.env` has only the four lines above, and that the curl check lists `openai/gpt-oss-20b`.
3. Make sure your policy is registered in `agent_framework/registry.py` and that `python -m pytest tests -q` passes (apart from the known P2 handoff failures).
4. Run the smoke test above with your policy name.
5. Run the full dev run with the shared script. It runs all three suites over the whole `k` grid:

   ```bash
   scripts/team_settings.sh <policy> <owner> [dev|heldout] ["k values"]
   scripts/team_settings.sh provenance P7                 # dev, k = 0 1 2 3 5 10
   scripts/team_settings.sh provenance P7 dev "2"         # dev, k = 2 only (first look)
   ```

   Results go to `results/dev/<owner>/`. Runs are cached per pipeline name; add `--force` to the runner (not the script) only if you must redo one. If the server drops mid-run, restart the same command: finished tasks are skipped.
6. Check the setup in your summaries:

   ```bash
   python scripts/check_summaries.py results/dev/<owner>
   ```

   Every line must say `ok`. A `FAIL` lists the wrong model, a mock reviewer, or errored tasks. Fix the cause and rerun. Do not edit summaries by hand.
7. Look at your results: each `summary_<suite>_important_instructions.json` has TCR, `hitl_load_completed`, `hitl_load_all`, token usage per component, and every gate decision. If `tasks_with_errors` is above zero, those pairs are not real completions: rerun them.
8. Submit: copy your finished run into `submitted_results/` (see "Where results go"), commit that folder only, and open a pull request to `main`. Write in the description any deviation from the shared setup and why. Results with a deviation can be used for discussion but not in the final tables.

For the final report, P1 runs `heldout` once per policy after each policy is frozen:

```bash
FINAL_RUN=1 scripts/team_settings.sh <policy> <owner> heldout
```

The held-out run is submitted to `submitted_results/heldout/<name>/` the same way.

## Where results go

- `results/` is your own scratch space. It is git-ignored, so smoke tests, failed runs and experiments stay on your machine. Do not commit it and do not force-add it.
- Anything that should count is copied to `submitted_results/<split>/<name>/`, where `<split>` is `dev` or `heldout` and `<name>` is your number (`P1` for baselines, `P2`, `P3`, `P4`, `P6`, `P7`) or `P4_P6_P7_combined_or` for the team's combined policy. Use the same `<name>` as the owner argument of `scripts/team_settings.sh`.

```bash
python scripts/check_summaries.py results/dev/P7          # all lines must say ok
mkdir -p submitted_results/dev/P7
cp -r results/dev/P7/. submitted_results/dev/P7/          # summaries and traces
git add submitted_results/dev/P7
```

- Submit only the final dev run and, at the end, the one held-out run. Notes go in `NOTES.md` inside your folder; analysis scripts and model artifacts stay with your code.

## Policies

| CLI name | Owner | Idea |
|---|---|---|
| `full_approve` | baseline | approve every call |
| `full_escalate` | baseline | escalate every call |
| `anomaly` | P2 | Isolation Forest on call features, plus generic guards |
| `supervised_risk` | P3 | classifier-based risk score with two thresholds |
| `plan_consistency` | P4 | lexical relevance of the call to the task |
| `approval_reuse` | P6 | reuse earlier reviewer decisions within a task |
| `provenance` | P7 | LLM-extracted authorization and argument provenance |
| `p4_p6_p7_combined_or` | team | P6 reuse, then P4 or P7 |

Details: [`docs/policy_interface.md`](docs/policy_interface.md) (the contract), [`docs/tool_metadata.md`](docs/tool_metadata.md) (per-tool metadata), [`docs/policies/plan_consistency.md`](docs/policies/plan_consistency.md), [`docs/policies/p3_supervised_risk.md`](docs/policies/p3_supervised_risk.md), [`docs/policies/p6_approval_reuse.md`](docs/policies/p6_approval_reuse.md), [`docs/policies/provenance.md`](docs/policies/provenance.md), [`docs/policies/combined_p4_p6_p7_v1.md`](docs/policies/combined_p4_p6_p7_v1.md), [`docs/policies/anomaly.md`](docs/policies/anomaly.md) (P2). P2's anomaly gate notes and the handoff procedure are in [`docs/policies/p2_anomaly_handoff.md`](docs/policies/p2_anomaly_handoff.md).

## The simulated reviewer

`--reviewer llm` uses `agent_framework/llm_reviewer.py`. It sees the user's request, the recent conversation (tool results are clipped), and the proposed call, and returns `approve` or `deny` with a one-sentence reason. It never sees benchmark labels, injection or attack information, or the policy's internal evidence. The prompt version is part of the result folder name. Server errors and unparseable replies count as a denial and are recorded in the reason (`REVIEWER_ERROR`, `REVIEWER_PARSE_FAILURE`). A design note is being written for the report.

## Adding a policy

1. Create `agent_framework/policies/<your_policy>.py` that subclasses `Policy`.
2. Add one line to `agent_framework/registry.py`.
3. Run it with `--policy <your_name>` and follow "How to do a dev run".

Full contract, context fields, logging and examples: [`docs/policy_interface.md`](docs/policy_interface.md) (sections 2, 3 and 9). Use only `context`; benchmark labels and injection details must never reach a policy.

## Local development without the shared server

For quick local tests you may use another provider (`--provider groq`, `--provider mlx`, or a local LM Studio at `http://127.0.0.1:1234/v1`). These runs are for development only and must not be submitted as results. MLX example:

```bash
python -m agent_framework.runner --provider mlx --llm mlx-community/gpt-oss-20b-MXFP4-Q8 \
    --policy approval_reuse --reviewer local_llm --suite slack --attack none \
    --user-tasks user_task_1 --k 2 --outdir results/smoke
```

Other runner options (local and hosted inference): [`docs/runner.md`](docs/runner.md).

## Repository layout

```
agent_framework/
  budget.py          escalation budget
  policy.py          Policy interface and baseline policies
  reviewer.py        reviewer interface and mock reviewer
  llm_reviewer.py    the simulated human reviewer
  tools_executor.py  the approval gate (P1ToolsExecutor)
  usage.py           token accounting
  inference.py       provider clients (LM Studio, Groq, ...)
  registry.py        POLICIES / REVIEWERS
  runner.py          benchmark entry point
  policies/          one file per policy
scripts/
  team_settings.sh   the shared dev / held-out run command
  check_summaries.py checks that summaries use the shared setup
  make_split.py, verify_traces.py, eval_reviewer.py, ...  analysis helpers
splits/              dev and held-out task lists per suite
docs/                policy contract (policy_interface.md), tool_metadata.md, runner.md,
                     policies/ (one set of notes per policy), report/
tests/               offline tests
p2_anomaly/          P2 training code and model artifacts
p3_risk/             P3 training code, data and model artifacts
p6_reuse/            P6 scripts and helpers
results/             local scratch outputs (git-ignored, never committed)
submitted_results/   dev|heldout/<name>/  the only results that are shared
CLAUDE.md            notes for Claude Code sessions
```

Each owner keeps policy-specific training code, data and scripts in their own top-level folder. Shared code changes go through P1.

## Notes

- Results are cached per pipeline name under `--outdir`; use `--force` to rerun.
- `tasks_with_errors` counts context-length and server errors; those pairs are not real completions.
- The security check is final-state only: a harmful call that was executed but left no trace is not counted as an attack success.
- Interface changes go through P1.
