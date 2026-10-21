"""Common .env and provider integration checks; no live services or real keys."""
import json
import os
from pathlib import Path

import httpx2
import pytest
from agentdojo.functions_runtime import FunctionsRuntime, make_function

from agent_framework import inference, runner, runner_config
from agent_framework.usage import TRACKER


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("LLM_", "LMSTUDIO_", "GROQ_", "OPENAI_", "INFERENCE_", "REVIEWER_", "PROVENANCE_", "MLX_")):
            monkeypatch.delenv(key)


def fake_server(monkeypatch, handler):
    original = inference.openai.OpenAI
    monkeypatch.setattr(inference.openai, "OpenAI", lambda **kwargs: original(
        **kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    ))
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://local.test/v1")
    monkeypatch.setenv("INFERENCE_BASE_URL", "https://production.test/v1")
    monkeypatch.setenv("INFERENCE_API_KEY", "test-production-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")


def completion(message):
    return httpx2.Response(200, json={
        "id": "completion-test", "object": "chat.completion", "created": 0, "model": "test-model",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    })


def tool_message():
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": "call_1", "type": "function",
        "function": {"name": "search_emails", "arguments": '{"query":"invoice 42"}'},
    }]}


def run_query(pipeline):
    executed = []

    def search_emails(query: str) -> str:
        """Search emails.

        :param query: Search text.
        """
        executed.append(query)
        return "Invoice 42"

    pipeline.query(query="Search emails for invoice 42.", runtime=FunctionsRuntime(functions=[make_function(search_emails)]))
    return executed


@pytest.mark.parametrize("provider,host", [
    ("lmstudio", "local.test"), ("compatible", "production.test"),
    ("groq", "api.groq.com"), ("openai", "api.openai.com"),
])
def test_agent_tool_loop_and_usage_for_each_provider(monkeypatch, provider, host):
    requests = []

    def respond(request):
        assert request.url.host == host
        requests.append(json.loads(request.content))
        return completion(tool_message() if len(requests) == 1 else {"role": "assistant", "content": "Done"})

    fake_server(monkeypatch, respond)
    pipeline = runner.build_pipeline("test/custom-model", "full_approve", "mock", 0, provider)
    assert run_query(pipeline) == ["invoice 42"]
    assert all(r["model"] == "test/custom-model" for r in requests)
    if provider in ("lmstudio", "compatible"):
        assert requests[0]["messages"][0]["role"] == "system"
        assert requests[0]["temperature"] == 0
        assert requests[0]["max_tokens"] == 4096
        assert all(isinstance(m["content"], str) for r in requests for m in r["messages"])
    assert TRACKER.totals["agent"] == {"calls": 2, "input_tokens": 20, "output_tokens": 10}
    assert pipeline.inference_config["agent"] == {"provider": provider, "model": "test/custom-model"}
    assert pipeline.name.startswith(provider + "-")


@pytest.mark.parametrize("provider", ["lmstudio", "compatible"])
def test_token_translation_preserves_explicit_limit(monkeypatch, provider):
    requests = []
    fake_server(monkeypatch, lambda r: requests.append(json.loads(r.content)) or completion({"role": "assistant", "content": "Done"}))
    client = inference.make_inference_client(provider)
    client.chat.completions.create(model="m", messages=[], max_completion_tokens=123, reasoning_effort="low")
    assert requests[0]["max_tokens"] == 123
    assert "max_completion_tokens" not in requests[0]
    assert "reasoning_effort" not in requests[0]


def test_cli_reads_repository_env_without_shell_exports(monkeypatch, tmp_path):
    (tmp_path / '.env').write_text('LLM_PROVIDER=lmstudio\nLMSTUDIO_MODEL=local-from-file\n')
    monkeypatch.setattr(runner_config, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("LMSTUDIO_MODEL", "inherited-value")
    monkeypatch.setattr("sys.argv", ["runner", "--policy", "full_approve", "--k", "0"])
    checked, runs = [], []
    monkeypatch.setattr(runner_config, "check_local_models", lambda models: checked.extend(models))
    monkeypatch.setattr(runner, "run_one", lambda args, k: runs.append((args.provider, args.llm, k)))
    runner.main()
    assert checked == ["local-from-file"]
    assert runs == [("lmstudio", "local-from-file", 0)]


def test_cli_overrides_env_and_accepts_explicit_env_file(monkeypatch, tmp_path):
    env = tmp_path / 'experiment.env'
    env.write_text('LLM_PROVIDER=lmstudio\nLMSTUDIO_MODEL=local-model\nGROQ_MODEL=hosted-model\n')
    monkeypatch.setattr("sys.argv", ["runner", "--env-file", str(env), "--provider", "groq", "--llm", "override-model", "--policy", "full_approve", "--k", "0"])
    checked, runs = [], []
    monkeypatch.setattr(runner_config, "check_local_models", lambda models: checked.extend(models))
    monkeypatch.setattr(runner, "run_one", lambda args, k: runs.append((args.provider, args.llm)))
    runner.main()
    assert checked == []
    assert runs == [("groq", "override-model")]


def test_missing_model_is_actionable(monkeypatch, tmp_path, capsys):
    (tmp_path / '.env').write_text('LLM_PROVIDER=lmstudio\n')
    monkeypatch.setattr(runner_config, "REPO_ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["runner", "--policy", "full_approve"])
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
    assert 'Set LMSTUDIO_MODEL in .env' in capsys.readouterr().err


def test_unknown_provider_from_env_is_rejected(monkeypatch, tmp_path):
    (tmp_path / '.env').write_text('LLM_PROVIDER=typo\n')
    monkeypatch.setattr(runner_config, "REPO_ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["runner", "--policy", "full_approve"])
    with pytest.raises(SystemExit):
        runner.main()


def test_missing_explicit_env_file_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["runner", "--env-file", str(tmp_path/'missing.env')])
    with pytest.raises(SystemExit):
        runner_config.load_runner_env()


def test_local_model_check_and_missing_id(monkeypatch):
    fake_server(monkeypatch, lambda r: httpx2.Response(200, json={"object": "list", "data": [
        {"id": "local-model", "object": "model", "created": 0, "owned_by": "local"},
    ]}))
    inference.check_local_models(["local-model"])
    with pytest.raises(ValueError, match="Available IDs: local-model"):
        inference.check_local_models(["missing-model"])


def test_unavailable_local_server_does_not_fall_back(monkeypatch):
    def offline(request):
        raise httpx2.ConnectError("offline", request=request)

    fake_server(monkeypatch, offline)
    with pytest.raises(ValueError, match="lms server start"):
        inference.check_local_models(["local-model"])


def test_component_provider_change_uses_its_own_model(monkeypatch):
    monkeypatch.setenv("REVIEWER_PROVIDER", "compatible")
    monkeypatch.setenv("INFERENCE_MODEL", "hosted-reviewer")
    assert inference.component_settings("REVIEWER", "lmstudio", "agent-model") == ("compatible", "hosted-reviewer")
    assert inference.component_settings("REVIEWER", "lmstudio", "agent-model", "explicit") == ("compatible", "explicit")


@pytest.mark.parametrize("provider,key", [("groq", "GROQ_API_KEY"), ("openai", "OPENAI_API_KEY")])
def test_hosted_credentials_are_required(provider, key):
    with pytest.raises(ValueError, match=key):
        inference.make_inference_client(provider)


def test_compatible_endpoint_must_be_configured():
    with pytest.raises(ValueError, match="INFERENCE_BASE_URL"):
        inference.make_inference_client("compatible")
