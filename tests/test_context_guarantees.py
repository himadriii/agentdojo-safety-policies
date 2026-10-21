from agent_framework.policy import Policy
from tests.test_executor_contract import build, run

def test_context_has_documented_keys_and_isolated_fields():
    seen, junk_at_entry = [], []

    class Probe(Policy):
        def evaluate(self, context, state):
            seen.append(context)
            junk_at_entry.append("junk" in context["metadata"])   # check BEFORE mutating
            context["metadata"]["junk"] = 1
            context["trajectory"].clear()
            return "approve", state

    pipeline, _ = build(Probe(), queries=("a", "b"))
    messages = run(pipeline)
    assert set(seen[0]) == {"task", "proposed_call", "environment", "trajectory",
                            "remaining_budget", "metadata", "tools"}
    assert "search_emails" in seen[0]["tools"]
    assert "description" in seen[0]["tools"]["search_emails"]
    assert set(seen[0]["metadata"]) >= {"step", "decision_history", "tool"}
    assert junk_at_entry == [False, False]        # nothing leaked from call 0 into call 1
    assert len(messages) >= 5                     # clearing the trajectory didn't corrupt the agent
