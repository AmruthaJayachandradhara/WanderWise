"""Simple in-process circuit breaker.

States:
  CLOSED   — normal operation; every request goes through.
  OPEN     — fast-failing; requests are rejected immediately for cooldown_s.
  HALF_OPEN — one probe request allowed; success → CLOSED, failure → OPEN.

The breaker is per-LLMClient instance and therefore per-process. It is not
distributed — that is intentional for a single-process FastAPI deployment.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_s: float = 60.0,
    ) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_s
        self._failures = 0
        self._state = CLOSED
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def allow_request(self) -> bool:
        """Return True if a request may proceed."""
        with self._lock:
            if self._state == CLOSED:
                return True
            if self._state == OPEN:
                elapsed = time.monotonic() - (self._opened_at or 0.0)
                if elapsed >= self._cooldown:
                    self._state = HALF_OPEN
                    logger.info("circuit: → HALF_OPEN after %.0fs (probing)", elapsed)
                    return True
                return False
            # HALF_OPEN: allow exactly one probe through
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._state != CLOSED:
                logger.info("circuit: → CLOSED (success recorded)")
            self._state = CLOSED
            self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == HALF_OPEN or self._failures >= self._threshold:
                self._state = OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "circuit: → OPEN after %d failure(s) (cooldown=%.0fs)",
                    self._failures,
                    self._cooldown,
                )

    @property
    def state(self) -> str:
        return self._state
