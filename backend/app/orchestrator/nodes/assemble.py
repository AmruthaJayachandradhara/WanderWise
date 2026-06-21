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
from backend.app.prompts.registry import get_prompt, render

logger = logging.getLogger(__name__)

_ASSEMBLE_TIER = "large"
_PROMPT_ID = "orchestrator/assemble_itinerary"


def assemble_node(state: GraphState) -> dict:
    """Synthesise a natural-language weather summary from state."""
    location = state.get("location", "unknown")
    degraded = state.get("degraded", False)
    weather = state.get("weather")

    if degraded or not weather:
        context = f"Weather data for {location!r} is currently unavailable."
    else:
        context = json.dumps(weather, indent=2)

    p = get_prompt(_PROMPT_ID)
    logger.info("Assemble: synthesising summary for location=%r degraded=%s prompt_version=%d",
                location, degraded, p.version)

    messages = [
        SystemMessage(content=render(_PROMPT_ID)),
        HumanMessage(content=f"Location: {location}\n\nForecast data:\n{context}"),
    ]

    response = llm.complete(_ASSEMBLE_TIER, messages)
    logger.info("Assemble: summary generated (%d chars)", len(response.text))

    return {
        "summary": response.text.strip(),
        "assemble_tier": _ASSEMBLE_TIER,
    }
