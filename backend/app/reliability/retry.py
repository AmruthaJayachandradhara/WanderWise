"""Exponential backoff with jitter for transient LLM/tool transport failures.

This covers the "API was down" failure mode. Quality failures ("the API
responded but the answer was wrong") are handled by the self-reflection
subgraph in orchestrator/nodes/reflection.py — those are intentionally
separate mechanisms.

Retryable: timeout, 429 rate-limit, 5xx server errors.
Not retryable: 4xx client errors (except 429), validation failures,
               parse errors — those re-trying won't fix.
"""

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def is_retryable(exc: Exception) -> bool:
    """Return True if this exception represents a transient transport failure."""
    try:
        import httpx
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
            return True
    except ImportError:
        pass

    exc_type = type(exc).__name__
    if exc_type in ("APITimeoutError", "APIConnectionError"):
        return True
    if exc_type == "APIStatusError":
        status = getattr(exc, "status_code", None)
        return status in _RETRYABLE_STATUS_CODES

    # Catch-all for LangChain-wrapped messages
    msg = str(exc).lower()
    return any(tok in msg for tok in ("timeout", "rate limit", "429", "503", "502", "service unavailable"))


def is_rate_limit(exc: Exception) -> bool:
    """Return True when exc is specifically a 429 quota / rate-limit error.

    Used by LLMClient to skip recording a circuit-breaker failure: a 429
    means "slow down", not "provider is down". Tripping the circuit on quota
    exhaustion blocks ALL subsequent calls for the entire cooldown window,
    turning a recoverable quota spike into a full eval cascade failure.
    """
    exc_type = type(exc).__name__
    if exc_type == "APIStatusError":
        return getattr(exc, "status_code", None) == 429
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "quota" in msg or "resource_exhausted" in msg


def with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
) -> T:
    """Call fn with exponential backoff + jitter on retryable errors.

    Delays: ~1s, ~2s, ~4s (base_delay * 2^attempt + U(0, 0.5s) jitter).
    Non-retryable exceptions propagate immediately without delay.
    Raises the last exception if all attempts are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if not is_retryable(exc):
                raise  # propagate immediately — retry won't help
            last_exc = exc
            if attempt < attempts - 1:
                delay = base_delay * (2**attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "retry: attempt %d/%d failed (%s: %s), retrying in %.1fs",
                    attempt + 1,
                    attempts,
                    type(exc).__name__,
                    exc,
                    delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "retry: all %d attempts exhausted (%s: %s)",
                    attempts,
                    type(exc).__name__,
                    exc,
                )
    raise last_exc  # type: ignore[misc]
