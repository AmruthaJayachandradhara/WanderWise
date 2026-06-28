"""Unit tests — graph structure validation.

Verifies the compiled graph has all expected Phase 2 nodes and
compiles without error. No LLM calls made.
"""

from backend.app.orchestrator.graph import graph


def test_graph_has_all_phase2_nodes():
    """All eight Phase 2 nodes must be present in the compiled graph."""
    expected = {"memory", "router", "plan", "travel_search", "weather", "rag", "budget", "assemble"}
    assert expected.issubset(set(graph.nodes))


def test_graph_compiles_without_error():
    """Graph singleton must be importable and non-null."""
    assert graph is not None
