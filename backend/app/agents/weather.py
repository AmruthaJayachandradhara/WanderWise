"""Weather agent node — extracts location then fetches forecast.

Agent-symmetry refactor: location extraction now happens here via a
small-tier LLM call rather than in the router node. Falls back to
state["location"] if the extraction fails.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.llm.client import llm
from backend.app.llm.parsing import parse_json_dict
from backend.app.memory.cache import api_get, api_set
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
        response = llm.complete(_EXTRACTION_TIER, messages, json_mode=True)
        parsed = parse_json_dict(response.text.strip(), context="weather_extraction")
        location = parsed.get("location") or state.get("location", "unknown")
    except Exception:
        location = state.get("location", "unknown")

    # API cache check (TTL=1h — weather is reasonably fresh for an hour)
    _cache_key = f"weather:v1:{location}"
    cached = api_get(_cache_key)
    if cached:
        logger.info("WeatherAgent: cache HIT for location=%r", location)
        return {
            "weather": parse_json_dict(cached, context="weather_cache"),
            "degraded": False,
            "weather_extraction_tier": _EXTRACTION_TIER,
            "cache_source": "api",
        }

    logger.info("WeatherAgent: fetching forecast for location=%r", location)

    result = _weather_tool.run(WeatherInput(location=location))

    if result.success and result.data:
        weather_data = result.data.model_dump()
        logger.info(
            "WeatherAgent: success — %d days of forecast for %s",
            len(result.data.daily),
            result.data.location,
        )
        from backend.app.config import settings
        api_set(_cache_key, json.dumps(weather_data), ttl=settings.CACHE_TTL_WEATHER)
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
