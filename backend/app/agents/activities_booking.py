"""Activities/Booking subagent — restaurants + events search, reservation prep.

The fifth specialist agent (Phase 4). Search extraction runs on the small
tier; venue selection reasoning on the large tier. Restaurant search via
Overpass (OSM, no key), events via Ticketmaster Discovery (deep links only
— no in-app ticketing by design).

The chosen restaurant is only *proposed* here (selected_restaurant). The
actual reservation goes through the mock BookingProvider inside
booking_execution, after the confirmation gate — same seam as flights.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.config import settings
from backend.app.llm.client import llm
from backend.app.llm.parsing import parse_json_dict
from backend.app.memory.cache import api_get, api_set
from backend.app.orchestrator.state import GraphState
from backend.app.prompts.registry import render
from backend.app.tools.events import EventsInput, EventsTool
from backend.app.tools.places import PlacesInput, PlacesTool

logger = logging.getLogger(__name__)

_EXTRACT_TIER = "small"
_SELECT_TIER = "large"
_EXTRACT_PROMPT = "activities_booking/search_extraction"
_SELECT_PROMPT = "activities_booking/selection_reasoning"

_places_tool = PlacesTool()
_events_tool = EventsTool()


def _extract_search_args(state: GraphState) -> dict:
    context = (
        f"Query: {state.get('query', '')}\n"
        f"Interests: {', '.join(state.get('interests', []) or [])}"
    )
    messages = [
        SystemMessage(content=render(_EXTRACT_PROMPT)),
        HumanMessage(content=context),
    ]
    response = llm.complete(_EXTRACT_TIER, messages, json_mode=True)
    parsed = parse_json_dict(response.text.strip(), context="activities_extraction")
    return {
        "cuisine": parsed.get("cuisine") or "",
        "event_keyword": parsed.get("event_keyword") or "",
        "party_size": parsed.get("party_size") or 2,
    }


def _search_restaurants(location: str, cuisine: str) -> list[dict] | None:
    cache_key = f"places:v1:{location.lower()}:{cuisine.lower()}"
    cached = api_get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            logger.warning("Activities: places cache entry corrupted — refetching")
    result = _places_tool.run(PlacesInput(location=location, cuisine=cuisine))
    if not result.success:
        # Retry once without the cuisine filter before giving up
        if cuisine:
            result = _places_tool.run(PlacesInput(location=location))
        if not result.success:
            return None
    places = [p.model_dump() for p in result.data.places]
    api_set(cache_key, json.dumps(places), ttl=settings.CACHE_TTL_PLACES)
    return places


def _search_events(location: str, keyword: str) -> list[dict] | None:
    result = _events_tool.run(EventsInput(location=location, keyword=keyword))
    if not result.success:
        return None
    return [e.model_dump() for e in result.data.events]


def _select_restaurant(state: GraphState, restaurants: list[dict], args: dict) -> dict | None:
    if not restaurants:
        return None
    candidates = "\n".join(
        f"- venue_id={r['venue_id']} name={r['name']} cuisine={r.get('cuisine', '')}"
        for r in restaurants
    )
    arrival = (state.get("selected_flight") or {}).get("arrival_at", "unknown")
    context = (
        f"Traveller interests: {', '.join(state.get('interests', []) or [])}. "
        f"Cuisine preference: {args['cuisine'] or 'none'}. "
        f"Party size: {args['party_size']}.\n"
        f"Arrival: {arrival} {state.get('location', '')}.\n"
        f"Candidates:\n{candidates}"
    )
    messages = [
        SystemMessage(content=render(_SELECT_PROMPT)),
        HumanMessage(content=context),
    ]
    response = llm.complete(_SELECT_TIER, messages, json_mode=True)
    parsed = parse_json_dict(response.text.strip(), context="activities_selection")
    if parsed.get("venue_id") in {r["venue_id"] for r in restaurants}:
        return {
            "venue_id": parsed["venue_id"],
            "name": parsed.get("name", ""),
            "slot": parsed.get("slot", ""),
            "party_size": parsed.get("party_size", args["party_size"]),
            "reason": parsed.get("reason", ""),
        }
    logger.warning(
        "Activities: selection parse failed or venue_id %r not in candidates — "
        "using first candidate",
        parsed.get("venue_id"),
    )
    first = restaurants[0]
    return {
        "venue_id": first["venue_id"],
        "name": first["name"],
        "slot": "",
        "party_size": args["party_size"],
        "reason": "fallback: first search result",
    }


def activities_node(state: GraphState) -> dict:
    """Find restaurants + events; propose one restaurant for reservation."""
    location = state.get("location", "")
    if not location:
        logger.warning("Activities: no location in state — skipping")
        return {"restaurants": None, "events": None, "activities_degraded": True}

    args = _extract_search_args(state)

    restaurants = _search_restaurants(location, args["cuisine"])
    events = _search_events(location, args["event_keyword"])
    degraded = restaurants is None and events is None

    selected = _select_restaurant(state, restaurants or [], args)

    logger.info(
        "Activities: %s restaurant(s), %s event(s) for %s — selected=%s",
        len(restaurants) if restaurants is not None else "degraded",
        len(events) if events is not None else "degraded",
        location,
        (selected or {}).get("name"),
    )
    return {
        "restaurants": restaurants,
        "events": events,
        "selected_restaurant": selected,
        "activities_degraded": degraded,
        "activities_tier": _SELECT_TIER,
    }
