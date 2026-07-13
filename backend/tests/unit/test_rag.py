"""Unit tests for the RAG agent node.

All tests are offline: retrieve() and the LLM are monkeypatched.
"""

from backend.app.llm.base import LLMResponse
from backend.app.rag.retriever import RetrievedChunk


def _llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        tier="large",
        model="gemini-2.5-flash",
        input_tokens=100,
        output_tokens=80,
        latency_ms=500.0,
    )


def _make_chunks(n: int = 2) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            text=f"US citizens can visit Japan visa-free for up to 90 days [{i}].",
            score=0.95 - i * 0.05,
            source_url="https://travel.state.gov/Japan",
            country_iso="JP",
            last_verified="2026-06-01T00:00:00+00:00",
            advisory_level="Level 1",
        )
        for i in range(n)
    ]


def test_rag_node_happy_path(monkeypatch):
    """Node writes rag_results + visa_answer when retrieval + synthesis succeed."""
    import backend.app.agents.rag as rag_module

    monkeypatch.setattr(rag_module, "_resolve_country_iso", lambda loc, q: "JP")
    monkeypatch.setattr(rag_module, "retrieve", lambda q, c, p: _make_chunks(2))
    monkeypatch.setattr(
        rag_module.llm, "complete",
        lambda tier, msgs, **kw: _llm_response("US citizens can enter Japan visa-free for up to 90 days [1]."),
    )

    result = rag_module.rag_node({
        "query": "Do I need a visa for Japan?",
        "location": "Tokyo",
        "passport_country": "US",
    })

    assert result["rag_degraded"] is False
    assert result["rag_tier"] == "large"
    assert isinstance(result["rag_results"], list)
    assert len(result["rag_results"]) == 2
    assert result["visa_answer"] is not None


def test_rag_node_disclaimer_present(monkeypatch):
    """Disclaimer is appended to every visa_answer."""
    import backend.app.agents.rag as rag_module

    monkeypatch.setattr(rag_module, "_resolve_country_iso", lambda loc, q: "JP")
    monkeypatch.setattr(rag_module, "retrieve", lambda q, c, p: _make_chunks(1))
    monkeypatch.setattr(
        rag_module.llm, "complete",
        lambda tier, msgs, **kw: _llm_response("Visa-free for 90 days."),
    )

    result = rag_module.rag_node({
        "query": "Japan visa?",
        "location": "Japan",
        "passport_country": "US",
    })

    assert "official" in result["visa_answer"].lower()
    assert "sources" in result["visa_answer"].lower()


def test_rag_node_empty_retrieval(monkeypatch):
    """Empty retrieval → visa_answer None, rag_results [], not degraded."""
    import backend.app.agents.rag as rag_module

    monkeypatch.setattr(rag_module, "_resolve_country_iso", lambda loc, q: "JP")
    monkeypatch.setattr(rag_module, "retrieve", lambda q, c, p: [])

    result = rag_module.rag_node({
        "query": "visa?",
        "location": "Japan",
        "passport_country": "US",
    })

    assert result["rag_results"] == []
    assert result["visa_answer"] is None
    assert result["rag_degraded"] is False


def test_rag_node_malformed_cache_entry_refetches(monkeypatch):
    """A corrupted/incompatible cache payload must not raise KeyError — it
    should be treated as a miss and fall through to a live retrieve+synthesise.

    Regression test for the TODO(phase-4) KeyError-swallow: run_eval.py used
    to catch KeyError around graph.invoke() because this cache-hit path did
    cached_data["visa_answer"] directly on whatever json.loads() returned.
    """
    import backend.app.agents.rag as rag_module

    monkeypatch.setattr(rag_module, "_resolve_country_iso", lambda loc, q: "JP")
    monkeypatch.setattr(rag_module, "retrieve", lambda q, c, p: _make_chunks(1))
    monkeypatch.setattr(
        rag_module.llm, "complete",
        lambda tier, msgs, **kw: _llm_response("Visa-free for 90 days [1]."),
    )
    # Not valid JSON at all
    monkeypatch.setattr(rag_module, "api_get", lambda key: "not-json{")
    monkeypatch.setattr(rag_module, "api_set", lambda key, value, ttl=0: None)

    result = rag_module.rag_node({
        "query": "Do I need a visa for Japan?",
        "location": "Tokyo",
        "passport_country": "US",
    })

    assert result.get("cache_source") != "api"
    assert result["visa_answer"] is not None


def test_rag_node_cache_entry_missing_keys_refetches(monkeypatch):
    """Valid JSON but wrong shape (e.g. a stale pre-Phase-4 payload) also
    falls through to a live fetch instead of raising."""
    import backend.app.agents.rag as rag_module

    monkeypatch.setattr(rag_module, "_resolve_country_iso", lambda loc, q: "JP")
    monkeypatch.setattr(rag_module, "retrieve", lambda q, c, p: _make_chunks(1))
    monkeypatch.setattr(
        rag_module.llm, "complete",
        lambda tier, msgs, **kw: _llm_response("Visa-free for 90 days [1]."),
    )
    monkeypatch.setattr(rag_module, "api_get", lambda key: "{}")
    monkeypatch.setattr(rag_module, "api_set", lambda key, value, ttl=0: None)

    result = rag_module.rag_node({
        "query": "Do I need a visa for Japan?",
        "location": "Tokyo",
        "passport_country": "US",
    })

    assert result.get("cache_source") != "api"
    assert result["visa_answer"] is not None
