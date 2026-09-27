from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "CivicPulse"
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/civicpulse",
        validation_alias="DATABASE_URL",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
    )

    groq_api_key: str = Field(default="", validation_alias="GROQ_API_KEY")
    triage_provider: str = Field(default="simulated", validation_alias="TRIAGE_PROVIDER")

    # Comma-separated. Empty by default: the production topology is same-origin
    # (nginx serves the frontend and proxies /api), so the safe baseline is to
    # allow no cross-origin access rather than to allow all of it and hope. Set
    # this only when the frontend is genuinely served from another origin.
    cors_origins_raw: str = Field(default="", validation_alias="CORS_ORIGINS")

    rate_limit_requests: int = Field(default=10, validation_alias="RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: int = Field(default=60, validation_alias="RATE_LIMIT_WINDOW")
    rate_limit_burst: int = Field(default=5, validation_alias="RATE_LIMIT_BURST")

    stats_cache_ttl_seconds: int = Field(default=30, validation_alias="STATS_CACHE_TTL")

    # ---------------------------------------------------------------------------
    # Triage provider configuration (§2.5 items 2-3-5)
    # Both LLMTriage (Groq) and OllamaTriage read these so the values cannot
    # drift apart.  TRIAGE_TIMEOUT is hard-capped at 10 s by the assignment
    # spec; TRIAGE_MAX_RETRIES must be >= 0.
    # ---------------------------------------------------------------------------
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_BASE_URL",
    )
    ollama_model: str = Field(
        default="llama3.2:1b",
        validation_alias="OLLAMA_MODEL",
    )
    triage_timeout: float = Field(
        default=10.0,
        validation_alias="TRIAGE_TIMEOUT",
        le=10.0,
    )
    triage_max_retries: int = Field(
        default=1,
        validation_alias="TRIAGE_MAX_RETRIES",
        ge=0,
    )
    triage_retry_base_delay: float = Field(
        default=0.5,
        validation_alias="TRIAGE_RETRY_BASE_DELAY",
    )
    triage_cache_ttl_hours: int = Field(
        default=24,
        validation_alias="TRIAGE_CACHE_TTL_HOURS",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
