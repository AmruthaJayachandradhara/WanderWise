"""Unit tests for the budget node.

All tests are offline: Frankfurter FX and LLM calls are monkeypatched.
"""

import json

from backend.app.llm.base import LLMResponse
from backend.app.orchestrator.nodes.budget import BudgetBreakdown, budget_node


def _llm_response(idx_flight: int = 0, idx_hotel: int = 0) -> LLMResponse:
    body = json.dumps({
        "selected_flight_idx": idx_flight,
        "selected_hotel_idx": idx_hotel,
        "reasoning": "Cheapest combination within budget.",
    })
    return LLMResponse(
        text=body,
        tier="large",
        model="gemini-2.5-flash",
        input_tokens=200,
        output_tokens=50,
        latency_ms=400.0,
    )


_FLIGHT = {"carrier": "AA", "price": 800.0, "currency": "USD", "price_normalized": 800.0}
_HOTEL = {"name": "Hotel A", "total_price": 700.0, "currency": "USD", "total_price_normalized": 700.0}


def test_budget_node_happy_path(monkeypatch):
    """budget_node returns a BudgetBreakdown with selected offers."""
    import backend.app.orchestrator.nodes.budget as bmod

    monkeypatch.setattr(bmod, "_fetch_rate", lambda f, t: 1.0)
    monkeypatch.setattr(bmod.llm, "complete", lambda tier, msgs, **kw: _llm_response(0, 0))

    result = budget_node({
        "budget_default": 3000.0,
        "home_currency": "USD",
        "flights": [dict(_FLIGHT)],
        "hotels": [dict(_HOTEL)],
    })

    bd = BudgetBreakdown(**result["budget_breakdown"])
    assert bd.is_affordable is True
    assert bd.selected_flight_cost == 800.0
    assert bd.selected_hotel_cost == 700.0
    assert result["selected_flight"]["carrier"] == "AA"
    assert result["selected_hotel"]["name"] == "Hotel A"


def test_budget_node_no_offers(monkeypatch):
    """budget_node handles empty flights and hotels without crashing."""
    import backend.app.orchestrator.nodes.budget as bmod

    monkeypatch.setattr(bmod, "_fetch_rate", lambda f, t: 1.0)

    result = budget_node({"budget_default": 3000.0, "home_currency": "USD"})

    bd = BudgetBreakdown(**result["budget_breakdown"])
    assert bd.selected_flight_cost is None
    assert bd.selected_hotel_cost is None
    assert result["selected_flight"] is None


def test_budget_node_fx_normalization(monkeypatch):
    """Prices in foreign currency are normalised before selection."""
    import backend.app.orchestrator.nodes.budget as bmod

    monkeypatch.setattr(bmod, "_fetch_rate", lambda f, t: 150.0)  # USD→JPY
    monkeypatch.setattr(bmod.llm, "complete", lambda tier, msgs, **kw: _llm_response(0, 0))

    jpy_flight = {"carrier": "JL", "price": 100000.0, "currency": "JPY"}
    jpy_hotel = {"name": "Ryokan", "total_price": 80000.0, "currency": "JPY"}

    result = budget_node({
        "budget_default": 3000.0,
        "home_currency": "USD",
        "flights": [jpy_flight],
        "hotels": [jpy_hotel],
    })

    bd = BudgetBreakdown(**result["budget_breakdown"])
    assert bd.selected_flight_cost == pytest_approx(100000.0 * 150.0)


def test_budget_node_not_affordable(monkeypatch):
    """is_affordable is False when offers exceed total budget."""
    import backend.app.orchestrator.nodes.budget as bmod

    monkeypatch.setattr(bmod, "_fetch_rate", lambda f, t: 1.0)
    monkeypatch.setattr(bmod.llm, "complete", lambda tier, msgs, **kw: _llm_response(0, 0))

    expensive_flight = {"carrier": "BA", "price": 2500.0, "currency": "USD", "price_normalized": 2500.0}
    expensive_hotel = {"name": "Luxury", "total_price": 2000.0, "currency": "USD", "total_price_normalized": 2000.0}

    result = budget_node({
        "budget_default": 3000.0,
        "home_currency": "USD",
        "flights": [expensive_flight],
        "hotels": [expensive_hotel],
    })

    bd = BudgetBreakdown(**result["budget_breakdown"])
    assert bd.is_affordable is False


def pytest_approx(val):
    import math
    class _Approx:
        def __eq__(self, other):
            return math.isclose(other, val, rel_tol=1e-3)
    return _Approx()
