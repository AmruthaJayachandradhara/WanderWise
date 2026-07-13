"""Plan node — decides which agents to dispatch and annotates state.

Uses the large tier to interpret query + profile context and return
a list of agents_needed. The graph topology is static (always fans out
to all three agents); agents_needed is metadata for traces only.

Falls back to all three agents if the LLM response can't be parsed.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.llm.client import llm
from backend.app.orchestrator.state import GraphState
from backend.app.prompts.registry import get_prompt, render

logger = logging.getLogger(__name__)

_PLAN_TIER = "large"
_PROMPT_ID = "orchestrator/plan_dispatch"
_DEFAULT_AGENTS = ["travel_search", "weather", "rag"]


def plan_node(state: GraphState) -> dict:
    """Annotate state with which agents are needed for this query."""
    query = state.get("query", "")
    home_airport = state.get("home_airport", "unknown")
    passport_country = state.get("passport_country", "unknown")
    budget_default = state.get("budget_default", 3000.0)
    sub_queries = state.get("sub_queries") or []

    context = (
        f"Query: {query}\n"
        f"Home airport: {home_airport}\n"
        f"Passport: {passport_country}\n"
        f"Budget: {budget_default}\n"
        f"RAG sub-queries planned: {len(sub_queries) or 1}"
    )

    p = get_prompt(_PROMPT_ID)
    messages = [
        SystemMessage(content=render(_PROMPT_ID)),
        HumanMessage(content=context),
    ]

    response = llm.complete(_PLAN_TIER, messages)

    try:
        parsed = json.loads(response.text.strip())
        agents_needed = parsed.get("agents_needed", _DEFAULT_AGENTS)
        if not isinstance(agents_needed, list) or not agents_needed:
            agents_needed = _DEFAULT_AGENTS
    except (json.JSONDecodeError, AttributeError):
        logger.warning("Plan: failed to parse response, defaulting to all agents")
        agents_needed = _DEFAULT_AGENTS

    # Decomposition-aware annotation (trace metadata; topology stays static):
    # a multi-sub-query run shows its RAG fan-out width in the plan trace.
    if len(sub_queries) > 1 and "rag" in agents_needed:
        agents_needed = [
            f"rag×{len(sub_queries)}" if a == "rag" else a for a in agents_needed
        ]

    logger.info(
        "Plan: agents_needed=%s prompt_version=%d",
        agents_needed, p.version,
    )
    return {"agents_needed": agents_needed, "plan_tier": _PLAN_TIER}
