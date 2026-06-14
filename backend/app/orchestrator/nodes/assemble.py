"""Assemble node — composes the final natural-language summary.

Uses the "large" tier for synthesis. This is what makes both tiers visible
in a single run: router uses "small" for extraction, assemble uses "large"
for the final answer.

If the weather tool returned a degraded result, the summary is honest
about that rather than fabricating data.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.llm.client import llm
from backend.app.orchestrator.state import GraphState

logger = logging.getLogger(__name__)

_ASSEMBLE_TIER = "large"

_SYSTEM_PROMPT = """\
You are a helpful travel assistant. Given weather forecast data, write a short,
friendly summary (3–5 sentences) that tells the traveller what to expect.
Mention temperature range, any rain, and the general outlook. Be concise.
If the forecast data is unavailable, say so honestly and suggest the user
check a weather service before travelling.
"""


def assemble_node(state: GraphState) -> dict:
    """Synthesise a natural-language weather summary from state."""
    location = state.get("location", "unknown")
    degraded = state.get("degraded", False)
    weather = state.get("weather")

    if degraded or not weather:
        context = f"Weather data for {location!r} is currently unavailable."
    else:
        context = json.dumps(weather, indent=2)

    logger.info("Assemble: synthesising summary for location=%r degraded=%s", location, degraded)

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=f"Location: {location}\n\nForecast data:\n{context}"),
    ]

    response = llm.complete(_ASSEMBLE_TIER, messages)
    logger.info("Assemble: summary generated (%d chars)", len(response.text))

    return {
        "summary": response.text.strip(),
        "assemble_tier": _ASSEMBLE_TIER,
    }
