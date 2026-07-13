"""Offline unit tests for query decomposition + RAG fan-out (Phase 4 Step 7).

LLM and retrieval are monkeypatched. Verifies: split parsing + fallback,
booking-intent detection, per-sub-query retrieval fan-out, labeled merge
input to a single synthesis call, and the single-query degenerate path.
"""

import backend.app.agents.rag as rag_module
import backend.app.rag.decompose as decompose_module
from backend.app.agents.rag import rag_node
from backend.app.llm.base import LLMResponse
from backend.app.rag.decompose import decompose_node
from backend.app.rag.retriever import RetrievedChunk


def _fake_llm(monkeypatch, module, text: str, record: list | None = None):
    def complete(tier, messages, **kw):
        if record is not None:
            record.append((tier, messages))
        return LLMResponse(
            text=text, tier=tier, model="fake",
            input_tokens=0, output_tokens=0, latency_ms=1.0,
        )

    monkeypatch.setattr(module.llm, "complete", complete)


def _chunk(text: str, iso: str) -> RetrievedChunk:
    return RetrievedChunk(
        text=text,
        score=0.9,
        source_url=f"https://travel.state.gov/{iso}",
        country_iso=iso,
        last_verified="2026-07-01T00:00:00+00:00",
        advisory_level="",
    )


def _no_cache(monkeypatch):
    monkeypatch.setattr(rag_module, "api_get", lambda k: None)
    monkeypatch.setattr(rag_module, "api_set", lambda k, v, ttl=0: None)


# ---------------------------------------------------------------------------
# decompose_node
# ---------------------------------------------------------------------------

class TestDecomposeNode:
    def test_two_passport_split(self, monkeypatch):
        _fake_llm(monkeypatch, decompose_module, (
            '{"booking_requested": false, "sub_queries": ['
            '{"query": "Visa requirements for US passport holders visiting Japan", "passport": "US", "destination": "Japan", "kind": "visa"},'
            '{"query": "Visa requirements for Indian passport holders visiting Japan", "passport": "IN", "destination": "Japan", "kind": "visa"}]}'
        ))
        result = decompose_node({
            "query": "Japan trip; I have a US passport, my partner an Indian one",
            "passport_country": "US",
            "location": "Japan",
        })
        assert len(result["sub_queries"]) == 2
        assert [s["passport"] for s in result["sub_queries"]] == ["US", "IN"]
        assert result["booking_requested"] is False
        assert result["decompose_tier"] == "small"

    def test_booking_intent_detected(self, monkeypatch):
        _fake_llm(monkeypatch, decompose_module, (
            '{"booking_requested": true, "sub_queries": ['
            '{"query": "Visa for Japan", "passport": "US", "destination": "Tokyo", "kind": "visa"}]}'
        ))
        result = decompose_node({"query": "Book me a Tokyo trip", "passport_country": "US"})
        assert result["booking_requested"] is True

    def test_parse_failure_falls_back_to_single(self, monkeypatch):
        _fake_llm(monkeypatch, decompose_module, "sorry, no JSON here")
        result = decompose_node({
            "query": "Plan a Bali trip",
            "passport_country": "US",
            "location": "Bali",
        })
        assert len(result["sub_queries"]) == 1
        assert result["sub_queries"][0]["passport"] == "US"
        assert result["sub_queries"][0]["destination"] == "Bali"
        assert result["booking_requested"] is False

    def test_fallback_booking_heuristic(self, monkeypatch):
        _fake_llm(monkeypatch, decompose_module, "not json")
        result = decompose_node({
            "query": "Please book a hotel in Rome",
            "passport_country": "US",
            "location": "Rome",
        })
        assert result["booking_requested"] is True

    def test_empty_subqueries_falls_back(self, monkeypatch):
        _fake_llm(monkeypatch, decompose_module, '{"booking_requested": false, "sub_queries": []}')
        result = decompose_node({"query": "Trip to Paris", "passport_country": "US", "location": "Paris"})
        assert len(result["sub_queries"]) == 1


# ---------------------------------------------------------------------------
# rag_node fan-out
# ---------------------------------------------------------------------------

class TestRagFanOut:
    def test_two_subqueries_two_retrievals_one_synthesis(self, monkeypatch):
        _no_cache(monkeypatch)
        retrieve_calls = []

        def fake_retrieve(query, iso, passport):
            retrieve_calls.append((query, iso, passport))
            text = "90 days visa-free" if passport == "US" else "Visa required before travel"
            return [_chunk(text, iso)]

        monkeypatch.setattr(rag_module, "retrieve", fake_retrieve)
        llm_calls = []
        _fake_llm(monkeypatch, rag_module, "US passport: 90 days [1]. Indian passport: visa required [2].", llm_calls)

        result = rag_node({
            "query": "Do we both need visas for Japan?",
            "location": "Japan",
            "passport_country": "US",
            "sub_queries": [
                {"query": "US passport Japan visa", "passport": "US", "destination": "Japan", "kind": "visa"},
                {"query": "Indian passport Japan visa", "passport": "IN", "destination": "Japan", "kind": "visa"},
            ],
        })

        assert [(iso, p) for _, iso, p in retrieve_calls] == [("JP", "US"), ("JP", "IN")]
        assert len(llm_calls) == 1  # one merged synthesis call
        human = llm_calls[0][1][1].content
        assert "=== US passport → Japan ===" in human
        assert "=== IN passport → Japan ===" in human
        assert "[1]" in human and "[2]" in human  # refs continue across sections
        # Results carry their subject label
        subjects = {r["subject"] for r in result["rag_results"]}
        assert subjects == {"US passport → Japan", "IN passport → Japan"}
        assert "US passport" in result["visa_answer"]

    def test_single_query_degenerate_path(self, monkeypatch):
        _no_cache(monkeypatch)
        retrieve_calls = []

        def fake_retrieve(query, iso, passport):
            retrieve_calls.append((iso, passport))
            return [_chunk("90 days visa-free", iso)]

        monkeypatch.setattr(rag_module, "retrieve", fake_retrieve)
        _fake_llm(monkeypatch, rag_module, "You get 90 days visa-free [1].")

        result = rag_node({
            "query": "Visa for Japan?",
            "location": "Japan",
            "passport_country": "US",
        })
        assert retrieve_calls == [("JP", "US")]
        assert result["visa_answer"].startswith("You get 90 days")
        assert result["rag_results"][0]["subject"] == "US passport → Japan"

    def test_cache_key_includes_all_subjects(self, monkeypatch):
        seen_keys = []
        monkeypatch.setattr(rag_module, "api_get", lambda k: seen_keys.append(k) or None)
        monkeypatch.setattr(rag_module, "api_set", lambda k, v, ttl=0: None)
        monkeypatch.setattr(rag_module, "retrieve", lambda q, i, p: [])
        result = rag_node({
            "query": "visas?",
            "location": "Japan",
            "passport_country": "US",
            "sub_queries": [
                {"query": "a", "passport": "US", "destination": "Japan", "kind": "visa"},
                {"query": "b", "passport": "IN", "destination": "Japan", "kind": "visa"},
            ],
        })
        assert seen_keys[0].startswith("rag:v1:JP-JP:US-IN:")
        assert result["visa_answer"] is None  # no chunks anywhere

    def test_partial_results_still_synthesise(self, monkeypatch):
        _no_cache(monkeypatch)

        def fake_retrieve(query, iso, passport):
            return [_chunk("rule text", iso)] if passport == "US" else []

        monkeypatch.setattr(rag_module, "retrieve", fake_retrieve)
        llm_calls = []
        _fake_llm(monkeypatch, rag_module, "US passport: rule [1].", llm_calls)

        result = rag_node({
            "query": "visas?",
            "location": "Japan",
            "passport_country": "US",
            "sub_queries": [
                {"query": "a", "passport": "US", "destination": "Japan", "kind": "visa"},
                {"query": "b", "passport": "IN", "destination": "Japan", "kind": "visa"},
            ],
        })
        assert len(result["rag_results"]) == 1
        human = llm_calls[0][1][1].content
        assert "=== US passport → Japan ===" in human
        assert "IN passport" not in human  # empty subject not fabricated
