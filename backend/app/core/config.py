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

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
