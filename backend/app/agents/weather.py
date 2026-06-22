"""Weather agent node — extracts location then fetches forecast.

Agent-symmetry refactor: location extraction now happens here via a
small-tier LLM call rather than in the router node. Falls back to
state["location"] if the extraction fails.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.llm.client import llm
from backend.app.orchestrator.state import GraphState
from backend.app.prompts.registry import render
from backend.app.tools.weather import WeatherInput, WeatherTool

logger = logging.getLogger(__name__)

_weather_tool = WeatherTool()
_EXTRACTION_TIER = "small"
_EXTRACTION_PROMPT = "weather/argument_extraction"


def weather_node(state: GraphState) -> dict:
    """Extract location from query, fetch forecast, write result to state."""
    query = state.get("query", "")

    # Own small-tier extraction (agent symmetry)
    try:
        messages = [
            SystemMessage(content=render(_EXTRACTION_PROMPT)),
            HumanMessage(content=query),
        ]
        response = llm.complete(_EXTRACTION_TIER, messages)
        parsed = json.loads(response.text.strip())
        location = parsed.get("location") or state.get("location", "unknown")
    except Exception:
        location = state.get("location", "unknown")

    logger.info("WeatherAgent: fetching forecast for location=%r", location)

    result = _weather_tool.run(WeatherInput(location=location))

    if result.success and result.data:
        weather_data = result.data.model_dump()
        logger.info(
            "WeatherAgent: success — %d days of forecast for %s",
            len(result.data.daily),
            result.data.location,
        )
        return {
            "weather": weather_data,
            "degraded": False,
            "weather_extraction_tier": _EXTRACTION_TIER,
        }

    logger.warning("WeatherAgent: degraded — %s", result.error)
    return {
        "weather": None,
        "degraded": True,
        "weather_extraction_tier": _EXTRACTION_TIER,
    }
