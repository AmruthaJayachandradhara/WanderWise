"""Gemini provider — Google AI Studio via OpenAI-compatible endpoint."""

from backend.app.config import settings
from backend.app.llm.providers.openai_compat import OpenAICompatProvider


def make_gemini_provider() -> OpenAICompatProvider:
    return OpenAICompatProvider(
        base_url=settings.GEMINI_BASE_URL,
        api_key=settings.GEMINI_API_KEY,
        tier_model_map=settings.MODEL_TIERS,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.LLM_TIMEOUT_S,
    )
