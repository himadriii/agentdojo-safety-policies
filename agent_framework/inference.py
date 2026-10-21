"""Clients for local and hosted OpenAI-compatible inference servers.

Provider-specific Groq repair and MLX adapters remain in their original modules.
No credentials or model names need to be exported by the user's shell.
"""
import os

import openai
from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
from agentdojo.models import MODEL_NAMES

from agent_framework.llm_providers import GROQ_BASE_URL, _flatten, _make_groq_compatible

PROVIDERS = ("openai", "groq", "lmstudio", "compatible")
MODEL_KEYS = {
    "openai": "OPENAI_MODEL", "groq": "GROQ_MODEL",
    "lmstudio": "LMSTUDIO_MODEL", "compatible": "INFERENCE_MODEL", "mlx": "MLX_MODEL",
}


def resolve_model(provider, explicit=None):
    if provider not in MODEL_KEYS:
        raise ValueError(f"Unsupported provider: {provider}")
    model = explicit if explicit is not None else os.getenv(MODEL_KEYS[provider]) or os.getenv("LLM_MODEL")
    if not model or not model.strip():
        raise ValueError(f"Set {MODEL_KEYS[provider]} in .env or pass --llm MODEL.")
    return model.strip()


def component_settings(component, provider, model, explicit_model=None):
    selected = os.getenv(f"{component}_PROVIDER") or provider
    selected_model = explicit_model or os.getenv(f"{component}_MODEL")
    if selected_model:
        return selected, resolve_model(selected, selected_model)
    return selected, model if selected == provider else resolve_model(selected)


def _unset(value):
    return value is None or isinstance(value, openai.NotGiven)


def _make_compatible(client, provider, response_schema=None):
    original = client.chat.completions.create

    def create(*args, **kwargs):
        messages = []
        for message in kwargs.get("messages", []):
            message = dict(message)
            if message.get("role") == "developer":
                message["role"] = "system"
            if "content" in message:
                message["content"] = _flatten(message["content"])
            messages.append(message)
        kwargs["messages"] = messages
        if _unset(kwargs.get("temperature")):
            kwargs["temperature"] = 0
        completion_tokens = kwargs.pop("max_completion_tokens", None)
        if _unset(kwargs.get("max_tokens")):
            prefix = "LMSTUDIO" if provider == "lmstudio" else "INFERENCE"
            kwargs["max_tokens"] = (
                int(os.getenv(f"{prefix}_MAX_TOKENS", "4096"))
                if _unset(completion_tokens) else completion_tokens
            )
        # Local/third-party engines need not implement OpenAI's reasoning flag.
        kwargs.pop("reasoning_effort", None)
        if provider == "lmstudio" and kwargs.get("response_format") == {"type": "json_object"}:
            if response_schema is None:
                raise ValueError("LM Studio JSON output requires an explicit response schema")
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "policy_evidence", "schema": response_schema},
            }
        return original(*args, **kwargs)

    client.chat.completions.create = create
    return client


def make_inference_client(provider, *, response_schema=None):
    if provider == "mlx":
        # Available on the P6 branch; retain its context/memory error handling.
        from agent_framework.local_provider import make_local_client
        return make_local_client()
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    prefix = {
        "openai": "OPENAI", "groq": "GROQ", "lmstudio": "LMSTUDIO", "compatible": "INFERENCE",
    }[provider]
    base_url = {
        "openai": os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
        "groq": GROQ_BASE_URL,
        "lmstudio": os.getenv("LMSTUDIO_BASE_URL") or "http://127.0.0.1:1234/v1",
        "compatible": os.getenv("INFERENCE_BASE_URL"),
    }[provider]
    if not base_url:
        raise ValueError("Set INFERENCE_BASE_URL in .env for --provider compatible.")
    key = os.getenv(f"{prefix}_API_KEY")
    if not key and provider in ("groq", "openai"):
        raise ValueError(f"Set {prefix}_API_KEY in .env for --provider {provider}.")
    client = openai.OpenAI(
        api_key=key or "local-inference",
        base_url=base_url,
        timeout=float(os.getenv(f"{prefix}_TIMEOUT", "300")),
        max_retries=int(os.getenv(f"{prefix}_MAX_RETRIES", "8" if provider == "groq" else "2")),
    )
    if provider == "groq":
        return _make_groq_compatible(client)
    if provider in ("lmstudio", "compatible"):
        return _make_compatible(client, provider, response_schema)
    return client


def make_inference_llm(provider, model):
    MODEL_NAMES.setdefault(model, "AI assistant")
    MODEL_NAMES.setdefault(model.replace("/", "_"), "AI assistant")
    return OpenAILLM(make_inference_client(provider), model)


def check_local_models(model_names):
    """Check LM Studio once before starting a potentially long benchmark."""
    if not model_names:
        return
    with make_inference_client("lmstudio") as client:
        try:
            models = client.with_options(timeout=10, max_retries=0).models.list()
        except openai.APIConnectionError as error:
            raise ValueError(
                f"Cannot reach LM Studio at {client.base_url}. Start its server "
                "in the Developer tab or with `lms server start --port 1234`."
            ) from error
        except openai.APIStatusError as error:
            raise ValueError(
                f"LM Studio rejected the model check (HTTP {error.status_code}); "
                "check LMSTUDIO_BASE_URL and LMSTUDIO_API_KEY in .env."
            ) from error
        available = {model.id for model in models.data}
        missing = set(model_names) - available
        if missing:
            raise ValueError(
                f"LM Studio models not found: {', '.join(sorted(missing))}. "
                f"Available IDs: {', '.join(sorted(available)) or '(none)'}. "
                "Load the model and set its exact ID in .env."
            )
