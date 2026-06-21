"""Uniform tool contract.

Every tool in WanderWise implements BaseTool. The contract guarantees:
  - Typed input/output (Pydantic schemas).
  - A declared latency budget.
  - A run() method that NEVER raises — upstream failures return a degraded
    ToolResult so the orchestrator can handle them gracefully.

This is the template RAG retriever, Duffel, and booking tools will copy.
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class ToolResult(BaseModel, Generic[OutputT]):
    """Wrapper returned by every tool's run() method."""

    success: bool
    degraded: bool = False       # True when the upstream API was unavailable
    data: OutputT | None = None  # Populated on success
    error: str | None = None     # Human-readable error on failure
    latency_ms: float = 0.0


class BaseTool(ABC, Generic[InputT, OutputT]):
    """Abstract base every WanderWise tool inherits from."""

    # Subclasses declare their expected maximum latency
    latency_budget_s: float = 10.0

    @abstractmethod
    def _run(self, input: InputT) -> OutputT:  # noqa: A002
        """Execute the tool. May raise on upstream failure."""

    def run(self, input: InputT) -> ToolResult[OutputT]:  # noqa: A002
        """Execute the tool; catch any exception and return a degraded result."""
        start = time.monotonic()
        try:
            data = self._run(input)
            latency_ms = (time.monotonic() - start) * 1000
            return ToolResult(success=True, data=data, latency_ms=latency_ms)
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            logger.warning(
                "%s failed after %.0fms: %s",
                self.__class__.__name__,
                latency_ms,
                exc,
            )
            return ToolResult(
                success=False,
                degraded=True,
                error=str(exc),
                latency_ms=latency_ms,
            )
