"""LLM client — the single interface the whole system calls.

Callers pass a tier ("small" or "large"), never a model name.
The active provider is selected by config (Gemini default, Groq when
USE_GROQ_FALLBACK=True). Swapping providers requires zero code changes.
"""

import logging
import time
from typing import Any

from langchain_core.messages import BaseMessage

from backend.app.config import settings
from backend.app.llm.base import LLMResponse, LLMProvider
from backend.app.observability.tracing import trace_metadata

logger = logging.getLogger(__name__)


def _build_provider() -> LLMProvider:
    if settings.USE_GROQ_FALLBACK:
        from backend.app.llm.providers.groq import make_groq_provider
        logger.info("LLM provider: Groq (fallback)")
        return make_groq_provider()
    from backend.app.llm.providers.gemini import make_gemini_provider
    logger.info("LLM provider: Gemini (primary)")
    return make_gemini_provider()


class LLMClient:
    """Thin wrapper that resolves tier → model and records latency/tokens."""

    def __init__(self) -> None:
        self._provider: LLMProvider = _build_provider()

    def complete(
        self,
        tier: str,
        messages: list[BaseMessage],
        *,
        config: dict[str, Any] | None = None,
        **opts: Any,
    ) -> LLMResponse:
        """Call the LLM for the given tier and return a structured response."""
        model = self._provider.resolve_model(tier)

        # Merge tier/model metadata into config for LangSmith trace visibility
        trace_cfg = trace_metadata(tier, model)
        if config:
            # Caller-supplied config takes precedence; merge metadata dicts
            merged_meta = {**trace_cfg.get("metadata", {}), **config.get("metadata", {})}
            merged_tags = list({*trace_cfg.get("tags", []), *config.get("tags", [])})
            config = {**trace_cfg, **config, "metadata": merged_meta, "tags": merged_tags}
        else:
            config = trace_cfg

        start = time.monotonic()
        ai_msg = self._provider.complete(model, messages, config=config, **opts)
        latency_ms = (time.monotonic() - start) * 1000

        usage = getattr(ai_msg, "usage_metadata", {}) or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        logger.info(
            "LLM call tier=%s model=%s in=%d out=%d latency=%.0fms",
            tier,
            model,
            input_tokens,
            output_tokens,
            latency_ms,
        )

        return LLMResponse(
            text=ai_msg.content,
            tier=tier,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )


# Module-level singleton — import and use throughout the app
llm = LLMClient()
