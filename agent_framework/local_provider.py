"""OpenAI-compatible provider for a local MLX-Serve server (agent and reviewer).

AgentDojo's OpenAILLM needs four adjustments against MLX-Serve:
- `developer` messages and list content are not understood (same fix as the Groq adapter);
- AgentDojo sends `temperature=0.0 or NOT_GIVEN`, so the server would sample at its default;
- MLX-Serve answers an omitted `max_tokens` with only 100 tokens, and AgentDojo never sends it;
- AgentDojo records a task error only for `context_length_exceeded`; MLX-Serve words its
  context and memory errors differently, which would crash the whole run instead.
"""
import os

import openai
from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
from agentdojo.models import MODEL_NAMES

DEFAULT_BASE_URL = "http://127.0.0.1:11234/v1"
DEFAULT_MAX_TOKENS = 4096
_CONTEXT_ERRORS = (
    "prompt exceeds maximum context length",
    "does not fit in gpu memory",
    "rotatingkvcache quantization",   # LM Studio's MLX engine fails on long prompts with a quantized KV cache
)


def base_url() -> str:
    return os.getenv("MLX_BASE_URL", DEFAULT_BASE_URL)


def max_tokens() -> int:
    return int(os.getenv("MLX_MAX_TOKENS", DEFAULT_MAX_TOKENS))


def _unset(value) -> bool:
    return value is None or isinstance(value, openai.NotGiven)


def _flatten(content):
    if content is None:
        return ""
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return content


def as_context_length_error(error):
    """The BadRequestError AgentDojo records as a task error when a local server fails on a long prompt, else None.

    AgentDojo only tolerates `context_length_exceeded`; local servers word their context and memory
    failures differently, which would otherwise crash the whole stage.
    """
    text = str(error)
    if any(marker in text.casefold() for marker in _CONTEXT_ERRORS):
        return openai.BadRequestError(
            text, response=error.response, body={"code": "context_length_exceeded", "message": text})
    return None


def make_local_compatible(client):
    completions = client.chat.completions
    original = completions.create

    def create(*args, **kwargs):
        fixed = []
        for m in kwargs.get("messages", []):
            m = dict(m)
            if m.get("role") == "developer":
                m["role"] = "system"
            if "content" in m:
                m["content"] = _flatten(m["content"])
            fixed.append(m)
        kwargs["messages"] = fixed
        if _unset(kwargs.get("temperature")):
            kwargs["temperature"] = 0
        if _unset(kwargs.get("max_tokens")):
            kwargs["max_tokens"] = max_tokens()
        try:
            return original(*args, **kwargs)
        except openai.APIStatusError as error:
            mapped = as_context_length_error(error)
            if mapped is not None:
                raise mapped from error
            raise

    completions.create = create
    return client


def make_local_client():
    client = openai.OpenAI(api_key=os.getenv("MLX_API_KEY", "mlx-local"), base_url=base_url(), max_retries=2)
    return make_local_compatible(client)


def make_local_llm(model: str) -> OpenAILLM:
    client = make_local_client()
    # Attacks look the model up by name inside pipeline.name (which has "/" replaced by "_").
    MODEL_NAMES.setdefault(model, "AI assistant")
    MODEL_NAMES.setdefault(model.replace("/", "_"), "AI assistant")
    return OpenAILLM(client, model)
