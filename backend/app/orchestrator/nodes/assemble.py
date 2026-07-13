"""Assemble node — composes the final natural-language itinerary.

Phase 2 (v2): Synthesises a full travel itinerary from all parallel-agent
results: selected flight, hotel, weather forecast, visa/advisory answer,
and budget breakdown. Degrades gracefully when any component is missing.

Phase 4: folds in reservations/confirmations (flights, hotels, restaurants
— all via the same BookingProvider seam), the auto-created calendar hold,
and the drafted (never auto-sent) itinerary email, so the assembled
itinerary reflects real action-taking, not just search results.

Uses the "large" tier for synthesis — this is the step where token quality
matters most since the output is shown directly to the user.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.llm.client import llm
from backend.app.orchestrator.state import GraphState
from backend.app.prompts.registry import get_prompt, render

logger = logging.getLogger(__name__)

_ASSEMBLE_TIER = "large"
_PROMPT_ID = "orchestrator/assemble_itinerary"


def assemble_node(state: GraphState) -> dict:
    """Compose a full itinerary from all agent results in state."""
    location = state.get("location", "unknown")
    home_currency = state.get("home_currency", "USD")

    # Weather section
    weather = state.get("weather")
    degraded = state.get("degraded", False)
    if degraded or not weather:
        weather_section = f"Weather data for {location!r} is currently unavailable."
    else:
        weather_section = json.dumps(weather, indent=2)

    # Flight section
    selected_flight = state.get("selected_flight")
    flights_degraded = state.get("flights_degraded", False)
    if selected_flight:
        price = selected_flight.get("price_normalized") or selected_flight.get("price", 0)
        flight_section = (
            f"Selected flight: {selected_flight.get('carrier', 'Unknown')} "
            f"— {selected_flight.get('departure_at', '')} → {selected_flight.get('arrival_at', '')} "
            f"({selected_flight.get('stops', 0)} stop(s), {price:.0f} {home_currency})"
        )
    elif flights_degraded:
        flight_section = "Flight data is currently unavailable."
    else:
        flight_section = "No flights searched in this session."

    # Hotel section
    selected_hotel = state.get("selected_hotel")
    hotels_degraded = state.get("hotels_degraded", False)
    if selected_hotel:
        total = selected_hotel.get("total_price_normalized") or selected_hotel.get("total_price", 0)
        hotel_section = (
            f"Selected hotel: {selected_hotel.get('name', 'Unknown')} "
            f"— {total:.0f} {home_currency} total "
            f"(rating: {selected_hotel.get('rating') or 'N/A'})"
        )
    elif hotels_degraded:
        hotel_section = "Hotel data is currently unavailable."
    else:
        hotel_section = "No hotels searched in this session."

    # Budget section
    budget_breakdown = state.get("budget_breakdown")
    if budget_breakdown:
        budget_section = (
            f"Budget: {budget_breakdown.get('total_budget', 0):.0f} "
            f"{budget_breakdown.get('currency', home_currency)} total | "
            f"Remaining: {budget_breakdown.get('remaining', 0):.0f} | "
            f"Affordable: {'Yes' if budget_breakdown.get('is_affordable') else 'No'}"
        )
    else:
        budget_section = "Budget analysis not available."

    # Visa/advisory section
    visa_answer = state.get("visa_answer")
    rag_degraded = state.get("rag_degraded", False)
    if visa_answer:
        visa_section = visa_answer
    elif rag_degraded:
        visa_section = "Visa/advisory information is currently unavailable. Check travel.state.gov."
    else:
        visa_section = "No visa information requested."

    # Restaurant / activities section
    selected_restaurant = state.get("selected_restaurant")
    events = state.get("events") or []
    activities_degraded = state.get("activities_degraded", False)
    if selected_restaurant:
        activities_section = (
            f"Proposed restaurant: {selected_restaurant.get('name', 'Unknown')} "
            f"— {selected_restaurant.get('slot', 'time TBD')}, "
            f"party of {selected_restaurant.get('party_size', 2)}"
        )
    elif activities_degraded:
        activities_section = "Restaurant/activity search is currently unavailable."
    else:
        activities_section = "No restaurant reservation requested."
    if events:
        activities_section += (
            f"\nEvents nearby ({len(events)} found, deep links only — not booked in-app): "
            + "; ".join(e.get("name", "Unknown") for e in events[:3])
        )

    # Reservations & confirmations section — the ONLY source of booking claims
    # the summary is allowed to make (no-hallucinated-booking gate keys on this).
    confirmations = state.get("confirmations") or []
    if confirmations:
        reservations_section = "\n".join(
            f"- {c.get('booking_type', 'booking').title()} CONFIRMED via "
            f"{c.get('provider', 'provider')}: {c.get('description', '')} "
            f"(confirmation ID: {c.get('confirmation_id', '')})"
            for c in confirmations
        )
    elif state.get("pending_actions"):
        reservations_section = "Bookings were proposed but not yet confirmed."
    else:
        reservations_section = "No bookings were made this session."

    # Action layer section — calendar hold (auto) + drafted email (gated)
    action_parts = []
    if state.get("calendar_ics"):
        action_parts.append("A calendar hold (.ics) was created for this trip.")
    email_draft = state.get("email_draft")
    email_status = state.get("email_status", "none")
    if email_draft and email_status == "approved":
        action_parts.append(
            f"An itinerary email ({email_draft.get('subject', '')!r}) was approved and released."
        )
    elif email_draft and email_status == "drafted":
        action_parts.append(
            f"An itinerary email ({email_draft.get('subject', '')!r}) was drafted and is "
            "awaiting your confirmation before it is sent."
        )
    elif email_status == "discarded":
        action_parts.append("The drafted itinerary email was discarded per your decision.")
    action_section = " ".join(action_parts) if action_parts else "No actions taken this session."

    # Prior session context — inject pinned constraints + summary if present
    prior_section = ""
    pinned = state.get("pinned_constraints") or {}
    session_summary = state.get("session_summary") or ""
    if pinned or session_summary:
        parts = []
        if pinned:
            parts.append(f"User constraints (always honour these): {json.dumps(pinned)}")
        if session_summary:
            parts.append(f"Previous conversation summary: {session_summary}")
        prior_section = "\nPrior context:\n" + "\n".join(parts)

    full_context = (
        f"Destination: {location}\n"
        f"Weather: {weather_section}\n"
        f"Flight: {flight_section}\n"
        f"Hotel: {hotel_section}\n"
        f"Activities/Dining: {activities_section}\n"
        f"Budget: {budget_section}\n"
        f"Visa/Advisory: {visa_section}\n"
        f"Reservations: {reservations_section}\n"
        f"Actions taken: {action_section}"
        f"{prior_section}"
    )

    p = get_prompt(_PROMPT_ID)
    logger.info(
        "Assemble: composing itinerary for location=%r prompt_version=%d",
        location, p.version,
    )

    messages = [
        SystemMessage(content=render(_PROMPT_ID)),
        HumanMessage(content=full_context),
    ]

    response = llm.complete(_ASSEMBLE_TIER, messages)
    logger.info("Assemble: itinerary generated (%d chars)", len(response.text))

    return {
        "summary": response.text.strip(),
        "assemble_tier": _ASSEMBLE_TIER,
    }
