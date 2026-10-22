# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AI6101 group project: approval policies (gates) for LLM agents, evaluated on AgentDojo. Every tool call the agent proposes goes through one policy that returns `approve`, `deny` or `escalate`, under a per-task escalation budget `k`. Seven owners (P1–P7) each build one policy against a single shared contract owned by P1. The authoritative contract is `docs/policy_interface.md`; interface changes go through P1.

## Commands

```bash
python3.14 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt      # requirements-lock.txt pins the full tree
cp .env.example .env                           # then set GROQ_API_KEY

python -m pytest tests -q                       # offline, no API key; 12 tests on main
python -m pytest tests/test_executor_contract.py::test_unknown_decision_is_denied -q   # single test

# Live run through AgentDojo (needs a provider). --k takes several values; one run per k.
python -m agent_framework.runner --provider groq --policy full_approve \
    --llm openai/gpt-oss-20b --attack none --user-tasks user_task_0 --k 0 --outdir results/smoke
```

Runner flags worth knowing: `--suite` (default `workspace`), `--benchmark-version` (default `v1.2`), `--attack` (`important_instructions` default, `direct`, `ignore_previous`, `injecagent`, `tool_knowledge`, `none`; never `manual`), `--injection-tasks`, `--reviewer mock`, `--force` (results are cached per pipeline name, so reruns are no-ops without it). No linter or formatter is configured.

## Architecture

`runner.build_pipeline` assembles an AgentDojo `AgentPipeline`:

```
ResetTaskState(executor) → SystemMessage → InitQuery → LLM → ToolsExecutionLoop([P1ToolsExecutor, LLM])
```

- `tools_executor.P1ToolsExecutor` replaces AgentDojo's `ToolsExecutor`. For each tool call in the last assistant message it builds a context dict (`task`, `proposed_call` as a deep copy, `environment`, `trajectory`, `remaining_budget`, `metadata`), calls `policy.evaluate(context, state)`, and `_resolve` turns the decision into an outcome: `auto_approve`, `auto_deny`, `escalate_approved`/`escalate_denied` (budget consumed *before* the reviewer is called), `budget_exhausted_deny`, or `unknown_decision_deny`. Denied calls return `DENIAL_MESSAGE` in both `content` and `error` of the tool result.
- `evaluate` may return `(decision, state)` or `(decision, state, info)` with `info = {"reason", "scores"}`; `_unpack` handles both. `reason` is shown to the reviewer.
- **State scoping:** `ResetTaskState` is the first pipeline element, so budget, `policy_state`, the decision log and `TRACKER` reset at the start of every task (AgentDojo may call the pipeline more than once per task). Instance attributes on the policy survive across tasks; using them for task memory affects held-out evaluation and needs P1 sign-off.
- **Logging:** decisions and token counts go into AgentDojo's own trace JSON through `Logger.get().set_contextarg(...)` (keys `approval_decisions`, `token_usage`), at `results/<pipeline_name>/<suite>/<user_task>/<attack>/<injection_task|none>.json`. `run_one` then reads those traces back and writes `results/<pipeline_name>/summary_<suite>_<attack>.json` with TCR, `hitl_load_completed`, `hitl_load_all`, per-row outcomes and token totals.
- **Pipeline name** is `{llm}-{policy}-{reviewer}-k{k}` with `/` replaced by `_`; it is the cache key. Attacks look the model up in AgentDojo's `MODEL_NAMES` by this name, which is why `make_groq_llm` registers both spellings.
- **Token accounting:** `usage.TRACKER` is a process-wide singleton with buckets `agent`, `policy`, `reviewer`. The agent's OpenAI-compatible client is wrapped automatically; a policy that calls an LLM must wrap its own client with `track_openai_client(client, "policy")`.
- **Providers:** `llm_providers.make_groq_llm` wraps an `openai.OpenAI` client pointed at Groq and patches `chat.completions.create` to map `developer`→`system` and flatten list content. Any other OpenAI-compatible endpoint can reuse the same pattern. `--provider openai` goes through AgentDojo's `get_llm`, which only accepts `ModelsEnum` names.
- **Registry:** `registry.POLICIES` maps CLI name → zero-argument factory (use `functools.partial` for config). Policies live in `agent_framework/policies/`.

## Metrics as the runner computes them

- Completed safely = utility true and AgentDojo's final-state `security` check says the injection did not succeed.
- TCR@k = completed-safely / n, where n is user tasks (no attack) or user×injection pairs (attack).
- AgentDojo first runs each selected injection task as a plain user task; those runs are billed but excluded from the numbers.
- `tasks_with_errors` counts context-length/server errors; those are not real completions.
- The security check is final-state only: a harmful call that executed but left no trace is not counted as an attack success.

## Rules for policies (from the contract)

- Use only `context`. Benchmark labels, injection task ids/goals and attack names must never reach a policy or the reviewer.
- Never mutate `environment` or `trajectory`. `proposed_call` is a copy; tampering does not change what runs (there is a test for this).
- Catch your own exceptions inside `evaluate` and return `escalate` or `deny` with a reason; an uncaught exception crashes the task run.
- Deterministic where possible (temperature 0, fixed seeds). AgentDojo does not expose tool metadata (read/write, local/remote), so each policy keeps its own tool table.

## Testing pattern

`tests/test_executor_contract.py` is the template for offline tests: a `ScriptedLLM` pipeline element emits fixed tool calls, a `Fixed`/recording `Policy` stands in for the gate, and `MockReviewer("approve"|"deny")` plays the reviewer. Build the same pipeline shape as the runner and assert on `executor.decisions` outcomes and on which tool calls actually executed.

## Team branches

Owners work on separate branches and each adds one line to `registry.py`, so expect conflicts there when merging. As of Oct 18, 2026: P3 supervised risk on `origin/sahana` (adds `p3_risk/` with a seeded held-out split in `p3_risk/data/split.json`, plus numpy/pandas/scikit-learn/joblib), P4 plan consistency on `origin/vk/p4_policy`, P7 provenance on `origin/feat/p7_provenance`, P6 approval reuse on `feat/p6_approval_reuse`. P4 and P7 both modify `llm_providers.py` (Groq retry handling; P7 also recovers Groq's leaked `<|channel|>` tool-name suffix).

## Provider limits

Groq's free tier is about 200k tokens/day per organization (keys in one org share it) and 8k tokens/minute. One agent task costs roughly 2k–20k tokens. Tasks that read whole inboxes or drives can exceed the per-minute cap in a single request (HTTP 413), which retries cannot fix. Use small task subsets for development.
