"""LangGraph orchestration graph.

Phase 2 topology:
  START → memory → router → plan → [travel_search ∥ weather ∥ rag] → budget → assemble → END

Fan-out: three edges from plan dispatch all three agents concurrently.
Fan-in: three edges into budget — LangGraph waits for all three before
budget runs. Parallel writes are safe because each agent writes to its
own namespaced state keys.
"""

import logging

from langgraph.graph import END, START, StateGraph

from backend.app.agents.rag import rag_node
from backend.app.agents.travel_search import travel_search_node
from backend.app.agents.weather import weather_node
from backend.app.memory.session import load_profile_node
from backend.app.orchestrator.nodes.assemble import assemble_node
from backend.app.orchestrator.nodes.budget import budget_node
from backend.app.orchestrator.nodes.plan import plan_node
from backend.app.orchestrator.router import router_node
from backend.app.orchestrator.state import GraphState

logger = logging.getLogger(__name__)


def build_graph():
    """Build and compile the Phase 2 graph."""
    builder = StateGraph(GraphState)

    builder.add_node("memory", load_profile_node)
    builder.add_node("router", router_node)
    builder.add_node("plan", plan_node)
    builder.add_node("travel_search", travel_search_node)
    builder.add_node("weather", weather_node)
    builder.add_node("rag", rag_node)
    builder.add_node("budget", budget_node)
    builder.add_node("assemble", assemble_node)

    # Linear prefix
    builder.add_edge(START, "memory")
    builder.add_edge("memory", "router")
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
    builder.add_edge("assemble", END)

    graph = builder.compile()
    logger.info(
        "Graph compiled: START → memory → router → plan → "
        "[travel_search ∥ weather ∥ rag] → budget → assemble → END"
    )
    return graph


# Module-level compiled graph — imported by the API layer
graph = build_graph()
