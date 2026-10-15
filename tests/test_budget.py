from agent_framework.budget import EscalationBudget

def test_budget_reset():
    budget = EscalationBudget(limit=2)

    assert budget.consume()
    assert budget.consume()
    assert budget.remaining == 0

    budget.reset()

    assert budget.used == 0
    assert budget.remaining == 2

    print("PASS: budget resets for a new task")


if __name__ == "__main__":
    test_budget_reset()
