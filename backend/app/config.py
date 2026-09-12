"""StockUp configuration settings loaded from environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    # App
    app_name: str = "StockUp"
    app_env: str = "development"
    app_debug: bool = True
    app_port: int = 8000

    # CORS — comma-separated list of allowed origins. In production this should
    # be set to the public origin(s) that host the SPA, e.g.
    #   CORS_ORIGINS=https://stockup.jmumo.com
    # Localhost defaults keep the Vite dev server working out of the box.
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # Database
    database_url: str = "postgresql://stockup:stockup123@localhost:5432/stockup"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str = "dev-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Data Sources
    yfinance_enabled: bool = True
    scraper_enabled: bool = True
    scraper_base_url: str = "https://afx.kwayisi.org/ngse/"
    marketscreener_enabled: bool = True

    # Internal machine-to-machine API (used by the local price fetcher, which
    # runs on the operator's machine because MarketScreener blocks the VM IP).
    # Leave blank to disable the /api/internal/* endpoints entirely.
    internal_api_token: str = ""

    # AI Financial Enrichment
    ai_provider: str = "openai"  # "openai" or "anthropic"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    ai_model: str = ""  # Leave blank for provider default
    ai_chat_rate_limit_requests: int = 20
    ai_chat_rate_limit_window_seconds: int = 600

    # Annual Report Parser
    pdf_cache_dir: str = "data/annual_reports"
    pdf_download_timeout: int = 60
    pdf_max_size_mb: int = 50

    # Scheduled Jobs
    price_fetch_hour: int = 18
    valuation_calc_hour: int = 19
    alert_eval_hour: int = 19
    alert_eval_minute: int = 30

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
