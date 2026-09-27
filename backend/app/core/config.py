from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Every name providers/triage/factory.py knows how to build. The factory ends
# with a catch-all that returns SimulatedTriage for any unrecognised string, so
# without validation a typo such as TRIAGE_PROVIDER=grq runs the stub in
# production while the logs look healthy. This must be a module constant, not a
# class attribute: pydantic turns annotated class attributes into fields, and a
# field is not readable off the class.
TRIAGE_PROVIDERS: frozenset[str] = frozenset(
    {
        "simulated",
        "rules",
        "llm",
        "llm:groq",
        "groq",
        "ollama",
        "llm:ollama",
    }
)


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

    @field_validator("triage_provider")
    @classmethod
    def _check_triage_provider(cls, value: str) -> str:
        normalised = value.strip().lower()
        if normalised not in TRIAGE_PROVIDERS:
            raise ValueError(
                f"TRIAGE_PROVIDER={value!r} is not a known provider. "
                f"Valid values: {', '.join(sorted(TRIAGE_PROVIDERS))}"
            )
        return normalised

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

    # Rate limiter operational switches. The limiter moves to an atomic Redis
    # Lua script so that concurrent requests cannot each read the same token
    # count and all be admitted; that makes the limiter's behaviour under
    # concurrency testable, which is why it needs to be switchable at all.
    rate_limit_enabled: bool = Field(default=True, validation_alias="RATE_LIMIT_ENABLED")
    # Fail closed (reject) when Redis is unreachable. Failing open means a Redis
    # outage silently disables the limiter, which is the wrong default for a
    # public write endpoint.
    rate_limit_fail_closed: bool = Field(
        default=False, validation_alias="RATE_LIMIT_FAIL_CLOSED"
    )

    @field_validator("rate_limit_requests", "rate_limit_burst", "rate_limit_window_seconds")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("rate limit values must be positive")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
