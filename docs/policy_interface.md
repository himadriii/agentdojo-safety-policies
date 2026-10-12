# Shared Policy Interface — P1 AgentDojo

## 1. Purpose

All approval policies must implement a common interface so that the P1 AgentDojo runner can evaluate them without depending on their internal implementation.

The interface supports rule-based, anomaly-based, supervised, plan-consistency, approval-memory, and provenance-based policies.

## 2. Required interface

```python
decision, updated_state = policy.evaluate(context, state)
```

- `context`: Information available when evaluating the proposed tool call.
- `state`: Policy-specific state for the current task.
- `decision`: One of `"approve"`, `"deny"`, or `"escalate"`.
- `updated_state`: Updated state to pass into the next evaluation within the same task.

## 3. Context fields

| Field | Type | Description |
|---|---|---|
| `proposed_call` | AgentDojo tool-call object | Requested tool and arguments |
| `trajectory` | Sequence of messages | Conversation and preceding tool-call history |
| `environment` | AgentDojo environment | Current task environment |
| `metadata` | Dictionary | Additional available task/tool metadata |
| `remaining_budget` | Integer | Escalations remaining |
| `task` | Task description, when available | User's objective and task context |

Policies must use only information available at decision time. Benchmark ground-truth labels and attack annotations must not be exposed to the policy or simulated reviewer.

## 4. Decision semantics

- **approve:** The runner may execute the proposed tool call.
- **deny:** The runner must not execute the proposed tool call.
- **escalate:** The runner sends the call and relevant context to the reviewer, subject to the escalation budget.

If the escalation budget is exhausted, the runner denies the escalation-worthy call without invoking the reviewer.

The policy recommends a decision; the shared runner is responsible for enforcing it.

## 5. State handling

Each task starts with fresh policy state.

The runner passes the state returned by one evaluation into the next evaluation within that task. State must not leak between unrelated tasks.

Stateless policies may return the state unchanged.

## 6. Sample input

The following is illustrative pseudocode. The real `proposed_call` should be an AgentDojo tool-call object.

```python
context = {
    "task": "Find the user's latest flight email.",
    "proposed_call": {
        "function": "search_emails",
        "args": {"query": "flight"},
    },
    "trajectory": [],
    "environment": None,
    "metadata": {"task_id": "sample_task"},
    "remaining_budget": 2,
}

state = {}
```

## 7. Sample output

```python
decision = "escalate"
updated_state = state
```

This is an example of the output format, not a claim that every policy should escalate this call. The policy implementation determines the actual decision.

## 8. Implementation requirements

Every policy owner should provide:

1. A callable implementation of `evaluate(context, state)`.
2. A sample input and output.
3. Required features, dependencies, thresholds, or configuration.
4. Known limitations and representative failure cases.
5. An explanation of what the policy catches, what legitimate calls it may block, and what unsafe calls it may miss.

A placeholder implementation is acceptable for initial interface integration.
