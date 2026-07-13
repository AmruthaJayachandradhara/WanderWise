"""Offline unit tests for the Action agent + confirmation gate (Phase 4 Step 5).

Covers: .ics generation round-trip, action_node risk tiering (auto calendar
vs gated email/bookings), the confirmation gate interrupt/resume cycle on a
minimal checkpointed graph, and booking_execution through a fake provider.
No network, no LLM.
"""

import pytest
from icalendar import Calendar
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

import backend.app.agents.action as action_module
from backend.app.agents.action import action_node
from backend.app.llm.base import LLMResponse
from backend.app.orchestrator.nodes.confirmation import (
    booking_execution_node,
    confirmation_gate_node,
    route_action,
    route_confirmation,
)
from backend.app.orchestrator.state import GraphState
from backend.app.tools.base import ToolResult
from backend.app.tools.calendar import build_trip_ics

_FLIGHT = {
    "offer_id": "off_123",
    "carrier": "Duffel Airways",
    "price": 512.30,
    "currency": "USD",
    "departure_at": "2026-08-15T10:50:00",
    "arrival_at": "2026-08-15T18:48:00",
}

_RESTAURANT = {
    "venue_id": "osm:node/123",
    "name": "Sushi Saito",
    "slot": "2026-08-16T19:00",
    "party_size": 2,
}


def _fake_llm(monkeypatch, text: str):
    monkeypatch.setattr(
        action_module.llm,
        "complete",
        lambda tier, messages, **kw: LLMResponse(
            text=text, tier=tier, model="fake", input_tokens=0, output_tokens=0, latency_ms=1.0
        ),
    )


# ---------------------------------------------------------------------------
# Calendar tool
# ---------------------------------------------------------------------------

class TestCalendar:
    def test_ics_round_trips_through_icalendar(self):
        ics = build_trip_ics("Tokyo", flight=_FLIGHT, restaurant=_RESTAURANT)
        cal = Calendar.from_ical(ics)
        summaries = [str(e["summary"]) for e in cal.walk("VEVENT")]
        assert len(summaries) == 2
        assert any("Flight to Tokyo" in s for s in summaries)
        assert any("Sushi Saito" in s for s in summaries)

    def test_returns_none_with_nothing_datable(self):
        assert build_trip_ics("Tokyo") is None
        assert build_trip_ics("Tokyo", flight={"departure_at": "not-a-date"}) is None


# ---------------------------------------------------------------------------
# Action agent — risk tiering
# ---------------------------------------------------------------------------

class TestActionNode:
    def test_no_booking_requested_calendar_only(self, monkeypatch):
        # LLM must never be called on the no-booking path
        _fake_llm(monkeypatch, "SHOULD NOT BE CALLED")
        called = []
        monkeypatch.setattr(
            action_module, "_draft_email", lambda state: called.append(1)
        )
        result = action_node(
            {"location": "Tokyo", "selected_flight": _FLIGHT, "booking_requested": False}
        )
        assert result["calendar_ics"] is not None  # low-risk: automatic
        assert result["pending_actions"] == []
        assert result["email_status"] == "none"
        assert not called

    def test_booking_requested_drafts_and_queues(self, monkeypatch):
        _fake_llm(monkeypatch, '{"subject": "Tokyo trip", "body": "Ready to confirm."}')
        state = {
            "location": "Tokyo",
            "booking_requested": True,
            "selected_flight": _FLIGHT,
            "selected_hotel": {"result_id": "res_1", "name": "Park Hyatt", "total_price": 1450, "currency": "USD"},
            "selected_restaurant": _RESTAURANT,
        }
        result = action_node(state)
        assert result["email_status"] == "drafted"
        assert result["email_draft"] == {"subject": "Tokyo trip", "body": "Ready to confirm."}
        types = [a["action_type"] for a in result["pending_actions"]]
        assert types == [
            "flight_booking",
            "hotel_booking",
            "restaurant_reservation",
            "email_send",
        ]

    def test_email_parse_failure_falls_back_to_plain_text(self, monkeypatch):
        _fake_llm(monkeypatch, "not json at all")
        result = action_node(
            {"location": "Tokyo", "booking_requested": True, "selected_flight": _FLIGHT}
        )
        assert result["email_draft"]["subject"] == "Your Tokyo itinerary"
        assert result["email_draft"]["body"] == "not json at all"

    def test_hotel_without_result_id_not_queued(self, monkeypatch):
        _fake_llm(monkeypatch, '{"subject": "s", "body": "b"}')
        result = action_node(
            {
                "location": "Tokyo",
                "booking_requested": True,
                "selected_hotel": {"property_id": "acc_1", "name": "No handle"},
            }
        )
        types = [a["action_type"] for a in result["pending_actions"]]
        assert "hotel_booking" not in types


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

class TestRouting:
    def test_route_action(self):
        assert route_action({"pending_actions": [{"action_type": "email_send"}]}) == "confirm"
        assert route_action({"pending_actions": []}) == "skip"
        assert route_action({}) == "skip"

    def test_route_confirmation(self):
        assert route_confirmation({"actions_approved": True}) == "execute"
        assert route_confirmation({"actions_approved": False}) == "skip"
        assert route_confirmation({}) == "skip"


# ---------------------------------------------------------------------------
# Booking execution through a fake provider
# ---------------------------------------------------------------------------

class _FakeProvider:
    provider_name = "fake"
    booking_types = ("flight", "hotel", "restaurant")

    def __init__(self):
        self.reserve_calls = []

    def reserve(self, req):
        self.reserve_calls.append(req)
        from backend.app.booking.provider import Reservation

        return ToolResult(
            success=True,
            data=Reservation(
                reservation_id=f"res_{req.booking_type}",
                offer_id=req.offer_id,
                booking_type=req.booking_type,
                status="reserved",
                provider="fake",
            ),
        )

    def confirm(self, reservation_id):
        from backend.app.booking.provider import Confirmation

        return ToolResult(
            success=True,
            data=Confirmation(
                confirmation_id=f"CONF-{reservation_id}",
                reservation_id=reservation_id,
                status="confirmed",
                provider="fake",
            ),
        )


class TestBookingExecution:
    def test_executes_all_approved_actions(self, monkeypatch):
        fake = _FakeProvider()
        monkeypatch.setattr(
            "backend.app.orchestrator.nodes.confirmation.get_provider",
            lambda booking_type: fake,
        )
        state = {
            "user_id": "u1",
            "pending_actions": [
                {"action_type": "flight_booking", "offer_id": "off_1"},
                {"action_type": "restaurant_reservation", "offer_id": "osm:1", "details": {"slot": "t"}},
                {"action_type": "email_send"},
            ],
            "email_status": "drafted",
        }
        result = booking_execution_node(state)
        assert len(result["confirmations"]) == 2
        assert result["confirmation_id"] == "CONF-res_flight"
        assert result["email_status"] == "approved"
        # Idempotency keys are stable per user+type+offer
        assert fake.reserve_calls[0].idempotency_key == "u1:flight:off_1"

    def test_failed_booking_degrades_without_aborting(self, monkeypatch):
        class _FailingFlight(_FakeProvider):
            def reserve(self, req):
                if req.booking_type == "flight":
                    return ToolResult(success=False, error="offer expired")
                return super().reserve(req)

        fake = _FailingFlight()
        monkeypatch.setattr(
            "backend.app.orchestrator.nodes.confirmation.get_provider",
            lambda booking_type: fake,
        )
        state = {
            "user_id": "u1",
            "pending_actions": [
                {"action_type": "flight_booking", "offer_id": "off_1"},
                {"action_type": "restaurant_reservation", "offer_id": "osm:1"},
            ],
        }
        result = booking_execution_node(state)
        assert len(result["confirmations"]) == 1
        assert result["confirmations"][0]["booking_type"] == "restaurant"
        assert "booking_flight" in result["degraded_flags"]


# ---------------------------------------------------------------------------
# Interrupt / resume cycle on a minimal checkpointed graph
# ---------------------------------------------------------------------------

def _mini_gate_graph(monkeypatch, provider):
    """action → gate → (booking_execution | skip) → END, checkpointed."""
    monkeypatch.setattr(
        "backend.app.orchestrator.nodes.confirmation.get_provider",
        lambda booking_type: provider,
    )
    builder = StateGraph(GraphState)
    builder.add_node("confirmation_gate", confirmation_gate_node)
    builder.add_node("booking_execution", booking_execution_node)
    builder.add_edge(START, "confirmation_gate")
    builder.add_conditional_edges(
        "confirmation_gate",
        route_confirmation,
        {"execute": "booking_execution", "skip": END},
    )
    builder.add_edge("booking_execution", END)
    return builder.compile(checkpointer=InMemorySaver())


class TestConfirmationGateCycle:
    def test_interrupt_surfaces_pending_actions_then_approve_executes(self, monkeypatch):
        graph = _mini_gate_graph(monkeypatch, _FakeProvider())
        config = {"configurable": {"thread_id": "t1"}}
        state = {
            "user_id": "u1",
            "pending_actions": [{"action_type": "flight_booking", "offer_id": "off_1"}],
            "email_draft": {"subject": "s", "body": "b"},
        }

        first = graph.invoke(state, config=config)
        assert "__interrupt__" in first
        payload = first["__interrupt__"][0].value
        assert payload["pending_actions"][0]["offer_id"] == "off_1"
        assert payload["email_draft"]["subject"] == "s"

        resumed = graph.invoke(Command(resume={"approved": True}), config=config)
        assert resumed["actions_approved"] is True
        assert resumed["confirmation_id"] == "CONF-res_flight"

    def test_decline_discards_actions_and_books_nothing(self, monkeypatch):
        provider = _FakeProvider()
        graph = _mini_gate_graph(monkeypatch, provider)
        config = {"configurable": {"thread_id": "t2"}}
        state = {
            "user_id": "u1",
            "pending_actions": [{"action_type": "flight_booking", "offer_id": "off_1"}],
            "email_status": "drafted",
        }

        first = graph.invoke(state, config=config)
        assert "__interrupt__" in first

        resumed = graph.invoke(Command(resume={"approved": False}), config=config)
        assert resumed["actions_approved"] is False
        assert resumed["pending_actions"] == []
        assert resumed["email_status"] == "discarded"
        assert resumed.get("confirmation_id") is None
        assert provider.reserve_calls == []


# ---------------------------------------------------------------------------
# Full compiled graph accepts a thread config (checkpointer smoke)
# ---------------------------------------------------------------------------

def test_full_graph_requires_and_accepts_thread_id():
    from backend.app.orchestrator.graph import graph

    with pytest.raises(ValueError):
        # No thread_id with a checkpointer must fail loudly, not silently
        graph.invoke({"user_id": "u", "query": "hi"})
