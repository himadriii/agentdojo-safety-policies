"""OpenAI-compatible providers that AgentDojo's get_llm does not know about (Groq)."""
import os

import openai

from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
from agentdojo.models import MODEL_NAMES
from agentdojo.functions_runtime import EmptyEnv
from agentdojo.logging import Logger
from agentdojo.types import ChatAssistantMessage, text_content_block_from_string

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

class RobustOpenAILLM(OpenAILLM):
    """Resamples Groq 'tool_use_failed' (malformed tool call) instead of aborting the run."""
    max_format_retries = 3

    def query(self, query, runtime, env=EmptyEnv(), messages=(), extra_args={}):
        for attempt in range(self.max_format_retries + 1):
            try:
                return super().query(query, runtime, env, messages, extra_args)
            except openai.BadRequestError as e:
                if "tool_use_failed" not in str(e):
                    raise
                trace = Logger.get()
                if hasattr(trace, "set_contextarg"):
                    n = trace.context.get("llm_tool_format_errors", 0) + 1
                    trace.set_contextarg("llm_tool_format_errors", n)
                if attempt == self.max_format_retries:
                    msg = ChatAssistantMessage(
                        role="assistant",
                        content=[text_content_block_from_string("The model failed to produce a valid tool call.")],
                        tool_calls=None)
                    return query, runtime, env, [*messages, msg], extra_args

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
    client = openai.OpenAI(api_key=key, base_url=GROQ_BASE_URL, max_retries=8)
    _make_groq_compatible(client)
    # Attacks look the model up by name inside pipeline.name (which has "/" replaced by "_").
    MODEL_NAMES.setdefault(model, "AI assistant")
    MODEL_NAMES.setdefault(model.replace("/", "_"), "AI assistant")
    return RobustOpenAILLM(client, model)
