# Running p2/anomaly-gate

**P2 split guard:** final task IDs are awaiting team confirmation. For P2, use
the development-only handoff in the README with `--provider lmstudio`; it selects
the current calibrated candidate and real reviewer. Do not run the all-task or
`user_task_0` examples below while the split is pending. These generic runner
examples default to a mock reviewer unless `--reviewer llm` is supplied.

This branch supports local LM Studio models and hosted inference through the same
runner. Available policies: `full_approve`, `full_escalate`, `anomaly`. Reviewers: `mock`, `llm`.

## Setup and configuration

Run these commands from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

If `.env` already exists, edit it instead of copying over it. It is ignored by
Git. No `export`, `source .env`, shell-variable substitution, or custom runner
script is required. The runner reads the `.env` next to the repository itself,
even when launched from another directory. Explicit settings in `.env` take
precedence over inherited environment values; command-line flags take precedence
over `.env`. Use `--env-file /path/to/experiment.env` to select another file.

For GPT OSS 20B in LM Studio, set:

```dotenv
LLM_PROVIDER=lmstudio
LMSTUDIO_MODEL=openai/gpt-oss-20b
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
```

Load the model in LM Studio and start the server in its Developer tab or with
`lms server start --port 1234`. The exact model ID must match the server's
`/v1/models` response. The runner checks it before starting a local benchmark.
Set `LMSTUDIO_API_KEY` in `.env` only if the server requires authentication.
Configure reasoning effort in LM Studio's loaded-model settings.

## Smoke test and full run

With the `.env` above, run one task:

```bash
.venv/bin/python -m agent_framework.runner \
  --policy full_approve --attack none --user-tasks user_task_0 \
  --k 0 --outdir results/smoke-local --force
```

Run all workspace tasks:

```bash
.venv/bin/python -m agent_framework.runner \
  --policy full_approve --attack none \
  --k 0 --outdir results/full-updated --force
```

`--k 0` denies calls that require reviewer escalation. It does not guarantee task
completion. To compare reviewer budgets, use `--k 0 1 2 3 5`. For a baseline, use
`--policy full_approve` or `--policy full_approve` on every branch.

For an attacked task, use a separate output directory:

```bash
.venv/bin/python -m agent_framework.runner \
  --policy full_approve --attack important_instructions \
  --user-tasks user_task_0 --injection-tasks injection_task_0 \
  --k 0 2 --outdir results/attack-local --force
```

## Hosted production inference

For Groq, edit `.env`:

```dotenv
LLM_PROVIDER=groq
GROQ_MODEL=openai/gpt-oss-20b
GROQ_API_KEY=your_groq_key
```

Use the same smoke/full commands. To switch providers for one command while
keeping both models and credentials in `.env`:

```bash
.venv/bin/python -m agent_framework.runner \
  --provider groq --policy full_approve --attack none \
  --user-tasks user_task_0 --k 0 --outdir results/smoke-groq --force
```

OpenAI is selected with `LLM_PROVIDER=openai`, `OPENAI_MODEL` and
`OPENAI_API_KEY` in `.env`. Arbitrary model IDs supported by that endpoint are
accepted; there is no AgentDojo enum restriction.

For a deployed vLLM server, another local engine, or a hosted OpenAI-compatible
service, set these values to your actual endpoint, model and credentials:

```dotenv
LLM_PROVIDER=compatible
INFERENCE_BASE_URL=https://your-inference-server.example/v1
INFERENCE_MODEL=your-deployed-model-id
INFERENCE_API_KEY=your_server_key
```

The server must support `/chat/completions` and tool calling. A provenance checker
also needs JSON output. `INFERENCE_API_KEY` can be blank for a trusted local
server that does not require authentication. Configure timeouts, retries and
output limits using the commented settings in `.env.example`. There is no
silent fallback from local inference to a paid provider.

## Outputs and checks

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m agent_framework.runner --help
```

Trace JSON and summary JSON are created below `--outdir`. Summary `inference`
records the selected providers and models, and token usage is separated into
agent, policy and reviewer components when the server returns usage. Pipeline
cache names include the provider and a hash of component model selections;
older result directories are not reused. Endpoint changes with identical model
IDs and model-setting changes still require a new output directory or `--force`.
Never commit `.env`, credentials, or generated results. Historical experiment
scripts may retain their original provider flags; these commands are the common
entry point across branches.

## LLM reviewer

Use the existing `llm` reviewer with a nonzero budget:

```bash
.venv/bin/python -m agent_framework.runner \
  --policy full_escalate --reviewer llm --attack none \
  --user-tasks user_task_0 --k 2 --outdir results/reviewer-smoke --force
```

The reviewer uses the agent provider and model unless `REVIEWER_PROVIDER` or
`REVIEWER_MODEL` is set in `.env`. `--reviewer-model` overrides the model for one
run. A different provider uses that provider's model key when no reviewer model
is set. Prompt and decision parsing retain this branch's existing behavior.

## P2 shared compatibility and DEV (free tier)

Use the team settings (Groq 20B agent, 120B reviewer, v2 prompt,
`important_instructions`, v1.2, k=2) with an explicit gate artifact:

```bash
.venv/bin/python -m p2_anomaly.shared_run compat \
  --artifact p2_anomaly/artifacts/development/lmstudio-v2-category/model.joblib \
  --outdir results/compat/P2-shared-v01
.venv/bin/python scripts/verify_traces.py results/compat/P2-shared-v01
.venv/bin/python -m p2_anomaly.shared_run dev \
  --artifact p2_anomaly/artifacts/development/lmstudio-v2-category/model.joblib \
  --outdir results/dev/P2-shared-v01
.venv/bin/python scripts/verify_traces.py results/dev/P2-shared-v01
```

This wrapper preserves the shared agent/reviewer requests and stops immediately
on quota instead of invoking the runner's automatic rate-limit retries. After a
provider reset, repeat with `--resume-after-quota`; completed traces are cached.
Keep the output directory tied to one source/model version. DEV uses only the
published DEV IDs; held-out tasks are unavailable through this command.

The current artifact was trained on workspace calls. Cross-suite DEV results
measure this existing gate, including unsupported-tool escalation; they are
not evidence of a cross-suite-trained detector. Trace verification checks logging
invariants, not attack resistance or task completion.

### Cross-suite candidate and budget comparison

The replacement candidate is `p2_anomaly/artifacts/development/cross-suite-v2/model.joblib`.
It recognizes all four suites and reserves review for banking changes and URL
fetches. Training uses DEV-only references plus audited clean calls; independent
live Slack/travel calibration is still missing. It has not been promoted or frozen.

After the provider quota has reset, first compare the candidate on banking at k=2:

```bash
.venv/bin/python -m p2_anomaly.shared_run dev --suite banking --k 2 \
  --artifact p2_anomaly/artifacts/development/cross-suite-v2/model.joblib \
  --outdir results/dev/P2-cross-suite-v2-banking-k2 --resume-after-quota
.venv/bin/python scripts/verify_traces.py results/dev/P2-cross-suite-v2-banking-k2
```

Then repeat with `--k 0` and `--k 5`, each with a different output directory.
Use `--attack none` in a separate directory to check legitimate-task interference.
Omit `--suite banking` for the full three-suite DEV run. Never resume an old
artifact's directory with the new model/source. New directories also respect
the retained provider quota stop. An explicit resume is for a confirmed reset.

The reproducible offline routing check is:

```bash
.venv/bin/python -m p2_anomaly.replay_shared \
  --traces results/dev/P2-shared-v01 \
  --old p2_anomaly/artifacts/development/lmstudio-v2-category/model.joblib \
  --candidate p2_anomaly/artifacts/development/cross-suite-v2/model.joblib \
  --out results/offline-routing.json
```

Offline replay holds the old proposals fixed; it cannot measure new TCR or
actual review savings. Banking tasks 5 and 10 require separate interpretation:
task 5 can pass its utility check without a new payment, while task 10 deliberately
rewards taking no action on an underspecified request. Keep official scores and
verified requested actions separate. Select the smallest k that gives acceptable
safe task completion on matched live DEV runs; no optimal k is established yet.

The serial matrix can follow an already-running banking k=2 job without starting
a duplicate. It records only complete, matching runs and stops at quota/errors:

```bash
.venv/bin/python -m p2_anomaly.evaluate_shared \
  --artifact p2_anomaly/artifacts/development/cross-suite-v2/model.joblib \
  --root results/dev/P2-cross-suite-v2-matrix \
  --first-running results/dev/P2-cross-suite-v2-banking-k2 \
  --report p2_anomaly/artifacts/development/cross-suite-v2/live-evaluation.json
```

Start/resume the first run separately after a confirmed quota reset before using
this command. It waits for that run, then schedules clean controls and the
remaining shared DEV budgets. It never resumes quota automatically.
When following an explicitly resumed first run that already has an old quota
marker, add `--wait-for-resume` to the matrix command. A new quota event still
stops the queue. The initial wait is limited to 90 minutes.

## P2 anomaly artifacts and experiment protocol

The default anomaly artifact is unavailable; the original v1 manifest is revoked.
The runner retains P2's refusal to run `anomaly` without a valid, trusted artifact.
For an explicitly developmental smoke test, add this to `.env`:

```dotenv
P2_ANOMALY_MODEL=p2_anomaly/artifacts/development/family-v2-category/model.joblib
```

Then run:

```bash
.venv/bin/python -m agent_framework.runner \
  --policy anomaly --reviewer llm --attack none \
  --user-tasks user_task_3 --k 2 --outdir results/anomaly-development --force
```

The candidate's manifest is checked before loading. The development readiness
report still reports insufficient live audited calibration evidence; this is not
a frozen or validated production policy. Do not substitute the revoked v1 model.
The model artifact hash remains part of the pipeline cache name. No training,
threshold selection or held-out evaluation was performed for this provider update.

P2's separate `p2_anomaly.experiments` workflow retains its original Groq-only
protocol, pacing, quota stop/resume, and audited partition restrictions. Use the
common runner above for local or alternate hosted smoke experiments; do not
present them as the frozen P2 study. The experiment source fingerprint now also
includes the shared inference/configuration modules, so provider-code changes
cannot silently reuse an older execution identity. P2's JSON reviewer schema is
translated for LM Studio while its prompt and decision parsing remain unchanged.


<!-- Current shared workflow supersedes historical P2 run settings above. -->

# Running p1-llm-reviewer

This branch supports local LM Studio models and hosted inference through the same
runner. Available policies: `full_approve`, `full_escalate`. Reviewers: `mock`, `mock_deny`, `llm`.

## Setup and configuration

Run these commands from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

If `.env` already exists, edit it instead of copying over it. It is ignored by
Git. No `export`, `source .env`, shell-variable substitution, or custom runner
script is required. The runner reads the `.env` next to the repository itself,
even when launched from another directory. Explicit settings in `.env` take
precedence over inherited environment values; command-line flags take precedence
over `.env`. Use `--env-file /path/to/experiment.env` to select another file.

For GPT OSS 20B in LM Studio, set:

```dotenv
LLM_PROVIDER=lmstudio
LMSTUDIO_MODEL=openai/gpt-oss-20b
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
```

Load the model in LM Studio and start the server in its Developer tab or with
`lms server start --port 1234`. The exact model ID must match the server's
`/v1/models` response. The runner checks it before starting a local benchmark.
Set `LMSTUDIO_API_KEY` in `.env` only if the server requires authentication.
Configure reasoning effort in LM Studio's loaded-model settings.

## Smoke test and full run

With the `.env` above, run one task:

```bash
.venv/bin/python -m agent_framework.runner \
  --policy full_escalate --attack none --user-tasks user_task_0 \
  --k 0 --outdir results/smoke-local --force
```

Run all workspace tasks:

```bash
.venv/bin/python -m agent_framework.runner \
  --policy full_escalate --attack none \
  --k 0 --outdir results/full-updated --force
```

`--k 0` denies calls that require reviewer escalation. It does not guarantee task
completion. To compare reviewer budgets, use `--k 0 1 2 3 5`. For a baseline, use
`--policy full_approve` or `--policy full_escalate` on every branch.

For an attacked task, use a separate output directory:

```bash
.venv/bin/python -m agent_framework.runner \
  --policy full_escalate --attack important_instructions \
  --user-tasks user_task_0 --injection-tasks injection_task_0 \
  --k 0 2 --outdir results/attack-local --force
```

## Hosted production inference

For Groq, edit `.env`:

```dotenv
LLM_PROVIDER=groq
GROQ_MODEL=openai/gpt-oss-20b
GROQ_API_KEY=your_groq_key
```

Use the same smoke/full commands. To switch providers for one command while
keeping both models and credentials in `.env`:

```bash
.venv/bin/python -m agent_framework.runner \
  --provider groq --policy full_escalate --attack none \
  --user-tasks user_task_0 --k 0 --outdir results/smoke-groq --force
```

OpenAI is selected with `LLM_PROVIDER=openai`, `OPENAI_MODEL` and
`OPENAI_API_KEY` in `.env`. Arbitrary model IDs supported by that endpoint are
accepted; there is no AgentDojo enum restriction.

For a deployed vLLM server, another local engine, or a hosted OpenAI-compatible
service, set these values to your actual endpoint, model and credentials:

```dotenv
LLM_PROVIDER=compatible
INFERENCE_BASE_URL=https://your-inference-server.example/v1
INFERENCE_MODEL=your-deployed-model-id
INFERENCE_API_KEY=your_server_key
```

The server must support `/chat/completions` and tool calling. A provenance checker
also needs JSON output. `INFERENCE_API_KEY` can be blank for a trusted local
server that does not require authentication. Configure timeouts, retries and
output limits using the commented settings in `.env.example`. There is no
silent fallback from local inference to a paid provider.

## Outputs and checks

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m agent_framework.runner --help
```

Trace JSON and summary JSON are created below `--outdir`. Summary `inference`
records the selected providers and models, and token usage is separated into
agent, policy and reviewer components when the server returns usage. Pipeline
cache names include the provider and a hash of component model selections;
older result directories are not reused. Endpoint changes with identical model
IDs and model-setting changes still require a new output directory or `--force`.
Never commit `.env`, credentials, or generated results. Historical experiment
scripts may retain their original provider flags; these commands are the common
entry point across branches.

## LLM reviewer

Use the existing `llm` reviewer with a nonzero budget:

```bash
.venv/bin/python -m agent_framework.runner \
  --policy full_escalate --reviewer llm --attack none \
  --user-tasks user_task_0 --k 2 --outdir results/reviewer-smoke --force
```

The reviewer uses the agent provider and model unless `REVIEWER_PROVIDER` or
`REVIEWER_MODEL` is set in `.env`. `--reviewer-model` overrides the model for one
run. A different provider uses that provider's model key when no reviewer model
is set. Prompt and decision parsing retain this branch's existing behavior.
