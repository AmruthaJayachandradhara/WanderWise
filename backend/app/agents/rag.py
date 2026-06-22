"""RAG agent node — stub placeholder.

Full implementation added in a later commit when the retrieval
pipeline and Qdrant ingest are wired in.
"""

from backend.app.orchestrator.state import GraphState


def rag_node(state: GraphState) -> dict:
    return {
        "rag_results": None,
        "visa_answer": None,
        "rag_degraded": False,
        "rag_tier": "stub",
    }
