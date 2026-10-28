"""Runtime configuration loaded from environment variables (and a local .env).

Provider endpoints are constants, not configuration: an attacker who can set
environment variables should not be able to redirect provider traffic.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

OPENAI_BASE_URL = "https://api.openai.com/v1"
TAVILY_BASE_URL = "https://api.tavily.com"

PROMPT_VERSION = "2026-10-28.3"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True)

    env: Literal["development", "test", "production"] = Field("development", alias="PREDIXION_ENV")
    mode: Literal["live", "fixture"] = Field("fixture", alias="PREDIXION_MODE")
    host: str = Field("127.0.0.1", alias="PREDIXION_HOST")
    port: int = Field(8000, alias="PREDIXION_PORT")

    openai_api_key: SecretStr | None = Field(None, alias="OPENAI_API_KEY")
    tavily_api_key: SecretStr | None = Field(None, alias="TAVILY_API_KEY")

    research_model: str = Field("gpt-6.1-terra", alias="RESEARCH_MODEL")
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high"] | None = Field("low", alias="RESEARCH_REASONING_EFFORT")
    # Standard-tier list prices for gpt-6.1-terra, checked 2026-10-28. Re-verify before relying on cost ceilings.
    model_input_usd_per_mtok: float = Field(1.0, alias="MODEL_INPUT_USD_PER_MTOK", ge=0)
    model_output_usd_per_mtok: float = Field(5.0, alias="MODEL_OUTPUT_USD_PER_MTOK", ge=0)
    tavily_usd_per_credit: float = Field(0.008, alias="TAVILY_USD_PER_CREDIT", ge=0)

    # Per-run limits (initial engineering settings, not benchmark claims).
    max_rounds: int = Field(2, alias="MAX_ROUNDS", ge=1, le=4)
    max_queries_per_round: int = Field(3, alias="MAX_QUERIES_PER_ROUND", ge=1, le=5)
    max_pages_per_run: int = Field(8, alias="MAX_PAGES_PER_RUN", ge=1, le=20)
    max_concurrency: int = Field(3, alias="MAX_CONCURRENCY", ge=1, le=8)
    max_model_attempts: int = Field(8, alias="MAX_MODEL_ATTEMPTS", ge=3, le=20)
    max_repair_cycles: int = Field(1, alias="MAX_REPAIR_CYCLES", ge=0, le=2)
    run_deadline_s: float = Field(120.0, alias="RUN_DEADLINE_S", ge=10, le=900)
    finalize_reserve_s: float = Field(20.0, alias="FINALIZE_RESERVE_S", ge=2, le=120)
    max_tokens_per_run: int = Field(150_000, alias="MAX_TOKENS_PER_RUN", ge=1_000)
    max_cost_usd_per_run: float = Field(0.60, alias="MAX_COST_USD_PER_RUN", gt=0)
    max_output_tokens: int = Field(6_000, alias="MAX_OUTPUT_TOKENS", ge=256)

    model_timeout_s: float = Field(60.0, alias="MODEL_TIMEOUT_S", gt=0)
    search_timeout_s: float = Field(15.0, alias="SEARCH_TIMEOUT_S", gt=0)
    extract_timeout_s: float = Field(30.0, alias="EXTRACT_TIMEOUT_S", gt=0)
    retry_max_attempts: int = Field(3, alias="RETRY_MAX_ATTEMPTS", ge=1, le=5)

    # Service limits.
    max_concurrent_runs: int = Field(4, alias="MAX_CONCURRENT_RUNS", ge=1)
    max_queued_runs: int = Field(16, alias="MAX_QUEUED_RUNS", ge=0)
    max_sse_per_run: int = Field(5, alias="MAX_SSE_PER_RUN", ge=1)
    max_sse_total: int = Field(50, alias="MAX_SSE_TOTAL", ge=1)
    max_events_per_run: int = Field(400, alias="MAX_EVENTS_PER_RUN", ge=50)

    db_path: str = Field("data/predixion.sqlite3", alias="PREDIXION_DB_PATH")
    retention_days: float = Field(7.0, alias="RUN_RETENTION_DAYS", gt=0)

    auth_mode: Literal["none", "token"] = Field("none", alias="AUTH_MODE")
    # Comma-separated "user_id:sha256_hex_of_token" pairs. Only hashes live in config.
    api_token_hashes: SecretStr | None = Field(None, alias="API_TOKEN_HASHES")
    # For a container that binds 0.0.0.0 but is published only on host loopback.
    allow_unauthenticated_bind: bool = Field(False, alias="ALLOW_UNAUTHENTICATED_BIND")
    cors_origins: str = Field("http://127.0.0.1:5173,http://localhost:5173", alias="CORS_ORIGINS")
    serve_frontend_dir: str | None = Field(None, alias="SERVE_FRONTEND_DIR")

    enable_fault_injection: bool = Field(False, alias="ENABLE_FAULT_INJECTION")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    log_content: bool = Field(False, alias="LOG_CONTENT")

    cache_ttl_search_s: float = Field(3600.0, alias="CACHE_TTL_SEARCH_S", ge=0)
    cache_ttl_extract_s: float = Field(86_400.0, alias="CACHE_TTL_EXTRACT_S", ge=0)
    cache_max_entries: int = Field(512, alias="CACHE_MAX_ENTRIES", ge=0)

    @field_validator("openai_api_key", "tavily_api_key", "api_token_hashes", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("reasoning_effort", mode="before")
    @classmethod
    def _blank_effort(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def live_available(self) -> bool:
        return self.openai_api_key is not None and self.tavily_api_key is not None

    def missing_live_credentials(self) -> list[str]:
        missing = []
        if self.openai_api_key is None:
            missing.append("OPENAI_API_KEY")
        if self.tavily_api_key is None:
            missing.append("TAVILY_API_KEY")
        return missing

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def fault_injection_allowed(self) -> bool:
        return self.enable_fault_injection and self.env != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
