"""LangSmith tracing setup.

Call init_tracing() once at app startup. After that, all LangChain and
LangGraph calls are automatically traced — no further code required.

Use trace_metadata(tier, model) to get a RunnableConfig dict that attaches
tier + model to every LLM trace, making routing decisions visible in LangSmith.

Sampling policy (Phase 5): TRACE_SAMPLING is fractional, not just on/off —
1.0 = full tracing (interactive/demo runs), a fraction like 0.25 = sampled
tracing (nightly eval, to respect LangSmith's free-tier trace cap at volume),
0 = disabled (the PR-path CI gate, which runs with LANGSMITH_TRACING=false
regardless). Sampling is enforced via LANGSMITH_TRACING_SAMPLING_RATE, which
the LangSmith SDK honours natively.
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
    os.environ.pop("LANGSMITH_TRACING_SAMPLING_RATE", None)
    if settings.TRACE_SAMPLING <= 0:
        os.environ["LANGSMITH_TRACING"] = "false"
        logger.info("LangSmith tracing disabled (TRACE_SAMPLING=0)")
    elif settings.TRACE_SAMPLING < 1:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_TRACING_SAMPLING_RATE"] = str(settings.TRACE_SAMPLING)
        logger.info(
            "LangSmith tracing enabled — project=%s sampling=%.2f (fractional)",
            settings.LANGSMITH_PROJECT,
            settings.TRACE_SAMPLING,
        )
    else:
        os.environ["LANGSMITH_TRACING"] = "true"
        logger.info(
            "LangSmith tracing enabled — project=%s sampling=full",
            settings.LANGSMITH_PROJECT,
        )

    _initialized = True


def trace_metadata(
    tier: str,
    model: str,
    prompt_id: str | None = None,
    prompt_version: int | None = None,
) -> dict:
    """Return a RunnableConfig fragment that records tier + model in traces.

    Optionally records prompt_id and prompt_version so every trace shows
    which versioned prompt produced that run — makes prompt regressions
    attributable to a specific prompt + version in LangSmith.

    Usage:
        config = trace_metadata("small", "gemini-2.5-flash-lite",
                                prompt_id="orchestrator/router_intent",
                                prompt_version=1)
        ai_msg = chat_model.invoke(messages, config=config)
    """
    metadata: dict = {"tier": tier, "model": model}
    if prompt_id is not None:
        metadata["prompt_id"] = prompt_id
    if prompt_version is not None:
        metadata["prompt_version"] = prompt_version
    return {
        "metadata": metadata,
        "tags": [tier, "wanderwise"],
    }
