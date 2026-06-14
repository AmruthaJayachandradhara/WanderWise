"""Router node — extracts location and annotates state with tier choice.

Phase 1: deterministic task-type routing.
  - Uses the "small" tier for location extraction (canonical small-tier job:
    tool-argument extraction, not synthesis).
  - Always sets task_type="weather" for now; Phase 2+ adds more task types
    and a complexity classifier.

The router uses a structured JSON response so location extraction is robust.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.llm.client import llm
from backend.app.orchestrator.state import GraphState

logger = logging.getLogger(__name__)

_ROUTER_TIER = "small"

_SYSTEM_PROMPT = """\
You are a routing assistant. Extract the destination location from the user's query.
Respond with valid JSON only — no markdown, no explanation:
{"task_type": "weather", "location": "<city or region name>"}
If you cannot identify a location, use location: "unknown".
"""


def router_node(state: GraphState) -> dict:
    """Extract destination location and assign routing tier."""
    query = state.get("query", "")
    logger.info("Router: processing query=%r", query[:80])

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=query),
    ]

    response = llm.complete(_ROUTER_TIER, messages)

    try:
        parsed = json.loads(response.text.strip())
        task_type = parsed.get("task_type", "weather")
        location = parsed.get("location", "unknown")
    except (json.JSONDecodeError, AttributeError):
        logger.warning("Router: failed to parse JSON response, defaulting to weather/unknown")
        task_type = "weather"
        location = "unknown"

    logger.info("Router: task_type=%s location=%r tier=%s", task_type, location, _ROUTER_TIER)

    return {
        "task_type": task_type,
        "location": location,
        "tier": _ROUTER_TIER,
        "router_tier": _ROUTER_TIER,
    }
