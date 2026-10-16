"""OpenAI-compatible providers that AgentDojo's get_llm does not know about (Groq)."""
import os

import openai

from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
from agentdojo.models import MODEL_NAMES

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _groq_max_retries():
    """Bound provider retries; rate limiting is handled without long retry storms."""
    raw = os.getenv("GROQ_MAX_RETRIES", "3")
    try:
        retries = int(raw)
    except ValueError as exc:
        raise ValueError("GROQ_MAX_RETRIES must be a non-negative integer") from exc
    if retries < 0:
        raise ValueError("GROQ_MAX_RETRIES must be a non-negative integer")
    return retries


def _flatten(content):
    """['text part', ...] -> 'text'. None -> ''."""
    if content is None:
        return ""
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return content


def _make_groq_compatible(client):
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
        return original(*args, **kwargs)

    completions.create = create
    return client


def make_groq_llm(model: str) -> OpenAILLM:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set (put it in .env in the repo root).")
    client = openai.OpenAI(api_key=key, base_url=GROQ_BASE_URL, max_retries=_groq_max_retries())
    _make_groq_compatible(client)
    # Attacks look the model up by name inside pipeline.name (which has "/" replaced by "_").
    MODEL_NAMES.setdefault(model, "AI assistant")
    MODEL_NAMES.setdefault(model.replace("/", "_"), "AI assistant")
    return OpenAILLM(client, model)
