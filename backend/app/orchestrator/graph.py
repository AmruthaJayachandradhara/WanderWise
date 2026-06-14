"""LangGraph orchestration graph.

Phase 1 pipeline:
  START → router → weather → assemble → END

Each node is a traceable unit — this is the reason for using LangGraph
instead of a single ReAct prompt: every step is inspectable in LangSmith.

The graph is compiled once at module load and reused across requests.
"""

import logging

from langgraph.graph import END, START, StateGraph

from backend.app.agents.weather import weather_node
from backend.app.orchestrator.nodes.assemble import assemble_node
from backend.app.orchestrator.router import router_node
from backend.app.orchestrator.state import GraphState

logger = logging.getLogger(__name__)


def build_graph():
    """Build and compile the Phase 1 graph."""
    builder = StateGraph(GraphState)

    builder.add_node("router", router_node)
    builder.add_node("weather", weather_node)
    builder.add_node("assemble", assemble_node)

    builder.add_edge(START, "router")
    builder.add_edge("router", "weather")
    builder.add_edge("weather", "assemble")
    builder.add_edge("assemble", END)

    graph = builder.compile()
    logger.info("Graph compiled: START → router → weather → assemble → END")
    return graph


# Module-level compiled graph — imported by the API layer
graph = build_graph()
