"""Unit tests for Phase 2 Steps 2–3 — Duffel flights + stays + travel_search node.

All tests are offline: no Duffel API calls, no LLM calls. Network and LLM
interactions are monkeypatched with typed fakes that satisfy the contracts.
"""

import json

from backend.app.llm.base import LLMResponse
from backend.app.tools.base import ToolResult
from backend.app.tools.duffel import (
    DuffelFlightInput,
    DuffelFlightOffers,
    DuffelFlightTool,
    DuffelStaysOffers,
    FlightOffer,
    HotelOffer,
    _iso8601_duration_to_minutes,
)


# --- Helpers ---

def _make_llm_response(payload: dict) -> LLMResponse:
    return LLMResponse(
        text=json.dumps(payload),
        tier="small",
        model="gemini-2.5-flash-lite",
        input_tokens=10,
        output_tokens=10,
        latency_ms=50.0,
    )


def _make_offers(n: int = 2) -> list[FlightOffer]:
    return [
        FlightOffer(
            offer_id=f"off_{i}",
            price=500.0 + i * 100,
            currency="USD",
            carrier="Duffel Airways",
            departure_at="2026-07-25T10:00:00",
            arrival_at="2026-07-25T22:00:00",
            duration_minutes=720,
            stops=0,
        )
        for i in range(n)
    ]


# --- Tests ---

def test_travel_search_node_happy_path(monkeypatch):
    """Node writes serialised flights into state when tool succeeds."""
    import backend.app.agents.travel_search as ts_module

    offers = _make_offers(3)
    monkeypatch.setattr(
        ts_module.llm, "complete",
        lambda tier, msgs, **kw: _make_llm_response({
            "origin": "SFO",
            "destination": "TYO",
            "departure_date": "2026-07-25",
            "return_date": "2026-08-01",
            "passengers": 1,
        }),
    )
    monkeypatch.setattr(
        ts_module._flight_tool, "run",
        lambda inp: ToolResult(
            success=True,
            data=DuffelFlightOffers(offers=offers),
            latency_ms=200.0,
        ),
    )

    result = ts_module.travel_search_node({
        "user_id": "demo-user",
        "query": "flights to Tokyo next month",
        "home_airport": "SFO",
    })

    assert result["flights_degraded"] is False
    assert result["travel_search_tier"] == "small"
    assert isinstance(result["flights"], list)
    assert len(result["flights"]) == 3
    assert result["flights"][0]["carrier"] == "Duffel Airways"


def test_travel_search_node_degraded_path(monkeypatch):
    """Node writes flights=None and flights_degraded=True on tool failure."""
    import backend.app.agents.travel_search as ts_module

    monkeypatch.setattr(
        ts_module.llm, "complete",
        lambda tier, msgs, **kw: _make_llm_response({
            "origin": "SFO",
            "destination": "LHR",
            "departure_date": "2026-08-10",
            "return_date": None,
            "passengers": 1,
        }),
    )
    monkeypatch.setattr(
        ts_module._flight_tool, "run",
        lambda inp: ToolResult(
            success=False,
            degraded=True,
            error="Duffel API timeout",
            latency_ms=15001.0,
        ),
    )

    result = ts_module.travel_search_node({
        "user_id": "demo-user",
        "query": "fly to London",
        "home_airport": "SFO",
    })

    assert result["flights"] is None
    assert result["flights_degraded"] is True
    assert result["travel_search_tier"] == "small"


def test_base_tool_wraps_run_exception(monkeypatch):
    """DuffelFlightTool.run() returns degraded result when _run raises — never re-raises."""
    # Force the no-key path even when a real .env key is present locally
    monkeypatch.setattr("backend.app.tools.duffel.settings.DUFFEL_API_KEY", None)
    tool = DuffelFlightTool()
    inp = DuffelFlightInput(
        origin="SFO",
        destination="TYO",
        departure_date="2026-07-25",
    )
    # No DUFFEL_API_KEY → duffel_headers() raises ValueError inside _run
    result = tool.run(inp)

    assert result.success is False
    assert result.degraded is True
    assert result.data is None
    assert result.error is not None


def test_travel_search_node_defaults_missing_fields(monkeypatch):
    """Node uses deterministic fallbacks when LLM omits departure_date and passengers."""
    import backend.app.agents.travel_search as ts_module

    captured: list[DuffelFlightInput] = []

    def _capture_run(inp: DuffelFlightInput) -> ToolResult:
        captured.append(inp)
        return ToolResult(success=False, degraded=True, error="no key", latency_ms=0.0)

    monkeypatch.setattr(
        ts_module.llm, "complete",
        lambda tier, msgs, **kw: _make_llm_response({
            "origin": None,
            "destination": "CDG",
            "departure_date": None,
            "return_date": None,
            "passengers": None,
        }),
    )
    monkeypatch.setattr(ts_module._flight_tool, "run", _capture_run)

    ts_module.travel_search_node({
        "user_id": "demo-user",
        "query": "fly to Paris",
        "home_airport": "SFO",
        "location": "Paris",
    })

    assert len(captured) == 1
    inp = captured[0]
    assert inp.origin == "SFO"       # fallback to home_airport
    assert inp.destination == "CDG"
    assert inp.passengers == 1
    # departure_date must be a valid future date
    import datetime
    dep = datetime.date.fromisoformat(inp.departure_date)
    assert dep > datetime.date.today()


def test_iso8601_duration_parsing():
    assert _iso8601_duration_to_minutes("PT11H30M") == 690
    assert _iso8601_duration_to_minutes("PT2H") == 120
    assert _iso8601_duration_to_minutes("PT45M") == 45
    assert _iso8601_duration_to_minutes("") == 0
    assert _iso8601_duration_to_minutes(None) == 0


def _make_hotel_offers(n: int = 2) -> list[HotelOffer]:
    return [
        HotelOffer(
            property_id=f"prop_{i}",
            name=f"Hotel {i}",
            price_per_night=100.0 + i * 50,
            currency="USD",
            total_price=700.0 + i * 350,
            rating=4.0,
            amenities=["wifi", "breakfast"],
        )
        for i in range(n)
    ]


def test_travel_search_node_stays_happy_path(monkeypatch):
    """Node writes serialised hotels into state when stays tool succeeds."""
    import backend.app.agents.travel_search as ts_module

    monkeypatch.setattr(
        ts_module.llm, "complete",
        lambda tier, msgs, **kw: _make_llm_response({
            "origin": "SFO",
            "destination": "TYO",
            "departure_date": "2026-07-25",
            "return_date": "2026-08-01",
            "passengers": 1,
        }),
    )
    monkeypatch.setattr(
        ts_module._flight_tool, "run",
        lambda inp: ToolResult(success=True, data=DuffelFlightOffers(offers=_make_offers(1)), latency_ms=100.0),
    )
    monkeypatch.setattr(
        ts_module._stays_tool, "run",
        lambda inp: ToolResult(
            success=True,
            data=DuffelStaysOffers(offers=_make_hotel_offers(2)),
            latency_ms=150.0,
        ),
    )

    result = ts_module.travel_search_node({
        "user_id": "demo-user",
        "query": "trip to Tokyo",
        "home_airport": "SFO",
        "budget_default": 3000.0,
    })

    assert result["hotels_degraded"] is False
    assert isinstance(result["hotels"], list)
    assert len(result["hotels"]) >= 1
    assert result["hotels"][0]["name"] == "Hotel 0"


def test_travel_search_node_stays_degraded(monkeypatch):
    """Node writes hotels=None and hotels_degraded=True when stays tool fails."""
    import backend.app.agents.travel_search as ts_module

    monkeypatch.setattr(
        ts_module.llm, "complete",
        lambda tier, msgs, **kw: _make_llm_response({
            "origin": "SFO",
            "destination": "TYO",
            "departure_date": "2026-07-25",
            "return_date": "2026-08-01",
            "passengers": 1,
        }),
    )
    monkeypatch.setattr(
        ts_module._flight_tool, "run",
        lambda inp: ToolResult(success=True, data=DuffelFlightOffers(offers=_make_offers(1)), latency_ms=100.0),
    )
    monkeypatch.setattr(
        ts_module._stays_tool, "run",
        lambda inp: ToolResult(success=False, degraded=True, error="Stays API unavailable", latency_ms=5000.0),
    )

    result = ts_module.travel_search_node({
        "user_id": "demo-user",
        "query": "trip to Tokyo",
        "home_airport": "SFO",
    })

    assert result["hotels"] is None
    assert result["hotels_degraded"] is True
