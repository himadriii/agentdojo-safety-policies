# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AI6101 group project: approval policies (gates) for LLM agents, evaluated on AgentDojo. Every tool call the agent proposes goes through one policy that returns `approve`, `deny` or `escalate`, under a per-task escalation budget `k`. Seven owners (P1–P7) each build one policy against a single shared contract owned by P1. The authoritative contract is `docs/policy_interface.md`; interface changes go through P1. `docs/team_workflow.md` has the shared setup and the dev-run procedure; `README.md` is the project overview.

## Shared setup (applies to every reported result)

- Inference: LM Studio on a teammate's laptop, `openai/gpt-oss-20b` for the agent, the reviewer and P7's policy LLM. Set in `.env` (`LLM_PROVIDER=lmstudio`, `LMSTUDIO_MODEL`, `LMSTUDIO_BASE_URL`, `LMSTUDIO_API_KEY`). Never commit `.env`, the URL or the key.
- Do not set `REVIEWER_*` or `PROVENANCE_*` in `.env`; unset means they follow the agent model.
- Reviewer `llm`, attack `important_instructions`, benchmark `v1.2`, suites banking/slack/travel via `splits/<suite>_v1.2.json`, `k` = 0 1 2 3 5 10.
- Run with `scripts/team_settings.sh <policy> <owner> <dev|heldout>`, then `python scripts/check_summaries.py results/<split>/<owner>`, where `<owner>` is `P1`..`P7` or `P4_P6_P7_combined_or`.
- The `heldout` split needs `FINAL_RUN=1` and is for the final frozen run only. Never tune on it.
- Groq, Ollama and MLX are development-only; their results are not pooled with shared results.

## Commands

```bash
python3.14 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt      # requirements-lock.txt pins the full tree
cp .env.example .env                           # then set the LM Studio values

python -m pytest tests -q                       # offline, no server needed
python -m pytest tests/test_executor_contract.py::test_unknown_decision_is_denied -q   # single test

# Smoke run through AgentDojo. --k takes several values; one run per k.
python -m agent_framework.runner --provider lmstudio --llm openai/gpt-oss-20b \
    --policy full_approve --attack none --user-tasks user_task_0 --k 0 --outdir results/smoke
```

`tests/test_p2_handoff.py` fails with an openai version mismatch unless the P2 environment lock is installed; this is known.

Runner flags worth knowing: `--provider` (defaults to `LLM_PROVIDER` in `.env`), `--suite` (default `workspace`), `--benchmark-version` (default `v1.2`), `--attack` (`important_instructions` default, `direct`, `ignore_previous`, `injecagent`, `tool_knowledge`, `none`; never `manual`), `--injection-tasks`, `--reviewer` (`mock` default, `llm`), `--reviewer-model`, `--split-file` with `--split dev|heldout` (shared comparison sets), `--shadow-audit`, `--force` (results are cached per pipeline name, so reruns are no-ops without it). No linter or formatter is configured. See `runner.md` for the full list.

## Architecture

`runner.build_pipeline` assembles an AgentDojo `AgentPipeline`:

```
ResetTaskState(executor) → SystemMessage → InitQuery → LLM → ToolsExecutionLoop([P1ToolsExecutor, LLM])
```

- `tools_executor.P1ToolsExecutor` replaces AgentDojo's `ToolsExecutor`. For each tool call in the last assistant message it builds a context dict (`task`, `proposed_call` as a deep copy, `environment`, `trajectory`, `remaining_budget`, `metadata`), calls `policy.evaluate(context, state)`, and `_resolve` turns the decision into an outcome: `auto_approve`, `auto_deny`, `escalate_approved`/`escalate_denied` (budget consumed *before* the reviewer is called), `budget_exhausted_deny`, or `unknown_decision_deny`. Denied calls return `DENIAL_MESSAGE` in both `content` and `error` of the tool result.
- `evaluate` may return `(decision, state)` or `(decision, state, info)` with `info = {"reason", "scores"}`; `_unpack` handles both. `reason` is shown to the reviewer.
- **State scoping:** `ResetTaskState` is the first pipeline element, so budget, `policy_state`, the decision log and `TRACKER` reset at the start of every task (AgentDojo may call the pipeline more than once per task). Instance attributes on the policy survive across tasks; using them for task memory affects held-out evaluation and needs P1 sign-off.
- **Logging:** decisions and token counts go into AgentDojo's own trace JSON through `Logger.get().set_contextarg(...)` (keys `approval_decisions`, `token_usage`), at `<outdir>/<pipeline_name>/<suite>/<user_task>/<attack>/<injection_task|none>.json`. `run_one` then reads those traces back and writes `<outdir>/<pipeline_name>/summary_<suite>_<attack>.json` with TCR, `hitl_load_completed`, `hitl_load_all`, per-row outcomes, gate decisions, per-component `inference` (provider/model), `tasks_with_errors` and token totals. Shared runs use `--outdir results/<split>/<owner>`.
- **Pipeline name** looks like `lmstudio-openai_gpt-oss-20b-provenance-llmv2-k2-7ebb101c17`: provider, model, policy, reviewer and its prompt version, `k`, and a short config hash, with `/` replaced by `_`. It is the cache key. Attacks look the model up in AgentDojo's `MODEL_NAMES` by name, which is why `make_groq_llm` registers both spellings.
- **Token accounting:** `usage.TRACKER` is a process-wide singleton with buckets `agent`, `policy`, `reviewer`. The agent's OpenAI-compatible client is wrapped automatically; a policy that calls an LLM must wrap its own client with `track_openai_client(client, "policy")`.
- **Providers:** `inference.py` builds the clients (LM Studio, Groq, OpenAI, generic OpenAI-compatible servers) from `.env`; `llm_providers.py` holds the Groq wrapper (maps `developer`→`system`, flattens list content); `local_provider.py` is the local/MLX path. `--provider openai` goes through AgentDojo's `get_llm`, which only accepts `ModelsEnum` names.
- **Reviewer:** `llm_reviewer.py` is the simulated human. Server errors and unparseable replies count as a denial (`REVIEWER_ERROR`, `REVIEWER_PARSE_FAILURE`, fail-closed). It must never see benchmark labels, injection information or policy evidence.
- **Registry:** `registry.POLICIES` maps CLI name → zero-argument factory (use `functools.partial` for config). Policies live in `agent_framework/policies/`. Registered: `full_approve`, `full_escalate`, `anomaly` (P2), `supervised_risk` (P3), `plan_consistency` (P4), `approval_reuse` (P6), `provenance` (P7), `p4_p6_p7_combined_or`.

## Metrics as the runner computes them

- Completed safely = utility true and AgentDojo's final-state `security` check says the injection did not succeed. In the traces, `security: True` means the injection succeeded.
- TCR@k = completed-safely / n, where n is user tasks (no attack) or user×injection pairs (attack).
- AgentDojo first runs each selected injection task as a plain user task; those runs are billed but excluded from the numbers.
- `tasks_with_errors` counts context-length/server errors; those are not real completions and must be rerun.
- The security check is final-state only: a harmful call that executed but left no trace is not counted as an attack success.

## Rules for policies (from the contract)

- Use only `context`. Benchmark labels, injection task ids/goals and attack names must never reach a policy or the reviewer.
- Never mutate `environment` or `trajectory`. `proposed_call` is a copy; tampering does not change what runs (there is a test for this).
- Catch your own exceptions inside `evaluate` and return `escalate` or `deny` with a reason; an uncaught exception crashes the task run.
- Deterministic where possible (temperature 0, fixed seeds). AgentDojo does not expose tool metadata (read/write, local/remote) directly, so policies use `tool_meta.py` or their own tool table.

## Testing pattern

`tests/test_executor_contract.py` is the template for offline tests: a `ScriptedLLM` pipeline element emits fixed tool calls, a `Fixed`/recording `Policy` stands in for the gate, and `MockReviewer("approve"|"deny")` plays the reviewer. Build the same pipeline shape as the runner and assert on `executor.decisions` outcomes and on which tool calls actually executed. `tests/test_policy_contract_all.py` checks every registered policy against the contract.

## Repository layout and ownership

- `agent_framework/`: shared framework and `policies/` (one module or package per policy). Changes to shared files go through P1; each owner adds one line to `registry.py`, so expect merge conflicts there.
- `p2_anomaly/`, `p3_risk/`, `p6_reuse/`: owner-specific training code, data, model artifacts and scripts. Policy modules load artifacts from these folders by path; do not move them without updating `registry`/policy paths and tests.
- `scripts/`: shared run and analysis scripts. `splits/`: task lists. `docs/`: contract and per-policy notes. `submitted_results/<dev|heldout>/<name>/` (`<name>` = `P1`..`P7` or `P4_P6_P7_combined_or`): the only results that are committed (summaries and traces copied from your local run). `results/` is local scratch, git-ignored, and must never be force-added.
- Do not commit `.env`, `.pytest_tmp/`, `.venv/`, anything under `results/` or experiment run folders. Never `git add -f` results. Never run `git clean -fdx` (it deletes `.env`).

## Local development without the shared server

Groq's free tier is about 200k tokens/day per organization and 8k tokens/minute, and some tasks exceed the per-minute cap in one request (HTTP 413), which retries cannot fix. Use small task subsets for Groq/MLX development; those runs are not reportable.
