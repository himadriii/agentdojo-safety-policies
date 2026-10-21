"""Shadow-audit executor: measures what reuse lets through that the reviewer would have refused.

An approve-all reviewer cannot expose reuse leaks, because the gate only ever swaps a
reviewer round-trip for an earlier verdict. The leak test is the opposite question: for every
call the gate approves from memory, what would the reviewer have said? The shadow review is
logged and never enforced, and it spends no escalation budget, so runs stay comparable with
the unaudited ones. Evaluation harness only; policies and the reviewer never see the audit.
"""
import logging

from agentdojo.logging import Logger

from agent_framework.reviewer import build_reviewer_context
from agent_framework.tools_executor import P1ToolsExecutor

log = logging.getLogger(__name__)


class ShadowAuditExecutor(P1ToolsExecutor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shadow_log = []

    def reset_for_new_task(self):
        super().reset_for_new_task()
        self.shadow_log = []

    def _resolve(self, decision, context, info):
        outcome, approved, reviewer_called = super()._resolve(decision, context, info)
        if outcome == "auto_approve" and (info.get("scores") or {}).get("reuse_approved"):
            self._shadow_review(context, info)
        return outcome, approved, reviewer_called

    def _shadow_review(self, context, info):
        call = context["proposed_call"]
        try:
            verdict = self.reviewer.review(build_reviewer_context(
                context["task"], call, context["trajectory"], info.get("reason")))
        except Exception as exc:  # an audit failure must never change the run
            log.warning("[shadow] review failed: %r", exc)
            verdict = "error"
        self.shadow_log.append({"tool": call.function, "args": dict(call.args), "shadow_verdict": verdict})
        trace_logger = Logger.get()
        if hasattr(trace_logger, "set_contextarg"):  # NullLogger has no such method
            trace_logger.set_contextarg("reuse_shadow", self.shadow_log)
