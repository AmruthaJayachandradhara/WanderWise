"""LangGraph orchestration graph.

Phase 4 topology:
  START → memory → input_guardrail → (blocked? → refusal → END)
                                   → cache_lookup → (hit → output_guardrail)
                                   → router → plan
                                           → [travel_search ∥ weather ∥ rag]
                                           → budget → action
                                                    → (no pending) → assemble
                                                    → confirmation_gate   ← interrupt()
                                                       → approved → booking_execution → assemble
                                                       → declined → assemble
                                           → assemble → output_guardrail
                                                    → ok → session_update → END
                                                    → reflect (≤2) → reflection
                                                                   → output_guardrail  ← cycle

input_guardrail:  topicality + injection + PII; blocks before any agent runs.
confirmation_gate: graph-edge human-in-the-loop — high-risk actions (booking,
                  email) pause the run at a checkpoint until the user resumes
                  with approve/decline. Requires the checkpointer + thread_id.
booking_execution: the ONLY node that executes a BookingProvider; sole writer
                  of confirmation_id (the no-hallucinated-booking gate's key).
output_guardrail: schema + budget + booking (deterministic) + grounding (LLM
                  judge); on failure routes to reflection for critique-and-fix.
"""

import logging

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from backend.app.agents.action import action_node
from backend.app.agents.activities_booking import activities_node
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
from backend.app.orchestrator.nodes.confirmation import (
    booking_execution_node,
    confirmation_gate_node,
    route_action,
    route_confirmation,
)
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
    builder.add_node("activities", activities_node)
    builder.add_node("budget", budget_node)
    builder.add_node("action", action_node)
    builder.add_node("confirmation_gate", confirmation_gate_node)
    builder.add_node("booking_execution", booking_execution_node)
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

    # Fan-out: plan dispatches all four agents in parallel
    builder.add_edge("plan", "travel_search")
    builder.add_edge("plan", "weather")
    builder.add_edge("plan", "rag")
    builder.add_edge("plan", "activities")

    # Fan-in: budget waits for all four
    builder.add_edge("travel_search", "budget")
    builder.add_edge("weather", "budget")
    builder.add_edge("rag", "budget")
    builder.add_edge("activities", "budget")

    # Action layer: calendar hold always; high-risk actions hit the gate
    builder.add_edge("budget", "action")
    builder.add_conditional_edges(
        "action",
        route_action,
        {"confirm": "confirmation_gate", "skip": "assemble"},
    )
    # The gate interrupts; on resume the user's decision routes execution
    builder.add_conditional_edges(
        "confirmation_gate",
        route_confirmation,
        {"execute": "booking_execution", "skip": "assemble"},
    )
    builder.add_edge("booking_execution", "assemble")

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

    # Checkpointer enables the confirmation-gate interrupt/resume cycle.
    # In-memory is deliberate: pending confirmations are ephemeral, and the
    # deploy target is a single container. Every invoke now needs a thread_id.
    graph = builder.compile(checkpointer=InMemorySaver())
    logger.info(
        "Graph compiled: START → memory → input_guardrail → (refuse|ok) → "
        "router → plan → [travel_search ∥ weather ∥ rag] → budget → action "
        "→ (gate ⇢ booking_execution)? → assemble "
        "→ output_guardrail ⟷ reflection (≤%d) → END",
        2,
    )
    return graph


# Module-level compiled graph — imported by the API layer
graph = build_graph()
