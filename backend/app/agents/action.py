"""Action agent — risk-tiered action taking (Phase 4).

Low-risk, automatic: a calendar hold (.ics) is generated in code — no
external write, no key, safe to do without asking.

High-risk, gated: when the query requested booking, the agent drafts the
itinerary email (large tier) and queues the bookings as pending_actions.
Nothing here executes: the confirmation_gate node interrupts the graph and
only booking_execution — after explicit user approval — calls a
BookingProvider and writes confirmation IDs.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.config import settings
from backend.app.llm.client import llm
from backend.app.llm.parsing import parse_json_dict
from backend.app.orchestrator.state import GraphState
from backend.app.prompts.registry import render
from backend.app.tools.calendar import build_trip_ics

logger = logging.getLogger(__name__)

_ACTION_TIER = "large"
_PROMPT_ID = "action/email_drafting"


def _itinerary_context(state: GraphState) -> str:
    lines = [f"Destination: {state.get('location', 'unknown')}"]
    flight = state.get("selected_flight")
    if flight:
        lines.append(
            f"Selected flight: {flight.get('carrier', '?')} departing "
            f"{flight.get('departure_at', '?')}, {flight.get('price', '?')} "
            f"{flight.get('currency', '')}"
        )
    hotel = state.get("selected_hotel")
    if hotel:
        lines.append(
            f"Selected hotel: {hotel.get('name', '?')}, "
            f"{hotel.get('total_price', '?')} {hotel.get('currency', '')} total"
        )
    restaurant = state.get("selected_restaurant")
    if restaurant:
        lines.append(
            f"Restaurant plan: {restaurant.get('name', '?')}, "
            f"{restaurant.get('slot', 'time TBD')}, party of {restaurant.get('party_size', 2)}"
        )
    breakdown = state.get("budget_breakdown")
    if breakdown:
        lines.append(f"Budget breakdown: {json.dumps(breakdown)}")
    visa = state.get("visa_answer")
    if visa:
        lines.append(f"Visa/entry notes: {visa}")
    return "\n".join(lines)


def _draft_email(state: GraphState) -> dict:
    location = state.get("location", "your trip")
    messages = [
        SystemMessage(content=render(_PROMPT_ID)),
        HumanMessage(content=_itinerary_context(state)),
    ]
    response = llm.complete(_ACTION_TIER, messages, json_mode=True)
    parsed = parse_json_dict(response.text.strip(), context="action_email")
    if "subject" in parsed and "body" in parsed:
        return {"subject": parsed["subject"], "body": parsed["body"]}
    logger.warning("Action: email draft parse failed — using plain-text fallback")
    return {"subject": f"Your {location} itinerary", "body": response.text.strip()}


def _build_pending_actions(state: GraphState, email_subject: str) -> list[dict]:
    pending: list[dict] = []
    flight = state.get("selected_flight")
    if flight and flight.get("offer_id"):
        pending.append(
            {
                "action_type": "flight_booking",
                "offer_id": flight["offer_id"],
                "description": (
                    f"Book flight: {flight.get('carrier', '?')} — "
                    f"{flight.get('price', '?')} {flight.get('currency', '')}"
                ),
            }
        )
    hotel = state.get("selected_hotel")
    if settings.HOTELS_BOOKING_ENABLED and hotel and hotel.get("result_id"):
        pending.append(
            {
                "action_type": "hotel_booking",
                "offer_id": hotel["result_id"],
                "description": (
                    f"Book hotel: {hotel.get('name', '?')} — "
                    f"{hotel.get('total_price', '?')} {hotel.get('currency', '')}"
                ),
            }
        )
    restaurant = state.get("selected_restaurant")
    if restaurant and restaurant.get("venue_id"):
        pending.append(
            {
                "action_type": "restaurant_reservation",
                "offer_id": restaurant["venue_id"],
                "details": {
                    "venue_name": restaurant.get("name", ""),
                    "slot": restaurant.get("slot", ""),
                    "party_size": restaurant.get("party_size", 2),
                },
                "description": f"Reserve table at {restaurant.get('name', '?')}",
            }
        )
    pending.append(
        {
            "action_type": "email_send",
            "description": f"Send itinerary email: {email_subject!r}",
        }
    )
    return pending


def action_node(state: GraphState) -> dict:
    """Auto-create the calendar hold; draft + queue gated actions."""
    location = state.get("location", "your destination")

    # Low-risk: calendar hold, automatic. Pure code — degrade-safe.
    calendar_ics = None
    try:
        calendar_ics = build_trip_ics(
            location=location,
            flight=state.get("selected_flight"),
            restaurant=state.get("selected_restaurant"),
        )
    except Exception as exc:
        logger.warning("Action: calendar generation failed: %s", exc)

    if not state.get("booking_requested"):
        logger.info("Action: no booking requested — calendar hold only")
        return {
            "calendar_ics": calendar_ics,
            "pending_actions": [],
            "email_status": "none",
        }

    # High-risk: draft, never send — held at the confirmation gate.
    email_draft = _draft_email(state)
    pending_actions = _build_pending_actions(state, email_draft["subject"])
    logger.info(
        "Action: %d action(s) pending confirmation (email drafted, not sent)",
        len(pending_actions),
    )
    return {
        "calendar_ics": calendar_ics,
        "email_draft": email_draft,
        "email_status": "drafted",
        "pending_actions": pending_actions,
        "action_tier": _ACTION_TIER,
    }
