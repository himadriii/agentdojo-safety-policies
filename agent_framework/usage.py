"""Token accounting per component, written into AgentDojo's per-task trace JSON."""
from agentdojo.logging import Logger

COMPONENTS = ("agent", "policy", "reviewer")


class UsageTracker:
    def __init__(self):
        self.lifetime = {c: {"calls": 0, "input_tokens": 0, "output_tokens": 0} for c in COMPONENTS}
        self.reset()

    def reset(self):
        self.totals = {c: {"calls": 0, "input_tokens": 0, "output_tokens": 0} for c in COMPONENTS}

    def add(self, component, input_tokens, output_tokens):
        t = self.totals[component]
        t["calls"] += 1
        t["input_tokens"] += input_tokens or 0
        t["output_tokens"] += output_tokens or 0
        lifetime = self.lifetime[component]
        lifetime['calls'] += 1
        lifetime['input_tokens'] += input_tokens or 0
        lifetime['output_tokens'] += output_tokens or 0
        log = Logger.get()
        if hasattr(log, "set_contextarg"):  # NullLogger has no such method
            log.set_contextarg("token_usage", self.totals)


TRACKER = UsageTracker()  # shared singleton, reset at the start of every task


def track_openai_client(client, component):
    """Wrap client.chat.completions.create so every call's usage is recorded.

    component is one of: "agent", "policy", "reviewer".
    Policies/reviewers that call an LLM should wrap their own client with this.
    """
    completions = client.chat.completions
    if getattr(completions, "_tracked_component", None) is not None:
        return client
    original = completions.create

    def create(*args, **kwargs):
        response = original(*args, **kwargs)
        usage = getattr(response, "usage", None)
        if usage is not None:
            TRACKER.add(component, usage.prompt_tokens, usage.completion_tokens)
        return response

    completions.create = create
    completions._tracked_component = component
    return client
