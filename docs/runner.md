# Runner reference

`python -m agent_framework.runner` is the single entry point for running a policy on AgentDojo. For the shared team settings and the full dev and held-out procedure, see [`team_workflow.md`](team_workflow.md). For how the pipeline works, see [`architecture.md`](architecture.md). Run `python -m agent_framework.runner --help` for the authoritative list of flags.

## Setup

```bash
python3.14 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env        # edit it; never commit it
```

The runner reads the `.env` in the repository root. Command-line flags override `.env`; use `--env-file <path>` to pick another file.

## Providers

Choose with `--provider` or `LLM_PROVIDER` in `.env`. Reported results use `lmstudio` with `openai/gpt-oss-20b`.

| Provider | Settings in `.env` | Notes |
|---|---|---|
| `lmstudio` | `LMSTUDIO_MODEL`, `LMSTUDIO_BASE_URL`, optional `LMSTUDIO_API_KEY` | Model ID must match the server's `/v1/models`. Turn KV-cache quantization off. |
| `groq` | `GROQ_MODEL`, `GROQ_API_KEY` | Development only |
| `openai` | `OPENAI_MODEL`, `OPENAI_API_KEY`, optional `OPENAI_BASE_URL` | Development only |
| `compatible` | `INFERENCE_MODEL`, `INFERENCE_BASE_URL`, `INFERENCE_API_KEY` | Any OpenAI-compatible server (vLLM and similar) that supports `/chat/completions` and tool calling. Provenance also needs JSON output. |

The reviewer and the provenance policy follow the agent's provider and model unless `REVIEWER_PROVIDER`, `REVIEWER_MODEL`, `PROVENANCE_PROVIDER` or `PROVENANCE_MODEL` are set. Leave those unset for shared results. Timeouts, retries and token limits are the commented settings in `.env.example`. There is no silent fallback to a paid provider.

## Main flags

| Flag | Meaning |
|---|---|
| `--policy` | Policy name from `agent_framework/registry.py` (required) |
| `--reviewer` | `mock` (default), `mock_deny`, `llm`, `local_llm`. Use `llm` for results |
| `--llm` | Agent model ID; defaults to the provider's model in `.env` |
| `--reviewer-model` | Override the reviewer's model |
| `--suite` | `banking`, `slack`, `travel` or `workspace` (default `workspace`) |
| `--benchmark-version` | AgentDojo benchmark version (default `v1.2`) |
| `--attack` | `important_instructions` (default), `direct`, `ignore_previous`, `injecagent`, `tool_knowledge`, or `none` for benign runs |
| `--k` | One or more escalation budgets, one run per value |
| `--user-tasks`, `--injection-tasks` | Restrict to named tasks |
| `--split-file`, `--split dev\|heldout` | Run the shared task list from `splits/<suite>_v1.2.json`. `heldout` needs `FINAL_RUN=1` |
| `--with-benign` | After the attack run, also run the same user tasks with no attack |
| `--shadow-audit` | Log what the reviewer would say about each reuse approval (never enforced) |
| `--outdir` | Output folder (default `results`) |
| `--force` | Rerun even if a cached result exists |

## Examples

```bash
# one task, to check the setup
python -m agent_framework.runner --provider lmstudio --llm openai/gpt-oss-20b \
    --policy full_approve --attack none --user-tasks user_task_0 --k 0 --outdir results/smoke

# a policy with the LLM reviewer on one suite, no attack
python -m agent_framework.runner --provider lmstudio --policy approval_reuse --reviewer llm \
    --suite slack --attack none --user-tasks user_task_1 --k 2 --outdir results/smoke
```

For full runs use `scripts/team_settings.sh` (see the workflow page).

## Outputs

Everything is written under `--outdir/<pipeline name>/`:

- one trace JSON per task at `<suite>/<user_task>/<attack>/<injection_task|none>.json`, containing the gate decisions (`approval_decisions`) and token usage (`token_usage`);
- one `summary_<suite>_<attack>.json` per run: per-task rows, TCR, human-in-the-loop (HITL) load, token usage by component (agent, policy, reviewer), the models used, and `tasks_with_errors`.

Results are cached by pipeline name, which includes the provider, model, policy, reviewer prompt version, `k` and a config hash. A rerun is skipped unless `--force` is given. If the server drops mid-run, repeat the same command: finished tasks are skipped. Check a finished folder with `python scripts/check_summaries.py <folder>`.

Never commit `.env`, credentials or `results/`.
