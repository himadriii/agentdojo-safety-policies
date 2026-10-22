"""Local MLX-Serve provider (plan U4). Fake clients only; no network."""
import os
from types import SimpleNamespace

import httpx2
import openai
import pytest
from agentdojo.agent_pipeline.llms.openai_llm import chat_completion_request
from agentdojo.models import MODEL_NAMES

from agent_framework.local_provider import DEFAULT_BASE_URL, make_local_compatible, make_local_llm
from agent_framework.runner import build_pipeline


def fake_client(raise_with=None, status=400):
    seen = []

    def create(*args, **kwargs):
        seen.append(kwargs)
        if raise_with:
            response = httpx2.Response(status, request=httpx2.Request("POST", DEFAULT_BASE_URL))
            cls = openai.BadRequestError if status == 400 else openai.InternalServerError
            raise cls(raise_with, response=response, body={"message": raise_with})
        return "ok"

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return make_local_compatible(client), seen


def request(client, temperature=0.0):
    messages = [{"role": "developer", "content": [{"type": "text", "text": "be brief"}]},
                {"role": "user", "content": "hi"}]
    return chat_completion_request(client, "m", messages, [], None, temperature)


def test_agentdojo_zero_temperature_arrives_as_zero():
    client, seen = fake_client()
    request(client, temperature=0.0)        # AgentDojo turns 0.0 into NOT_GIVEN
    assert seen[0]["temperature"] == 0
    request(client, temperature=0.7)
    assert seen[1]["temperature"] == 0.7


def test_max_tokens_default_env_and_explicit(monkeypatch):
    client, seen = fake_client()
    client.chat.completions.create(model="m", messages=[])
    assert seen[-1]["max_tokens"] == 4096
    monkeypatch.setenv("MLX_MAX_TOKENS", "2048")
    client.chat.completions.create(model="m", messages=[])
    assert seen[-1]["max_tokens"] == 2048
    client.chat.completions.create(model="m", messages=[], max_tokens=10)
    assert seen[-1]["max_tokens"] == 10


def test_developer_role_and_list_content_are_fixed():
    client, seen = fake_client()
    request(client)
    assert seen[0]["messages"][0] == {"role": "system", "content": "be brief"}


@pytest.mark.parametrize("message,status", [
    ("Prompt exceeds maximum context length (40000 > 32768)", 400),
    ("Internal server error: KV cache does not fit in GPU memory", 500),
    ("Error in iterating prediction stream: NotImplementedError: RotatingKVCache Quantization NYI", 400),
])
def test_context_and_memory_errors_become_context_length_exceeded(message, status):
    client, _ = fake_client(raise_with=message, status=status)
    with pytest.raises(openai.BadRequestError) as info:
        client.chat.completions.create(model="m", messages=[])
    assert info.value.code == "context_length_exceeded"


def test_lmstudio_client_maps_the_kv_cache_error_too():
    from agent_framework.inference import _make_compatible
    message = "NotImplementedError: RotatingKVCache Quantization NYI"

    def create(*args, **kwargs):
        response = httpx2.Response(400, request=httpx2.Request("POST", DEFAULT_BASE_URL))
        raise openai.BadRequestError(message, response=response, body={"message": message})

    client = _make_compatible(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
                              "lmstudio")
    with pytest.raises(openai.BadRequestError) as info:
        client.chat.completions.create(model="m", messages=[])
    assert info.value.code == "context_length_exceeded"


def test_other_errors_pass_through_unchanged():
    client, _ = fake_client(raise_with="model not found", status=400)
    with pytest.raises(openai.BadRequestError) as info:
        client.chat.completions.create(model="m", messages=[])
    assert info.value.code is None


def test_model_names_registered():
    make_local_llm("mlx-community/test-model")
    assert "mlx-community/test-model" in MODEL_NAMES
    assert "mlx-community_test-model" in MODEL_NAMES


def test_build_pipeline_mlx_points_at_local_server(monkeypatch):
    monkeypatch.setenv("MLX_BASE_URL", "http://127.0.0.1:9999/v1")
    pipeline = build_pipeline("mlx-community/gemma", "approval_reuse", "mock", 2, provider="mlx")
    llm = next(e for e in pipeline.elements if hasattr(e, "client"))
    assert str(llm.client.base_url).startswith("http://127.0.0.1:9999/v1")
    assert llm.model == "mlx-community/gemma"


def test_build_pipeline_groq_still_uses_groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    pipeline = build_pipeline("openai/gpt-oss-20b", "full_approve", "mock", 0, provider="groq")
    llm = next(e for e in pipeline.elements if hasattr(e, "client"))
    assert "groq.com" in str(llm.client.base_url)
