"""P3 + URL guard: the frozen supervised risk model plus one deterministic rule for get_webpage.

The risk model scores a read-only web fetch as harmless, so an injected "visit this link" slips
through. The rule denies a get_webpage call whose URL the user never wrote and that only appears
inside instruction-like text of earlier tool output (or nowhere in the visible context).
Every other call is decided by SupervisedRiskPolicy unchanged. No LLM calls.
"""
import re

from agent_framework.policies.risk_features import _injection_span, _text
from agent_framework.policies.supervised_risk import SupervisedRiskPolicy


def _norm(url):
    return re.sub(r"^https?://", "", str(url)).strip().rstrip("/").lower()


class SupervisedRiskURLGuardPolicy(SupervisedRiskPolicy):
    name = "supervised_risk_urlguard"

    def evaluate(self, context, state):
        call = context["proposed_call"]
        if call.function == "get_webpage":
            try:
                reason = self._untrusted_url(context, call)
            except Exception:  # fall back to the plain risk model
                reason = None
            if reason:
                return "deny", state, {"reason": reason}
        return super().evaluate(context, state)

    @staticmethod
    def _untrusted_url(context, call):
        url = _norm(call.args.get("url", ""))
        if not url or url in str(context.get("task", "")).lower():
            return None
        in_span = in_clean = False
        for m in context.get("trajectory", []):
            if m.get("role") != "tool":
                continue
            span, clean, _ = _injection_span(_text(m))
            in_span |= url in span.lower()
            in_clean |= url in clean.lower()
        if in_span or not in_clean:
            return f"URL {url} was not given by the user and comes from instruction-like tool output"
        return None
