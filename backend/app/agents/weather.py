"""Weather agent node — calls WeatherTool and writes result to graph state.

No LLM call here: the agent's job is tool execution, not synthesis.
Synthesis (turning raw forecast data into natural language) happens in
the assemble node so the "large" tier is used only for that step.
"""

import logging

from backend.app.orchestrator.state import GraphState
from backend.app.tools.weather import WeatherInput, WeatherTool

logger = logging.getLogger(__name__)

_weather_tool = WeatherTool()


def weather_node(state: GraphState) -> dict:
    """Fetch weather for the location in state and store the result."""
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
        return {"weather": weather_data, "degraded": False}

    logger.warning("WeatherAgent: degraded — %s", result.error)
    return {"weather": None, "degraded": True}
