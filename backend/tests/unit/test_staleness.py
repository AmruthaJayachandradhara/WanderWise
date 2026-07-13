"""Offline unit tests for staleness detection + selective re-ingestion
(Phase 4 Step 8). In-memory Qdrant; fetch + embeddings monkeypatched.
"""

from datetime import datetime, timedelta, timezone

import pytest
from qdrant_client import QdrantClient

import backend.app.agents.rag as rag_module
import backend.app.rag.ingest as ingest_module
import backend.app.rag.staleness as staleness_module
from backend.app.agents.rag import _staleness_warning, rag_node
from backend.app.rag.ingest import ingest_country
from backend.app.rag.staleness import refresh_country

_ADVISORY_V1 = (
    "Exercise normal precautions in Japan. Level 1 advisory. "
    "Some areas have increased risk, read the entire advisory carefully. "
) * 12  # long enough to produce multiple sliding-window chunks

_ADVISORY_V2 = _ADVISORY_V1.replace("normal precautions", "increased caution")


def _sources(advisory_text):
    return (
        [
            ("visa_entry", advisory_text, "https://travel.state.gov/jp.html"),
            ("advisories", advisory_text, "https://travel.state.gov/jp.html"),
            ("destination_guides", "Japan travel information. Capital: Tokyo.", "https://restcountries.com/v3.1/alpha/JP"),
        ],
        "Level 1",
    )


@pytest.fixture
def embed_counter(monkeypatch):
    """Fake embeddings; counts how many chunks were embedded."""
    counter = {"count": 0}

    def fake_embed(texts):
        counter["count"] += len(texts)
        return [[0.1] * 384 for _ in texts]

    monkeypatch.setattr(ingest_module, "embed_texts", fake_embed)
    monkeypatch.setattr(staleness_module, "embed_texts", fake_embed)
    return counter


def _ingest(monkeypatch, client, text=_ADVISORY_V1):
    monkeypatch.setattr(ingest_module, "fetch_country_sources", lambda iso: _sources(text))
    monkeypatch.setattr(staleness_module, "fetch_country_sources", lambda iso: _sources(text))
    return ingest_country("JP", client=client)


class TestRefreshCountry:
    def test_unchanged_source_zero_embeds_bumps_last_verified(self, monkeypatch, embed_counter):
        client = QdrantClient(":memory:")
        ingested = _ingest(monkeypatch, client)
        assert ingested > 0
        embed_counter["count"] = 0

        report = refresh_country("JP", collections=["advisories"], client=client)

        assert report.unchanged_chunks > 0
        assert report.new_chunks == 0
        assert report.deleted_chunks == 0
        assert not report.changed
        assert embed_counter["count"] == 0  # hash diff before embedding

        # last_verified was bumped in place
        points, _ = client.scroll(collection_name="advisories", limit=100, with_payload=True)
        for p in points:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(p.payload["last_verified"])
            assert age.total_seconds() < 60

    def test_changed_source_reingests_only_diff(self, monkeypatch, embed_counter):
        client = QdrantClient(":memory:")
        _ingest(monkeypatch, client, text=_ADVISORY_V1)
        embed_counter["count"] = 0

        # Source document changed → hash diff detects it
        monkeypatch.setattr(
            staleness_module, "fetch_country_sources", lambda iso: _sources(_ADVISORY_V2)
        )
        report = refresh_country("JP", collections=["advisories"], client=client)

        assert report.changed
        assert report.new_chunks > 0
        assert report.deleted_chunks > 0  # orphaned v1 chunks removed
        assert embed_counter["count"] == report.new_chunks  # only the diff paid for embedding

        # Store now contains only v2 content
        points, _ = client.scroll(collection_name="advisories", limit=100, with_payload=True)
        assert all("increased caution" in p.payload["text"] for p in points)

    def test_collections_filter_limits_scope(self, monkeypatch, embed_counter):
        client = QdrantClient(":memory:")
        _ingest(monkeypatch, client)
        report = refresh_country("JP", collections=["destination_guides"], client=client)
        assert report.collections == ["destination_guides"]

    def test_empty_fetch_recorded_as_error(self, monkeypatch, embed_counter):
        client = QdrantClient(":memory:")
        monkeypatch.setattr(
            staleness_module,
            "fetch_country_sources",
            lambda iso: ([("advisories", "", "https://x")], None),
        )
        report = refresh_country("JP", collections=["advisories"], client=client)
        assert report.errors


class TestStalenessWarning:
    def _result(self, days_old: int, collection: str = "advisories") -> dict:
        verified = datetime.now(timezone.utc) - timedelta(days=days_old)
        return {"last_verified": verified.isoformat(), "collection": collection}

    def test_fresh_chunk_no_warning(self):
        stale, warning = _staleness_warning([self._result(1)])
        assert not stale
        assert warning == ""

    def test_aged_advisory_warns_at_2_days(self):
        stale, warning = _staleness_warning([self._result(3)])
        assert stale
        assert "verify before travel" in warning

    def test_thresholds_are_per_collection(self):
        # 10 days is stale for advisories (2d) but fine for guides (60d)
        assert _staleness_warning([self._result(10, "advisories")])[0]
        assert not _staleness_warning([self._result(10, "destination_guides")])[0]

    def test_unparseable_date_ignored(self):
        stale, _ = _staleness_warning([{"last_verified": "", "collection": "advisories"}])
        assert not stale

    def test_rag_node_appends_warning(self, monkeypatch):
        from backend.app.llm.base import LLMResponse
        from backend.app.rag.retriever import RetrievedChunk

        monkeypatch.setattr(rag_module, "api_get", lambda k: None)
        monkeypatch.setattr(rag_module, "api_set", lambda k, v, ttl=0: None)
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        monkeypatch.setattr(
            rag_module,
            "retrieve",
            lambda q, i, p: [
                RetrievedChunk(
                    text="rules", score=0.9, source_url="https://x",
                    country_iso=i, last_verified=old, advisory_level=None,
                    collection="advisories",
                )
            ],
        )
        monkeypatch.setattr(
            rag_module.llm,
            "complete",
            lambda tier, messages, **kw: LLMResponse(
                text="Answer [1].", tier=tier, model="fake",
                input_tokens=0, output_tokens=0, latency_ms=1.0,
            ),
        )
        result = rag_node({"query": "Visa for Japan?", "location": "Japan", "passport_country": "US"})
        assert result["rag_stale"] is True
        assert "verify before travel" in result["visa_answer"]
