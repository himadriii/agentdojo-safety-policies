import hashlib
from types import SimpleNamespace

import pytest

from agent_framework.policies.anomaly import AnomalyPolicy, DEFAULT_ARTIFACT
from agent_framework import runner


def test_default_loads_committed_evaluated_model(monkeypatch):
    monkeypatch.delenv("P2_ANOMALY_MODEL", raising=False)
    policy = AnomalyPolicy()
    assert policy.artifact is not None, policy.load_error
    assert policy.artifact_hash == "972fdb55582c57506748828590b0a2a4ac34b94acdf496216a1a49b71a3f8aac"
    assert policy.artifact_hash == hashlib.sha256(DEFAULT_ARTIFACT.read_bytes()).hexdigest()


def test_missing_model_stops_pipeline_before_inference(monkeypatch, tmp_path):
    monkeypatch.setenv("P2_ANOMALY_MODEL", str(tmp_path / "missing.joblib"))
    def unexpected(*args, **kwargs):
        pytest.fail("Inference initialized before model validation")
    monkeypatch.setattr(runner, "make_inference_llm", unexpected)
    with pytest.raises(ValueError, match="Refusing to benchmark fallback"):
        runner.build_pipeline("test-model", "anomaly", "mock", 5)


def test_model_hash_changes_cache_identity(monkeypatch):
    monkeypatch.setattr(runner, "make_inference_llm", lambda *a, **k: SimpleNamespace())
    fake = SimpleNamespace(artifact={}, artifact_hash="first", artifact_path=DEFAULT_ARTIFACT)
    monkeypatch.setitem(runner.POLICIES, "anomaly", lambda: fake)
    first = runner.build_pipeline("test-model", "anomaly", "mock", 5)
    fake.artifact_hash = "second"
    second = runner.build_pipeline("test-model", "anomaly", "mock", 5)
    assert first.name != second.name
    assert first.anomaly_model["sha256"] == "first"
    assert second.anomaly_model["sha256"] == "second"
