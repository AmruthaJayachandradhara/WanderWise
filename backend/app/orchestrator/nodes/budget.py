"""Budget node — allocates trip budget and selects best flight + hotel.

Normalises all prices to the user's home currency via Frankfurter FX
(free, no key required). Uses the large tier to pick the best offer
combination within the stated budget and builds a structured breakdown.
"""

import json
import logging

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from backend.app.llm.client import llm
from backend.app.llm.parsing import parse_json_dict
from backend.app.orchestrator.state import GraphState
from backend.app.prompts.registry import render

logger = logging.getLogger(__name__)

_BUDGET_TIER = "large"
_PROMPT_ID = "orchestrator/budget_allocation"
_FRANKFURTER_URL = "https://api.frankfurter.app/latest"
_TIMEOUT_S = 5.0


class BudgetBreakdown(BaseModel):
    total_budget: float
    currency: str
    allocated: dict[str, float]
    selected_flight_cost: float | None
    selected_hotel_cost: float | None
    estimated_activities: float
    remaining: float
    is_affordable: bool


def _fetch_rate(from_currency: str, to_currency: str) -> float:
    if from_currency == to_currency:
        return 1.0
    try:
        resp = httpx.get(
            _FRANKFURTER_URL,
            params={"from": from_currency, "to": to_currency},
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        return float(resp.json()["rates"][to_currency])
    except Exception:
        logger.warning("Frankfurter FX unavailable %s→%s, using 1.0", from_currency, to_currency)
        return 1.0


def budget_node(state: GraphState) -> dict:
    """Select best flight + hotel and compute budget breakdown."""
    total_budget = state.get("budget_default", 3000.0)
    home_currency = state.get("home_currency", "USD")
    flights = state.get("flights") or []
    hotels = state.get("hotels") or []

    # Normalise all prices to home_currency
    for offer in flights:
        currency = offer.get("currency", home_currency)
        rate = _fetch_rate(currency, home_currency)
        offer["price_normalized"] = round(offer.get("price", 0) * rate, 2)

    for offer in hotels:
        currency = offer.get("currency", home_currency)
        rate = _fetch_rate(currency, home_currency)
        offer["total_price_normalized"] = round(offer.get("total_price", 0) * rate, 2)

    top_flights = sorted(flights, key=lambda x: x.get("price_normalized", 0))[:5]
    top_hotels = sorted(hotels, key=lambda x: x.get("total_price_normalized", 0))[:5]

    context = (
        f"Total budget: {total_budget} {home_currency}\n"
        f"Flights (top {len(top_flights)}):\n{json.dumps(top_flights, indent=2)}\n"
        f"Hotels (top {len(top_hotels)}):\n{json.dumps(top_hotels, indent=2)}"
    )

    selected_flight = None
    selected_hotel = None

    if top_flights or top_hotels:
        messages = [
            SystemMessage(content=render(_PROMPT_ID)),
            HumanMessage(content=context),
        ]
        response = llm.complete(_BUDGET_TIER, messages, json_mode=True)
        try:
            parsed = parse_json_dict(response.text.strip(), context="budget")
            fi = parsed.get("selected_flight_idx", 0)
            hi = parsed.get("selected_hotel_idx", 0)
            selected_flight = top_flights[fi] if top_flights and fi < len(top_flights) else (top_flights[0] if top_flights else None)
            selected_hotel = top_hotels[hi] if top_hotels and hi < len(top_hotels) else (top_hotels[0] if top_hotels else None)
        except Exception:
            selected_flight = top_flights[0] if top_flights else None
            selected_hotel = top_hotels[0] if top_hotels else None

    # Build breakdown with 40/35/15/10 allocation
    allocated = {
        "flights": round(total_budget * 0.40, 2),
        "lodging": round(total_budget * 0.35, 2),
        "activities": round(total_budget * 0.15, 2),
        "contingency": round(total_budget * 0.10, 2),
    }
    flight_cost = selected_flight.get("price_normalized") if selected_flight else None
    hotel_cost = selected_hotel.get("total_price_normalized") if selected_hotel else None
    estimated_activities = allocated["activities"]
    spent = (flight_cost or 0) + (hotel_cost or 0) + estimated_activities
    remaining = round(total_budget - spent, 2)

    breakdown = BudgetBreakdown(
        total_budget=total_budget,
        currency=home_currency,
        allocated=allocated,
        selected_flight_cost=flight_cost,
        selected_hotel_cost=hotel_cost,
        estimated_activities=estimated_activities,
        remaining=remaining,
        is_affordable=spent <= total_budget,
    )

    logger.info(
        "Budget: flight=%.0f hotel=%.0f remaining=%.0f affordable=%s",
        flight_cost or 0, hotel_cost or 0, remaining, breakdown.is_affordable,
    )

    return {
        "budget_breakdown": breakdown.model_dump(),
        "selected_flight": selected_flight,
        "selected_hotel": selected_hotel,
        "budget_tier": _BUDGET_TIER,
    }
