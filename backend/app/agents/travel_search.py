"""Travel search agent node — extracts flight/stay args and calls Duffel.

Extracts structured flight search parameters from the user query using a
small-tier LLM call, applies deterministic fallbacks for missing fields,
then calls DuffelFlightTool + DuffelStaysTool and writes normalised offers
into state. A deterministic budget pre-filter removes hotels whose total
price exceeds 45% of the traveller's budget before storing results.

Graph wiring (parallel dispatch with other agents) is deferred to Step 4.
Offer ranking/selection is deferred to Step 5 (budget node).
"""

import datetime
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.llm.client import llm
from backend.app.llm.parsing import parse_json_dict
from backend.app.orchestrator.state import GraphState
from backend.app.prompts.registry import get_prompt, render
from backend.app.tools.duffel import (
    DuffelFlightInput,
    DuffelFlightTool,
    DuffelStaysInput,
    DuffelStaysTool,
)

logger = logging.getLogger(__name__)

_TIER = "small"
_PROMPT_ID = "travel_search/argument_extraction"

_flight_tool = DuffelFlightTool()
_stays_tool = DuffelStaysTool()


def travel_search_node(state: GraphState) -> dict:
    """Extract flight search args, call Duffel, write offers into state."""
    query = state.get("query", "")
    home_airport = state.get("home_airport", "")
    today = datetime.date.today().isoformat()

    p = get_prompt(_PROMPT_ID)
    messages = [
        SystemMessage(content=render(_PROMPT_ID)),
        HumanMessage(content=f"Home airport: {home_airport}\nToday: {today}\nQuery: {query}"),
    ]

    response = llm.complete(_TIER, messages, json_mode=True)
    parsed = parse_json_dict(response.text.strip(), context="travel_search")

    # Deterministic fallbacks — never re-prompt
    origin = parsed.get("origin") or home_airport
    destination = parsed.get("destination") or state.get("location", "")
    departure_date = parsed.get("departure_date") or (
        datetime.date.today() + datetime.timedelta(days=30)
    ).isoformat()
    return_date = parsed.get("return_date") or (
        datetime.date.fromisoformat(departure_date) + datetime.timedelta(days=7)
    ).isoformat()
    passengers = int(parsed.get("passengers") or 1)

    logger.info(
        "TravelSearchAgent: %s→%s dep=%s ret=%s pax=%d tier=%s prompt_version=%d",
        origin, destination, departure_date, return_date, passengers,
        _TIER, p.version,
    )

    result = _flight_tool.run(
        DuffelFlightInput(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            passengers=passengers,
        )
    )

    out: dict = {}

    if result.success and result.data:
        logger.info(
            "TravelSearchAgent: %d flight offers %s→%s",
            len(result.data.offers), origin, destination,
        )
        out["flights"] = [o.model_dump() for o in result.data.offers]
        out["flights_degraded"] = False
    else:
        logger.warning("TravelSearchAgent: flights degraded — %s", result.error)
        out["flights"] = None
        out["flights_degraded"] = True

    out["travel_search_tier"] = _TIER

    # --- Stays search ---
    stays_result = _stays_tool.run(
        DuffelStaysInput(
            destination=destination,
            check_in=departure_date,
            check_out=return_date,
            guests=passengers,
        )
    )

    if stays_result.success and stays_result.data:
        # Deterministic budget pre-filter (45% of total budget for lodging)
        lodging_budget = state.get("budget_default", 3000.0) * 0.45
        raw_hotels = stays_result.data.offers
        filtered = [h for h in raw_hotels if h.total_price <= lodging_budget]
        if not filtered:
            filtered = raw_hotels  # keep all if none fit (let budget node decide)
        logger.info(
            "TravelSearchAgent: %d hotel offers (%d after pre-filter) for %s",
            len(raw_hotels), len(filtered), destination,
        )
        out["hotels"] = [h.model_dump() for h in filtered]
        out["hotels_degraded"] = False
    else:
        logger.warning("TravelSearchAgent: stays degraded — %s", stays_result.error)
        out["hotels"] = None
        out["hotels_degraded"] = True

    return out
