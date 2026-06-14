"""Groq fallback provider — Llama models via OpenAI-compatible endpoint."""

from backend.app.config import settings
from backend.app.llm.providers.openai_compat import OpenAICompatProvider


def make_groq_provider() -> OpenAICompatProvider:
    if not settings.GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is required when USE_GROQ_FALLBACK=true")
    return OpenAICompatProvider(
        base_url=settings.GROQ_BASE_URL,
        api_key=settings.GROQ_API_KEY,
        tier_model_map=settings.GROQ_MODEL_TIERS,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.LLM_TIMEOUT_S,
    )
