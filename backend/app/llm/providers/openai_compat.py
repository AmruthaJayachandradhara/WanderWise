"""Shared OpenAI-compatible provider base.

Both Gemini and Groq expose an OpenAI-compatible REST API.
This single class handles both; the only differences are base_url, api_key,
and the tier→model map — all supplied by the provider-specific submodules.
Swapping providers is therefore a config change, not a code change.
"""

import logging
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


class OpenAICompatProvider:
    """Wraps ChatOpenAI with a provider-specific base URL and tier map."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        tier_model_map: dict[str, str],
        temperature: float = 0.0,
        timeout: int = 30,
    ) -> None:
        self._tier_model_map = tier_model_map
        self._base_url = base_url
        self._api_key = api_key
        self._temperature = temperature
        self._timeout = timeout

    def resolve_model(self, tier: str) -> str:
        if tier not in self._tier_model_map:
            raise ValueError(f"Unknown tier '{tier}'. Valid tiers: {list(self._tier_model_map)}")
        return self._tier_model_map[tier]

    def complete(
        self,
        model: str,
        messages: list[BaseMessage],
        config: dict[str, Any] | None = None,
        **opts: Any,
    ) -> Any:
        """Invoke the model and return an AIMessage."""
        chat = ChatOpenAI(
            model=model,
            openai_api_key=self._api_key,
            openai_api_base=self._base_url,
            temperature=self._temperature,
            timeout=self._timeout,
            **opts,
        )
        return chat.invoke(messages, config=config)
