"""Fallback strategy when primary LLM provider retries are exhausted.

Strategy (in order):
  1. Tier demotion on the primary provider: large → small
     (gemini-2.5-flash → gemini-2.5-flash-lite)
  2. Groq provider at the same tier, if GROQ_API_KEY is configured
  3. Minimal degraded stub — service-unavailable message

Each step appends a tag to degraded_flags so the caller and traces know
which path was taken. The caller (LLMClient) surfaces this via the
LLMResponse.degraded / .fallback_used fields.
"""

import logging
import time
from typing import Any

from langchain_core.messages import BaseMessage

from backend.app.llm.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

_DEGRADED_STUB = "[Service temporarily unavailable. Please try again shortly.]"


def _extract_usage(ai_msg: Any) -> tuple[int, int]:
    usage = getattr(ai_msg, "usage_metadata", {}) or {}
    return usage.get("input_tokens", 0), usage.get("output_tokens", 0)


def try_fallback(
    *,
    primary_provider: LLMProvider,
    tier: str,
    messages: list[BaseMessage],
    config: dict[str, Any] | None,
    degraded_flags: list[str],
    **opts: Any,
) -> LLMResponse:
    """Attempt progressively degraded alternatives, return best available."""
    from backend.app.config import settings

    # Strategy 1: demote tier on the same primary provider
    if tier == "large":
        try:
            demoted_model = primary_provider.resolve_model("small")
            logger.warning("fallback: tier demotion large→small on primary provider")
            start = time.monotonic()
            ai_msg = primary_provider.complete(demoted_model, messages, config=config, **opts)
            latency_ms = (time.monotonic() - start) * 1000
            in_tok, out_tok = _extract_usage(ai_msg)
            degraded_flags.append("tier_demotion")
            return LLMResponse(
                text=ai_msg.content,
                tier="small",
                model=demoted_model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_ms=latency_ms,
                degraded=True,
                fallback_used="tier_demotion",
            )
        except Exception as exc:
            logger.warning("fallback: tier demotion also failed (%s)", exc)

    # Strategy 2: Groq provider
    if settings.GROQ_API_KEY:
        try:
            from backend.app.llm.providers.groq import make_groq_provider

            groq = make_groq_provider()
            groq_model = groq.resolve_model(tier)
            logger.warning("fallback: switching to Groq (tier=%s model=%s)", tier, groq_model)
            start = time.monotonic()
            ai_msg = groq.complete(groq_model, messages, config=config, **opts)
            latency_ms = (time.monotonic() - start) * 1000
            in_tok, out_tok = _extract_usage(ai_msg)
            degraded_flags.append("groq_fallback")
            return LLMResponse(
                text=ai_msg.content,
                tier=tier,
                model=groq_model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_ms=latency_ms,
                degraded=True,
                fallback_used="groq_fallback",
            )
        except Exception as exc:
            logger.warning("fallback: Groq also failed (%s)", exc)

    # Strategy 3: minimal degraded stub
    logger.error("fallback: all strategies exhausted — returning degraded stub")
    degraded_flags.append("all_providers_failed")
    return LLMResponse(
        text=_DEGRADED_STUB,
        tier=tier,
        model="degraded",
        input_tokens=0,
        output_tokens=0,
        latency_ms=0.0,
        degraded=True,
        fallback_used="stub",
    )
