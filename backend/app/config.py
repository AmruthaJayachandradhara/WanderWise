from typing import Dict
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # --- API Keys & Secrets (Loaded from .env) ---
    GEMINI_API_KEY: str
    DUFFEL_API_KEY: str | None = None
    TICKETMASTER_API_KEY: str | None = None
    EVENTBRITE_TOKEN: str | None = None
    ORS_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None
    HF_TOKEN: str | None = None
    
    # Observability (LangSmith)
    LANGSMITH_API_KEY: str | None = None
    LANGSMITH_TRACING: bool = True
    LANGSMITH_PROJECT: str = "wanderwise"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"
    TRACE_SAMPLING: float = 1.0  # Default to full sampling in dev
    
    # Vector DB (Qdrant)
    QDRANT_URL: str | None = None
    QDRANT_API_KEY: str | None = None
    
    # Cache / Session Store (Upstash Redis)
    UPSTASH_REDIS_URL: str | None = None
    UPSTASH_REDIS_TOKEN: str | None = None

    # --- Phase 0 Locked Decisions ---
    # Model Tier Mappings
    MODEL_TIERS: Dict[str, str] = {
        "small": "gemini-2.5-flash-lite",
        "large": "gemini-2.5-flash"
    }
    USE_GROQ_FALLBACK: bool = False
    
    VECTOR_DB_PROVIDER: str = "qdrant"
    CACHE_PROVIDER: str = "redis"
    GUARDRAILS_MODE: str = "custom_middleware"
    DEPLOYMENT_TARGET: str = "hugging_face_spaces"
    EMBEDDING_PROVIDER: str = "gemini"

    # --- Feature Flags ---
    HOTELS_BOOKING_ENABLED: bool = True

    # --- LLM Provider Endpoints (OpenAI-compatible) ---
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL_TIERS: Dict[str, str] = {
        "small": "llama-3.1-8b-instant",
        "large": "llama-3.3-70b-versatile",
    }

    # --- LLM Call Options ---
    LLM_TEMPERATURE: float = 0.0
    LLM_TIMEOUT_S: int = 30

    # --- App & Deployment ---
    LOG_LEVEL: str = "INFO"
    APP_PORT: int = 7860  # HF Spaces Docker default
    FRONTEND_DIST_DIR: str = "frontend/dist"
    DEMO_USER_ID: str = "demo-user"

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )

# Global settings instance to be imported across the app
settings = Settings()
