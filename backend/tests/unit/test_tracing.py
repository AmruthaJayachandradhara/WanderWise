"""Offline unit tests for LangSmith tracing sampling policy (Phase 5).

All tests are offline: no real LangSmith calls, no network.
"""

import os

import backend.app.observability.tracing as tracing_module
from backend.app.observability.tracing import init_tracing


def _reset(monkeypatch):
    monkeypatch.setattr(tracing_module, "_initialized", False)
    for key in ("LANGSMITH_TRACING", "LANGSMITH_TRACING_SAMPLING_RATE"):
        os.environ.pop(key, None)


def test_full_sampling_sets_tracing_true_no_rate_var(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(tracing_module.settings, "LANGSMITH_API_KEY", "test-key")
    monkeypatch.setattr(tracing_module.settings, "TRACE_SAMPLING", 1.0)
    init_tracing()
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert "LANGSMITH_TRACING_SAMPLING_RATE" not in os.environ


def test_fractional_sampling_sets_rate_var(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(tracing_module.settings, "LANGSMITH_API_KEY", "test-key")
    monkeypatch.setattr(tracing_module.settings, "TRACE_SAMPLING", 0.25)
    init_tracing()
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_TRACING_SAMPLING_RATE"] == "0.25"


def test_zero_sampling_disables_tracing(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(tracing_module.settings, "LANGSMITH_API_KEY", "test-key")
    monkeypatch.setattr(tracing_module.settings, "TRACE_SAMPLING", 0)
    init_tracing()
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert "LANGSMITH_TRACING_SAMPLING_RATE" not in os.environ


def test_no_api_key_disables_tracing_regardless_of_sampling(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(tracing_module.settings, "LANGSMITH_API_KEY", "")
    monkeypatch.setattr(tracing_module.settings, "TRACE_SAMPLING", 1.0)
    init_tracing()
    assert os.environ["LANGSMITH_TRACING"] == "false"
