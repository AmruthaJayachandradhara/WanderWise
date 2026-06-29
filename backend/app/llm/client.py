"""LLM client — the single interface the whole system calls.

Callers pass a tier ("small" or "large"), never a model name.
The active provider is selected by config (Gemini default, Groq when
USE_GROQ_FALLBACK=True). Swapping providers requires zero code changes.

Phase 3 additions:
- Exponential backoff retry on transient transport errors (timeout, 429, 5xx)
- Provider/tier fallback when all retries are exhausted
- In-process circuit breaker to stop hammering a down dependency

Infra retry (this module) and quality retry (orchestrator/nodes/reflection.py)
are intentionally separate mechanisms:
  - Infra retry:    "the API was down" → retry the same call
  - Quality retry:  "the API responded but the answer was wrong" → critique + regenerate
"""

import logging
import time
from typing import Any

from langchain_core.messages import BaseMessage

from backend.app.config import settings
from backend.app.llm.base import LLMProvider, LLMResponse
from backend.app.observability.tracing import trace_metadata
from backend.app.reliability.circuit import CircuitBreaker
from backend.app.reliability.fallback import try_fallback
from backend.app.reliability.retry import with_retry

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
    """Thin wrapper that resolves tier → model, records latency/tokens,
    and applies infra retry + fallback + circuit breaker."""

    def __init__(self) -> None:
        self._provider: LLMProvider = _build_provider()
        self._circuit = CircuitBreaker(
            failure_threshold=settings.LLM_CIRCUIT_FAILURE_THRESHOLD,
            cooldown_s=settings.LLM_CIRCUIT_COOLDOWN_S,
        )

    def complete(
        self,
        tier: str,
        messages: list[BaseMessage],
        *,
        config: dict[str, Any] | None = None,
        **opts: Any,
    ) -> LLMResponse:
        """Call the LLM for the given tier and return a structured response.

        On transient failure: retries with exponential backoff.
        On exhausted retries: delegates to try_fallback (tier demotion → Groq → stub).
        If the circuit is open: fast-fails directly to try_fallback.
        """
        model = self._provider.resolve_model(tier)

        # Merge tier/model metadata into config for LangSmith trace visibility
        trace_cfg = trace_metadata(tier, model)
        if config:
            merged_meta = {**trace_cfg.get("metadata", {}), **config.get("metadata", {})}
            merged_tags = list({*trace_cfg.get("tags", []), *config.get("tags", [])})
            config = {**trace_cfg, **config, "metadata": merged_meta, "tags": merged_tags}
        else:
            config = trace_cfg

        degraded_flags: list[str] = []

        # Fast-fail if circuit is open
        if not self._circuit.allow_request():
            logger.warning("LLM call blocked by open circuit breaker (tier=%s)", tier)
            degraded_flags.append("circuit_open")
            return try_fallback(
                primary_provider=self._provider,
                tier=tier,
                messages=messages,
                config=config,
                degraded_flags=degraded_flags,
                **opts,
            )

        # Normal path: call with retry
        start = time.monotonic()
        try:
            ai_msg = with_retry(
                lambda: self._provider.complete(model, messages, config=config, **opts),
                attempts=settings.LLM_RETRY_ATTEMPTS,
                base_delay=settings.LLM_RETRY_BASE_DELAY,
            )
            self._circuit.record_success()
        except Exception as exc:
            self._circuit.record_failure()
            logger.warning(
                "LLM call failed after %d retries (tier=%s): %s — trying fallback",
                settings.LLM_RETRY_ATTEMPTS,
                tier,
                exc,
            )
            degraded_flags.append(f"retry_exhausted:{type(exc).__name__}")
            return try_fallback(
                primary_provider=self._provider,
                tier=tier,
                messages=messages,
                config=config,
                degraded_flags=degraded_flags,
                **opts,
            )

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
