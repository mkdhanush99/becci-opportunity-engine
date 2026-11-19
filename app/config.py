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

    # Orchestrator & Autonomous Scheduler
    scan_execution_timeout_seconds: int = 300
    scan_max_attempts: int = 3
    scan_backoff_base_seconds: int = 60
    lock_lease_seconds: int = 900
    scheduler_poll_seconds: int = 60
    closing_soon_days: int = 7
    target_states: list[str] = ["National", "Andhra Pradesh", "Telangana"]
    auto_scheduler_enabled: bool = True
    auto_scan_interval_minutes: int = 60
    cron_secret: str = "becci-cloud-cron-secret-2026"

    # Autonomous Cadences (hours)
    cadence_tenders_hours: int = 3       # GeM, CPPP, Railways, Defence, PSUs (every 3h)
    cadence_jobs_hours: int = 6          # Govt recruitment & Private jobs (every 6h)
    cadence_funding_hours: int = 12      # SIDBI, NBCFDC, MSME finance (every 12h)
    cadence_schemes_hours: int = 24      # BC/OBC central & state schemes (every 24h)

    # Apify Integration (Token injected via Azure AppSettings APIFY_API_TOKEN or BECCI_APIFY_API_TOKEN)
    apify_api_token: str = Field(default="", validation_alias="APIFY_API_TOKEN")
    apify_webhook_secret: str = "b3cc1_ap1fy_w3bh00k_2026"
    apify_default_timeout_seconds: int = 180
    apify_default_memory_mbytes: int = 512

    # DeepSeek AI Intelligence Layer
    deepseek_api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_default_model: str = "deepseek-flash"
    deepseek_advanced_model: str = "deepseek-v4-pro"
    deepseek_daily_spend_limit_usd: float = 2.0
    deepseek_monthly_spend_limit_usd: float = 25.0
    deepseek_max_tokens: int = 1000

    # Publication policy: never auto-publish by default.
    auto_approve_official_confirmed: bool = False

    # Retention
    raw_capture_retention_days: int = 90
    log_retention_days: int = 180


@lru_cache
def get_settings() -> Settings:
    return Settings()
