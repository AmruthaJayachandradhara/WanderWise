"""LangGraph orchestration graph.

Phase 3 topology:
  START → memory → input_guardrail → (blocked? → refusal → END)
                                   → router → plan
                                           → [travel_search ∥ weather ∥ rag]
                                           → budget → assemble
                                                    → output_guardrail
                                                    → ok → END
                                                    → reflect (≤2) → reflection
                                                                   → output_guardrail  ← cycle

input_guardrail: topicality + injection + PII; blocks before any agent runs.
output_guardrail: schema + budget (deterministic) + grounding (LLM judge);
                  on failure routes to reflection for critique-and-fix.
reflection:       large-tier critic; corrects output, loops back to output_guardrail;
                  capped at GUARDRAIL_MAX_REFLECTION_ATTEMPTS (default 2).
"""

import logging

from langgraph.graph import END, START, StateGraph

from backend.app.agents.rag import rag_node
from backend.app.agents.travel_search import travel_search_node
from backend.app.agents.weather import weather_node
from backend.app.guardrails.input import input_guardrail_node, refusal_node, route_input
from backend.app.guardrails.output import output_guardrail_node, route_output
from backend.app.memory.cache import cache_lookup_node, route_cache
from backend.app.memory.session import load_profile_node
from backend.app.memory.summary import session_update_node
from backend.app.orchestrator.nodes.assemble import assemble_node
from backend.app.orchestrator.nodes.budget import budget_node
from backend.app.orchestrator.nodes.plan import plan_node
from backend.app.orchestrator.nodes.reflection import reflection_node
from backend.app.orchestrator.router import router_node
from backend.app.orchestrator.state import GraphState

logger = logging.getLogger(__name__)


def build_graph():
    """Build and compile the Phase 3 graph."""
    builder = StateGraph(GraphState)

    builder.add_node("memory", load_profile_node)
    builder.add_node("input_guardrail", input_guardrail_node)
    builder.add_node("refusal", refusal_node)
    builder.add_node("router", router_node)
    builder.add_node("plan", plan_node)
    builder.add_node("travel_search", travel_search_node)
    builder.add_node("weather", weather_node)
    builder.add_node("rag", rag_node)
    builder.add_node("budget", budget_node)
    builder.add_node("assemble", assemble_node)
    builder.add_node("cache_lookup", cache_lookup_node)
    builder.add_node("output_guardrail", output_guardrail_node)
    builder.add_node("reflection", reflection_node)
    builder.add_node("session_update", session_update_node)

    # Linear prefix — input guardrail sits between memory and router
    builder.add_edge(START, "memory")
    builder.add_edge("memory", "input_guardrail")

    # Conditional: blocked → refusal → END; clean → cache_lookup
    builder.add_conditional_edges(
        "input_guardrail",
        route_input,
        {"refuse": "refusal", "ok": "cache_lookup"},
    )
    builder.add_edge("refusal", END)

    # Conditional: cache hit → output_guardrail (skips all agents);
    # miss → router → normal pipeline
    builder.add_conditional_edges(
        "cache_lookup",
        route_cache,
        {"hit": "output_guardrail", "miss": "router"},
    )

    builder.add_edge("router", "plan")

    # Fan-out: plan dispatches all three agents in parallel
    builder.add_edge("plan", "travel_search")
    builder.add_edge("plan", "weather")
    builder.add_edge("plan", "rag")

    # Fan-in: budget waits for all three
    builder.add_edge("travel_search", "budget")
    builder.add_edge("weather", "budget")
    builder.add_edge("rag", "budget")

    builder.add_edge("budget", "assemble")
    builder.add_edge("assemble", "output_guardrail")

    # Conditional: ok → session_update → END; reflect → reflection ↩ output_guardrail
    # route_output enforces the cap: once reflection_attempts >= max, returns "ok"
    builder.add_conditional_edges(
        "output_guardrail",
        route_output,
        {"ok": "session_update", "reflect": "reflection"},
    )
    builder.add_edge("session_update", END)
    # Close the loop: reflection writes corrected output, re-validates
    builder.add_edge("reflection", "output_guardrail")

    graph = builder.compile()
    logger.info(
        "Graph compiled: START → memory → input_guardrail → (refuse|ok) → "
        "router → plan → [travel_search ∥ weather ∥ rag] → budget → assemble "
        "→ output_guardrail ⟷ reflection (≤%d) → END",
        2,
    )
    return graph


# Module-level compiled graph — imported by the API layer
graph = build_graph()
