"""Router node — tier-resolution only.

Agent-symmetry refactor: each agent now extracts its own arguments via
its own small-tier prompt. The router's only job is to classify the
task type and set router_tier for traces and eval.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.llm.client import llm
from backend.app.orchestrator.state import GraphState
from backend.app.prompts.registry import get_prompt, render

logger = logging.getLogger(__name__)

_ROUTER_TIER = "small"
_PROMPT_ID = "orchestrator/router_intent"


def router_node(state: GraphState) -> dict:
    """Classify task type and set routing tier."""
    query = state.get("query", "")
    logger.info("Router: processing query=%r", query[:80])

    p = get_prompt(_PROMPT_ID)
    messages = [
        SystemMessage(content=render(_PROMPT_ID)),
        HumanMessage(content=query),
    ]

    response = llm.complete(_ROUTER_TIER, messages)

    try:
        parsed = json.loads(response.text.strip())
        task_type = parsed.get("task_type", "travel_planning")
    except (json.JSONDecodeError, AttributeError):
        logger.warning("Router: failed to parse JSON response, defaulting to travel_planning")
        task_type = "travel_planning"

    logger.info(
        "Router: task_type=%s tier=%s prompt_version=%d",
        task_type, _ROUTER_TIER, p.version,
    )

    return {
        "task_type": task_type,
        "router_tier": _ROUTER_TIER,
    }
