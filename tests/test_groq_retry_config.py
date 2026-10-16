import pytest

from agent_framework.llm_providers import _groq_max_retries


def test_groq_retry_default_and_override(monkeypatch):
    monkeypatch.delenv("GROQ_MAX_RETRIES", raising=False)
    assert _groq_max_retries() == 3
    monkeypatch.setenv("GROQ_MAX_RETRIES", "1")
    assert _groq_max_retries() == 1


@pytest.mark.parametrize("value", ["-1", "many"])
def test_groq_retry_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("GROQ_MAX_RETRIES", value)
    with pytest.raises(ValueError, match="non-negative integer"):
        _groq_max_retries()
