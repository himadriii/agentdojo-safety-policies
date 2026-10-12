class MockReviewer:

    def __init__(self):
        self.calls = 0

    def review(self, context):
        self.calls += 1

        print(
            f"[REVIEWER] Reviewing tool call: "
            f"#{self.calls}: {context['proposed_call'].function}"
        )

        return "approve"
