"""Unit tests for the assemble node (Phase 4: reservations/actions/activities).

All tests are offline: the LLM call is monkeypatched to capture the human
message it was given, so we can assert on what context assemble_node built
without depending on real generation quality.
"""

from backend.app.llm.base import LLMResponse
from backend.app.orchestrator.nodes.assemble import assemble_node


def _capture_context(monkeypatch):
    """Patch llm.complete to record the human message content, return itinerary text."""
    import backend.app.orchestrator.nodes.assemble as assemble_module

    captured = {}

    def fake_complete(tier, messages, **kw):
        captured["human_content"] = messages[-1].content
        return LLMResponse(
            text="A lovely trip summary.",
            tier=tier,
            model="fake",
            input_tokens=10,
            output_tokens=10,
            latency_ms=1.0,
        )

    monkeypatch.setattr(assemble_module.llm, "complete", fake_complete)
    return captured


def test_no_bookings_reports_none_made(monkeypatch):
    captured = _capture_context(monkeypatch)
    assemble_node({"location": "Tokyo"})
    assert "No bookings were made this session." in captured["human_content"]
    assert "No actions taken this session." in captured["human_content"]


def test_confirmed_reservation_included_with_id(monkeypatch):
    captured = _capture_context(monkeypatch)
    assemble_node({
        "location": "Tokyo",
        "confirmations": [
            {
                "booking_type": "flight",
                "provider": "duffel",
                "confirmation_id": "ord_123",
                "description": "Duffel Airways SFO -> TYO",
            }
        ],
    })
    content = captured["human_content"]
    assert "CONFIRMED" in content
    assert "ord_123" in content


def test_pending_actions_without_confirmation_reports_not_yet_confirmed(monkeypatch):
    captured = _capture_context(monkeypatch)
    assemble_node({
        "location": "Tokyo",
        "pending_actions": [{"action_type": "flight_booking", "offer_id": "off_1"}],
    })
    content = captured["human_content"]
    assert "proposed but not yet confirmed" in content
    assert "CONFIRMED" not in content


def test_calendar_and_drafted_email_reported(monkeypatch):
    captured = _capture_context(monkeypatch)
    assemble_node({
        "location": "Tokyo",
        "calendar_ics": "BEGIN:VCALENDAR...",
        "email_draft": {"subject": "Your Tokyo itinerary", "body": "..."},
        "email_status": "drafted",
    })
    content = captured["human_content"]
    assert "calendar hold" in content.lower()
    assert "awaiting your confirmation" in content
    assert "Your Tokyo itinerary" in content


def test_discarded_email_reported(monkeypatch):
    captured = _capture_context(monkeypatch)
    assemble_node({
        "location": "Tokyo",
        "email_status": "discarded",
    })
    assert "discarded" in captured["human_content"].lower()


def test_selected_restaurant_and_events_included(monkeypatch):
    captured = _capture_context(monkeypatch)
    assemble_node({
        "location": "Tokyo",
        "selected_restaurant": {"name": "Sushi Saito", "slot": "19:00", "party_size": 2},
        "events": [{"name": "Sumo Tournament"}, {"name": "Cherry Blossom Fest"}],
    })
    content = captured["human_content"]
    assert "Sushi Saito" in content
    assert "Sumo Tournament" in content


def test_returns_summary_and_assemble_tier(monkeypatch):
    _capture_context(monkeypatch)
    result = assemble_node({"location": "Tokyo"})
    assert result["summary"] == "A lovely trip summary."
    assert result["assemble_tier"] == "large"
