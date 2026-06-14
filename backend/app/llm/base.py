"""LLM abstraction types. All callers use tier names, never model strings."""

from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import BaseMessage
from pydantic import BaseModel


class LLMResponse(BaseModel):
    """Structured response returned by LLMClient.complete()."""

    text: str
    tier: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol every provider must satisfy."""

    def resolve_model(self, tier: str) -> str:
        """Return the concrete model string for the given tier."""
        ...

    def complete(
        self,
        model: str,
        messages: list[BaseMessage],
        config: dict[str, Any] | None = None,
        **opts: Any,
    ) -> Any:  # returns AIMessage
        """Call the underlying LLM and return a LangChain AIMessage."""
        ...
