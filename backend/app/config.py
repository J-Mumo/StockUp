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
    kenyanstocks_enabled: bool = True

    # AI Financial Enrichment
    ai_provider: str = "openai"  # "openai" or "anthropic"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    ai_model: str = ""  # Leave blank for provider default

    # Scheduled Jobs
    price_fetch_hour: int = 18
    valuation_calc_hour: int = 19
    alert_eval_hour: int = 19
    alert_eval_minute: int = 30

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
