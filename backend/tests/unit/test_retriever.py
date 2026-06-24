"""Unit tests for the RAG retrieval pipeline.

All tests are offline: Qdrant client, embeddings, and LLM are monkeypatched.
"""

from types import SimpleNamespace

import backend.app.rag.retriever as retriever_module
from backend.app.rag.retriever import RetrievedChunk, retrieve


def _hit(score: float, chash: str, text: str = "US citizens visa-free 90 days."):
    return SimpleNamespace(
        score=score,
        payload={
            "text": text,
            "source_url": "https://travel.state.gov/JP",
            "country_iso": "JP",
            "passport_nationality": "US",
            "last_verified": "2026-06-01T00:00:00+00:00",
            "advisory_level": "Level 1",
            "content_hash": chash,
        },
    )


class _FakeClient:
    """Stand-in Qdrant client capturing the filter passed to search()."""

    def __init__(self, hits_by_collection: dict[str, list], collections: list[str]):
        self._hits = hits_by_collection
        self._collections = collections
        self.captured_filters: list = []

    def get_collections(self):
        cols = [SimpleNamespace(name=n) for n in self._collections]
        return SimpleNamespace(collections=cols)

    def search(self, collection_name, query_vector, query_filter, limit):
        self.captured_filters.append(query_filter)
        return self._hits.get(collection_name, [])


def _patch_common(monkeypatch, client):
    monkeypatch.setattr(retriever_module, "_get_client", lambda: client)
    monkeypatch.setattr(retriever_module, "embed_query", lambda q: [0.1] * 384)
    monkeypatch.setattr(
        retriever_module, "_rewrite_query",
        lambda q, c, p: f"{q} visa entry",
    )


def test_retrieve_happy_path(monkeypatch):
    """Returns RetrievedChunk objects merged across collections, top-5 by score."""
    client = _FakeClient(
        hits_by_collection={
            "visa_entry": [_hit(0.95, "h1"), _hit(0.80, "h2")],
            "advisories": [_hit(0.70, "h3")],
            "destination_guides": [],
        },
        collections=["visa_entry", "advisories", "destination_guides"],
    )
    _patch_common(monkeypatch, client)

    results = retrieve("Do I need a visa for Japan?", "JP", "US")

    assert all(isinstance(r, RetrievedChunk) for r in results)
    assert len(results) == 3
    assert results[0].score == 0.95  # sorted descending
    assert results[0].source_url == "https://travel.state.gov/JP"


def test_retrieve_metadata_filter_applied(monkeypatch):
    """The country_iso + passport_nationality filter is built and passed to search."""
    client = _FakeClient(
        hits_by_collection={"visa_entry": [_hit(0.9, "h1")]},
        collections=["visa_entry"],
    )
    _patch_common(monkeypatch, client)

    retrieve("visa?", "JP", "US")

    assert client.captured_filters, "search() must receive a filter"
    must = client.captured_filters[0].must
    keys = {c.key: c.match.value for c in must}
    assert keys["country_iso"] == "JP"
    assert keys["passport_nationality"] == "US"


def test_retrieve_dedup_and_empty(monkeypatch):
    """Duplicate content_hash collapses to one; no collections → empty list."""
    # Dedup: same hash across collections keeps the higher score
    client = _FakeClient(
        hits_by_collection={
            "visa_entry": [_hit(0.6, "dup")],
            "advisories": [_hit(0.9, "dup")],
        },
        collections=["visa_entry", "advisories"],
    )
    _patch_common(monkeypatch, client)
    results = retrieve("visa?", "JP", "US")
    assert len(results) == 1
    assert results[0].score == 0.9

    # Empty: collection list empty → no hits
    empty_client = _FakeClient(hits_by_collection={}, collections=[])
    _patch_common(monkeypatch, empty_client)
    assert retrieve("visa?", "JP", "US") == []
