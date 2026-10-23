# Dev submission: sahana (`supervised_risk`)

Command shape (see docs/merge_and_run_instructions.md section 8), run per suite on the dev split with k=2:

    python -m agent_framework.runner --provider lmstudio --policy supervised_risk --llm openai/gpt-oss-20b \
      --reviewer llm --reviewer-model openai/gpt-oss-20b --attack important_instructions \
      --split-file splits/<suite>_v1.2.json --split dev --k 2 --outdir results/dev/sahana

## Deviations from `scripts/team_settings.sh`

| Setting | Shared value | Used here | Reason |
|---|---|---|---|
| Provider | groq | lmstudio (served over ngrok) | Groq daily token cap exhausted for this account; instructed to use LM Studio |
| Reviewer model | openai/gpt-oss-120b | openai/gpt-oss-20b | the 120b model is not loaded on that server |

Agent model, reviewer type (`llm`, prompt v2), attack and k are as shared.

## Travel

13 of the 14 dev pairs finished. The LM Studio server returned HTTP 400 `RotatingKVCache Quantization NYI` on long conversations, which crashed the single-process run, so travel was rerun one (user task, injection task) pair at a time. Pair `user_task_18 | injection_task_0` fails on that server error every time and is absent (n=13). The runner overwrites its summary on every invocation, so `summary_travel_*.json` was rebuilt from the traces with `python -m p3_risk.summarize_traces results/dev/sahana`. The same script reproduces the runner's banking and Slack summaries exactly (rows, TCR, HITL).

## Trace verification

`scripts/verify_traces.py` globs only `*/workspace/*/*/*.json`, so it reports 0 traces for these suites. An identical copy with the glob widened to every suite checked 47 traces: 0 problems.
