"""LangSmith tracing setup.

Call init_tracing() once at app startup. After that, all LangChain and
LangGraph calls are automatically traced — no further code required.

Use trace_metadata(tier, model) to get a RunnableConfig dict that attaches
tier + model to every LLM trace, making routing decisions visible in LangSmith.
"""

import logging
import os

from backend.app.config import settings

logger = logging.getLogger(__name__)

_initialized = False


def init_tracing() -> None:
    """Set LangSmith env vars so LangChain auto-traces all calls.

    Idempotent — safe to call more than once.
    """
    global _initialized
    if _initialized:
        return

    if not settings.LANGSMITH_API_KEY:
        logger.warning("LANGSMITH_API_KEY not set — tracing disabled")
        os.environ["LANGSMITH_TRACING"] = "false"
        _initialized = True
        return

    # LangChain reads these env vars automatically
    os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
    os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT
    os.environ["LANGSMITH_ENDPOINT"] = settings.LANGSMITH_ENDPOINT

    # Honour the sampling flag — set to 0 in CI to avoid burning free-tier quota
    if settings.TRACE_SAMPLING <= 0:
        os.environ["LANGSMITH_TRACING"] = "false"
        logger.info("LangSmith tracing disabled (TRACE_SAMPLING=0)")
    else:
        os.environ["LANGSMITH_TRACING"] = "true"
        logger.info(
            "LangSmith tracing enabled — project=%s sampling=%.2f",
            settings.LANGSMITH_PROJECT,
            settings.TRACE_SAMPLING,
        )

    _initialized = True


def trace_metadata(tier: str, model: str) -> dict:
    """Return a RunnableConfig fragment that records tier + model in traces.

    Usage:
        config = trace_metadata("small", "gemini-2.5-flash-lite")
        ai_msg = chat_model.invoke(messages, config=config)

    LangSmith will surface 'tier' and 'model' as metadata on the run,
    making the routing decision visible at a glance in the trace explorer.
    """
    return {
        "metadata": {
            "tier": tier,
            "model": model,
            "phase": "phase1",
        },
        "tags": [tier, "wanderwise"],
    }
