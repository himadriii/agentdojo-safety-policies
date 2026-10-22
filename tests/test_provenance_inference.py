"""The agent and evidence extractor share the configured inference route."""
import json

import pytest

from agent_framework import runner
from agent_framework.usage import TRACKER
from tests.test_inference import completion, fake_server, isolated_settings, run_query, tool_message


@pytest.mark.parametrize("provider", ["lmstudio", "compatible", "groq", "openai"])
def test_provenance_uses_selected_model_and_current_schema(monkeypatch, provider):
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "response_format" in payload:
            if provider == "lmstudio":
                schema = payload["response_format"]["json_schema"]["schema"]
                assert schema["properties"]["edges"]["items"]["properties"]["transformation"]["type"] == ["object", "null"]
            return completion({"role": "assistant", "content": '{"edges": []}'})
        return completion(tool_message() if len(requests) == 1 else {"role": "assistant", "content": "Done"})

    fake_server(monkeypatch, respond)
    pipeline = runner.build_pipeline("selected-model", "provenance", "mock", 0, provider)
    assert run_query(pipeline) == ["invoice 42"]
    assert [r["model"] for r in requests] == ["selected-model"] * 3
    assert TRACKER.totals["policy"]["calls"] == 1


def test_local_agent_can_use_hosted_provenance_without_changing_agent_route(monkeypatch):
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append((request.url.host, payload["model"]))
        if "response_format" in payload:
            return completion({"role": "assistant", "content": '{"edges": []}'})
        return completion(tool_message() if len(requests) == 1 else {"role": "assistant", "content": "Done"})

    fake_server(monkeypatch, respond)
    monkeypatch.setenv("PROVENANCE_PROVIDER", "compatible")
    monkeypatch.setenv("INFERENCE_MODEL", "hosted-checker")
    pipeline = runner.build_pipeline("local-agent", "provenance", "mock", 0, "lmstudio")
    assert run_query(pipeline) == ["invoice 42"]
    assert requests == [("local.test", "local-agent"), ("production.test", "hosted-checker"), ("local.test", "local-agent")]


def test_combined_policy_configures_its_nested_provenance_gate(monkeypatch):
    fake_server(monkeypatch, lambda request: completion({"role": "assistant", "content": "Done"}))
    pipeline = runner.build_pipeline(
        "selected-model", "p4_p6_p7_combined_or", "mock", 2, "lmstudio"
    )
    combined = pipeline.elements[0].executor.policy
    assert combined.provenance.model == "selected-model"
    assert pipeline.inference_config["policy"] == {
        "provider": "lmstudio",
        "model": "selected-model",
    }
