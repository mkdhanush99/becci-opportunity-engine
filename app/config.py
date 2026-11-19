"""Environment-based configuration. All secrets come from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BECCI_", extra="ignore")

    env: str = "development"  # development | test | production
    database_url: str = "sqlite:///./data/becci.db"

    # Security
    secret_key: str = Field(default="CHANGE-ME-dev-only-secret", min_length=16)
    admin_token_ttl_minutes: int = 60 * 8
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://preview.becci.in",
        "https://becci.in",
        "https://www.becci.in",
    ]
    public_rate_limit_per_minute: int = 120
    admin_rate_limit_per_minute: int = 300
    login_rate_limit_per_minute: int = 10

    # Crawling etiquette
    user_agent: str = "Mozilla/5.0 (compatible; BECCI-OpportunityBot/0.1; +https://becci.org.in/opportunity-bot)"
    robots_user_agent: str = "BECCI-OpportunityBot"
    per_domain_min_interval_seconds: float = 3.0
    http_timeout_seconds: float = 25.0
    max_response_bytes: int = 5_000_000
    max_redirects: int = 5
    browser_max_concurrency: int = 2
    browser_navigation_timeout_ms: int = 45_000
    enforce_domain_allowlist: bool = True  # outbound fetches limited to registered source domains

    # Orchestrator
    scan_execution_timeout_seconds: int = 300
    scan_max_attempts: int = 3
    scan_backoff_base_seconds: int = 60
    lock_lease_seconds: int = 900
    scheduler_poll_seconds: int = 60
    closing_soon_days: int = 7

    # Publication policy: never auto-publish by default.
    auto_approve_official_confirmed: bool = False

    # Retention
    raw_capture_retention_days: int = 90
    log_retention_days: int = 180


@lru_cache
def get_settings() -> Settings:
    return Settings()
