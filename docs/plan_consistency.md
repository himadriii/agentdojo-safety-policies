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
- Recognizes date/event-related calendar reads, including common prerequisite
  calls such as `get_current_day` and `get_day_calendar_events`, to avoid using
  the escalation budget for those lookups.
- Escalates an unrequested side effect when it is plausibly task-related and an
  explicitly changed email recipient. Denies clearly unrelated destructive or
  other side-effect calls. Other uncertain calls escalate; relevant calls can
  be approved.
- Keeps no task-specific mutable state, so it returns the supplied state
  unchanged. The runner still resets state normally per task.

## Dependencies and configuration

No model or third-party dependency is used by this policy. The Groq model chosen
for the agent is independent of the gate. Defaults are `approve_threshold=0.16`
and `deny_threshold=0.02`; these are initial heuristic thresholds, not tuned
benchmark settings. The factory is zero-argument as required by the registry.

The Groq adapter retries failed API requests up to 3 times by default. Set
`GROQ_MAX_RETRIES` in the environment to change this cap. This bounds retry
delays; it does not prevent HTTP 429 rate limits.

## Known limitations

This is a deterministic lexical/rule baseline, not semantic intent
understanding. Paraphrases, implicit authorization, unusual tool names, and
argument changes beyond explicit email recipients may be misclassified. Tool
names are not guaranteed to describe their true effects. The policy should be
evaluated on clean and attacked AgentDojo runs, with false positives, false
negatives, review use, and latency reported. It cannot replace provenance or
argument-risk gates.
