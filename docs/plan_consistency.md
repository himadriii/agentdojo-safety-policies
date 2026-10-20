# P4 Plan Consistency Policy

## Interface

The registered policy name is `plan_consistency`:

```bash
python -m agent_framework.runner --provider groq --policy plan_consistency \
  --llm openai/gpt-oss-20b --attack none --user-tasks user_task_0 \
  --k 0 1 2 --outdir results/p4
```

It implements the shared `Policy.evaluate(context, state)` contract and returns
`(decision, state, info)`. Decisions are `approve`, `deny`, or `escalate`;
`info` contains a short reviewer-facing reason and float scores. The P1 runner
owns budget enforcement and reviewer calls.

## Inputs and behavior

- Uses `context["task"]`, `context["proposed_call"].function`,
  `context["proposed_call"].args`, and prior assistant tool calls in
  `context["trajectory"]`.
- Does not inspect or mutate `environment`, benchmark labels, attack names, or
  tool outputs. Tool output text may contain attacker instructions, so it is
  intentionally excluded from the trajectory continuity features.
- Computes normalized lexical Dice relevance to the task and lexical support
  from earlier assistant tool calls. History alone cannot make an unrelated
  call approvable.
- Scores tool names and structured identifiers such as recipient, ID, and
  path. Free-text fields such as message bodies, subjects, and search queries
  do not contribute to relevance.
- Approves a task-relevant read-only call, regardless of domain. Unrelated or
  ambiguous reads escalate. Clearly unrelated destructive or other side-effect
  calls are denied; other uncertain calls escalate.
- A send requires an explicit send/email request and an email address present
  in both the task and call arguments. Names without an explicit address are
  not currently matched, so those sends will be denied or escalated.
- The run summary reports `auto_denials` and `budget_exhausted_denials`, with
  per-task counts in each result row. Compare `auto_denials` on clean runs to
  quantify false positives.
- Keeps no task-specific mutable state, so it returns the supplied state
  unchanged. The runner still resets state normally per task.

## Dependencies and configuration

No model or third-party dependency is used by this policy. The Groq model chosen
for the agent is independent of the gate. Defaults are `approve_threshold=0.16`
and `deny_threshold=0.02`; these are initial heuristic thresholds, not tuned
benchmark settings. The factory is zero-argument as required by the registry.

## Known limitations

This is a deterministic lexical/rule baseline, not semantic intent
understanding. Paraphrases, implicit authorization, recipient names without
email addresses, unusual tool names, and argument changes may be
misclassified. Tool names are not guaranteed to describe their true effects.
Evaluate clean and attacked runs and report false positives, false negatives,
auto-denials, review use, and latency. It cannot replace provenance or
argument-risk gates.

See [`docs/plan_consistency_dev_run.md`](plan_consistency_dev_run.md) for the
development fixtures and partial clean-task utility sample, including its
coverage limits and observed denial cases.
