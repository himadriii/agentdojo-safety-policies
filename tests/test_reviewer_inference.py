"""Reviewer inference follows the selected endpoint and model."""
import json

import pytest

from agent_framework import runner
from agent_framework.usage import TRACKER
from tests.test_inference import completion, fake_server, isolated_settings, run_query, tool_message


@pytest.mark.parametrize("provider", ["lmstudio", "compatible", "groq", "openai"])
def test_llm_reviewer_uses_selected_provider_and_explicit_model(monkeypatch, provider):
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append((request.url.host, payload))
        if "tools" not in payload:
            return completion({"role": "assistant", "content": '{"decision":"approve","reason":"requested read"}'})
        return completion(tool_message() if len(requests) == 1 else {"role": "assistant", "content": "Done"})

    fake_server(monkeypatch, respond)
    pipeline = runner.build_pipeline("agent-model", "full_escalate", 'llm', 1, provider, reviewer_model="explicit-reviewer-model")
    assert run_query(pipeline) == ["invoice 42"]
    assert [p["model"] for _,p in requests] == ["agent-model", "explicit-reviewer-model", "agent-model"]
    assert len({host for host,_ in requests}) == 1
    assert pipeline.inference_config["reviewer"] == {"provider": provider, "model": "explicit-reviewer-model"}
    assert TRACKER.totals["reviewer"]["calls"] == 1


def test_reviewer_can_select_independent_hosted_route(monkeypatch):
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append((request.url.host, payload["model"]))
        if "tools" not in payload:
            return completion({"role": "assistant", "content": '{"decision":"approve","reason":"requested read"}'})
        return completion(tool_message() if len(requests) == 1 else {"role": "assistant", "content": "Done"})

    fake_server(monkeypatch, respond)
    monkeypatch.setenv("REVIEWER_PROVIDER", "compatible")
    monkeypatch.setenv("INFERENCE_MODEL", "hosted-reviewer")
    pipeline = runner.build_pipeline("local-agent", "full_escalate", 'llm', 1, "lmstudio")
    assert run_query(pipeline) == ["invoice 42"]
    assert requests == [("local.test", "local-agent"), ("production.test", "hosted-reviewer"), ("local.test", "local-agent")]
