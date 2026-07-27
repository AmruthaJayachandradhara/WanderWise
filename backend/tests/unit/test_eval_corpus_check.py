"""Offline unit tests for the Phase 5 corpus-populated precondition check.

All tests are offline: QdrantClient is fully monkeypatched, no network.
"""

from unittest.mock import MagicMock, patch

from backend.tests.eval.run_eval import _check_corpus_populated


def _fake_client(point_counts: dict[str, int]):
    """Build a MagicMock standing in for QdrantClient with the given
    collection -> points_count mapping. All three expected collections
    exist unless omitted from point_counts."""
    client = MagicMock()
    collections = [MagicMock(name=name) for name in point_counts]
    for mock_col, name in zip(collections, point_counts):
        mock_col.name = name
    client.get_collections.return_value = MagicMock(collections=collections)

    def get_collection(name):
        info = MagicMock()
        info.points_count = point_counts[name]
        return info

    client.get_collection.side_effect = get_collection
    return client


def test_corpus_populated_passes_when_all_collections_healthy():
    healthy = {"visa_entry": 200, "advisories": 300, "destination_guides": 400}
    with patch("qdrant_client.QdrantClient", return_value=_fake_client(healthy)):
        assert _check_corpus_populated() is None


def test_corpus_populated_passes_with_a_small_but_nonempty_corpus():
    # The floor is deliberately just "not empty" (not a count tuned to a
    # specific ingest scale) — a small, single-country corpus (e.g. the
    # current Japan-only state, see run_eval.py's _MIN_COLLECTION_POINTS
    # comment) must still pass.
    small = {"visa_entry": 2, "advisories": 14, "destination_guides": 51}
    with patch("qdrant_client.QdrantClient", return_value=_fake_client(small)):
        assert _check_corpus_populated() is None


def test_corpus_populated_fails_when_truly_empty():
    empty = {"visa_entry": 0, "advisories": 0, "destination_guides": 0}
    with patch("qdrant_client.QdrantClient", return_value=_fake_client(empty)):
        result = _check_corpus_populated()
    assert result is not None
    assert "visa_entry" in result
    assert "ingest_corpus.py --all" in result


def test_corpus_populated_fails_when_collection_missing():
    missing = {"advisories": 300, "destination_guides": 400}  # no visa_entry
    with patch("qdrant_client.QdrantClient", return_value=_fake_client(missing)):
        result = _check_corpus_populated()
    assert result is not None
    assert "visa_entry" in result
    assert "does not exist" in result


def test_corpus_populated_reports_connection_failure():
    with patch("qdrant_client.QdrantClient", side_effect=RuntimeError("connection refused")):
        result = _check_corpus_populated()
    assert result is not None
    assert "connection refused" in result
