from typing import Dict
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # --- API Keys & Secrets (Loaded from .env) ---
    # Optional default allows unit tests to import without a live key.
    # The eval steps in CI pass the real key via secrets.GEMINI_API_KEY.
    GEMINI_API_KEY: str = ""
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

    # --- Infra Retry + Circuit Breaker (Phase 3) ---
    LLM_RETRY_ATTEMPTS: int = 3
    LLM_RETRY_BASE_DELAY: float = 1.0       # seconds; doubles each attempt (1→2→4)
    LLM_CIRCUIT_FAILURE_THRESHOLD: int = 5  # consecutive failures before OPEN
    LLM_CIRCUIT_COOLDOWN_S: float = 60.0    # seconds in OPEN before HALF_OPEN probe

    # --- Guardrail Thresholds (Phase 3) ---
    GUARDRAIL_TOPICALITY_THRESHOLD: float = 0.95
    GUARDRAIL_GROUNDING_THRESHOLD: float = 0.80  # min faithfulness score before retry
    GUARDRAIL_MAX_REFLECTION_ATTEMPTS: int = 2

    # --- Booking & Actions (Phase 4) ---
    # booking type → provider backend; see backend/app/booking/provider.py
    BOOKING_PROVIDER_MAP: Dict[str, str] = {
        "flight": "duffel",
        "hotel": "duffel",
        "restaurant": "mock",
    }
    # None = call the reservation service in-process via ASGI transport;
    # set to e.g. http://reservation:8001 when it runs as its own container.
    RESERVATION_SERVICE_URL: str | None = None
    OVERPASS_BASE_URL: str = "https://overpass-api.de/api/interpreter"
    # Demo traveller used for Duffel sandbox orders (no real identity/money).
    BOOKING_PASSENGER: Dict[str, str] = {
        "title": "ms",
        "given_name": "Amelia",
        "family_name": "Wanderer",
        "gender": "f",
        "born_on": "1995-06-15",
        "email": "demo@wanderwise.example",
        "phone_number": "+14155550123",
    }

    # --- Cache TTLs in seconds (Phase 3) ---
    CACHE_TTL_VISA_DOCS: int = 86400     # 24h — visa rules change slowly
    CACHE_TTL_WEATHER: int = 3600        # 1h — forecast is reasonably fresh
    CACHE_TTL_FLIGHTS: int = 0           # 0 = never cache prices
    CACHE_TTL_PLACES: int = 86400        # 24h — OSM venues change slowly (Phase 4)
    CACHE_SEMANTIC_SIMILARITY_THRESHOLD: float = 0.92

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
