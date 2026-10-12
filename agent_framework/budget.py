
class EscalationBudget:
    """Tracks the number of reviewer escalations allowed per task."""
    def __init__(self, limit: int = 2):
        if limit < 0:
            raise ValueError("Budget limit cannot be negative")

        self.limit = limit
        self.used = 0

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def consume(self) -> bool:
        """Consume one escalation if budget remains."""
        if self.remaining <= 0:
            return False

        self.used += 1
        return True

    def reset(self) -> None:
        """Reset the budget for a new task."""
        self.used = 0
