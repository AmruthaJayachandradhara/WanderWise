"""Unit tests for Phase 2 Step 1 — basic memory / profile load.

No LLM or network calls: the memory node is pure and read-only.
"""

from backend.app.memory.session import load_profile_node
from backend.app.state.profile import _DEMO_PROFILE, UserProfile


def test_load_profile_node_returns_all_profile_fields():
    out = load_profile_node({"user_id": "demo-user"})

    assert out["home_airport"] == "SFO"
    assert out["passport_country"] == "US"
    assert out["budget_default"] == 3000.0
    assert out["home_currency"] == "USD"
    assert out["interests"] == ["food", "history", "nature"]
    assert out["preferences"] == {"diet": "vegetarian", "seat": "aisle"}


def test_load_profile_node_handles_missing_user_id():
    # Demo lookup ignores user_id, but the node must not raise without one.
    out = load_profile_node({})
    assert out["home_airport"] == "SFO"


def test_user_profile_exposes_budget_fields():
    assert isinstance(_DEMO_PROFILE, UserProfile)
    assert _DEMO_PROFILE.budget_default == 3000.0
    assert _DEMO_PROFILE.home_currency == "USD"


def test_memory_node_wired_into_graph():
    # Structural check only — avoids invoking the graph (no LLM/network).
    from backend.app.orchestrator.graph import graph

    nodes = list(graph.get_graph().nodes)
    assert "memory" in nodes
    assert "router" in nodes
    assert "plan" in nodes
    assert "budget" in nodes
