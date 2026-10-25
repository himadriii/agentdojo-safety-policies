"""P3 + guards v2: URL guard plus a reservation guard for the travel suite.

On top of SupervisedRiskURLGuardPolicy, a reserve_* call is denied when
  - the hotel / car company / restaurant it books is not named in the user's task, and
  - earlier tool output contained instruction-like text (the injection cue patterns P3 already uses).
Without any instruction-like text in the context the call goes to the frozen risk model as before.
Why: the risk model gives a booking a low score when the user's task also talks about booking
(for example "recommend a hotel to book"), even though the user never asked for a reservation.
"""
from agent_framework.policies.risk_features import _injection_span, _text
from agent_framework.policies.supervised_risk_urlguard import SupervisedRiskURLGuardPolicy

RESERVE_ARG = {"reserve_hotel": "hotel", "reserve_car_rental": "company",
               "reserve_restaurant_at_given_time": "restaurant"}


class SupervisedRiskGuardPolicy(SupervisedRiskURLGuardPolicy):
    name = "supervised_risk_guard"

    def evaluate(self, context, state):
        call = context["proposed_call"]
        arg = RESERVE_ARG.get(call.function)
        if arg:
            try:
                reason = self._unrequested_booking(context, str(call.args.get(arg, "")).strip().lower())
            except Exception:  # fall back to the URL guard / risk model
                reason = None
            if reason:
                return "deny", state, {"reason": reason}
        return super().evaluate(context, state)

    @staticmethod
    def _unrequested_booking(context, target):
        if not target or target in str(context.get("task", "")).lower():
            return None
        if any(_injection_span(_text(m))[2] for m in context.get("trajectory", []) if m.get("role") == "tool"):
            return f"booking '{target}' was not named by the user and tool output contained instruction-like text"
        return None
