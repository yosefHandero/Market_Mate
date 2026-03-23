from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SCANNER_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = SCANNER_ROOT / ".env"


def _resolve_database_url(url: str) -> str:
    if not url.startswith("sqlite:///"):
        return url

    raw_path = url.removeprefix("sqlite:///")
    if raw_path in {":memory:", ""}:
        return url

    if raw_path.startswith("/") or (len(raw_path) > 1 and raw_path[1] == ":"):
        return f"sqlite:///{Path(raw_path).resolve().as_posix()}"

    return f"sqlite:///{(SCANNER_ROOT / raw_path).resolve().as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "Market Mate Scanner API"
    app_version: str = "1.0.0"
    app_instance_id: str = Field(default_factory=lambda: f"scanner-{uuid4().hex[:12]}")
    database_url: str = "sqlite:///./market_mate.db"
    cors_allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    public_read_access_enabled: bool = True
    read_api_token: str = ""
    admin_api_token: str = ""
    startup_check_timeout_seconds: int = 5
    health_max_stale_minutes: int = 30
    signal_max_age_minutes: int = 120
    scan_concurrency_limit: int = 8
    provider_timeout_seconds: float = 20.0
    provider_retry_attempts: int = 2
    provider_retry_backoff_seconds: float = 0.5
    scheduler_enabled: bool = False
    scheduler_poll_seconds: int = 15
    scheduler_lease_seconds: int = 120
    scheduler_run_missed_on_startup: bool = True
    cache_dir: str = "./var/cache"
    log_level: str = "INFO"
    log_json: bool = True
    metrics_enabled: bool = True

    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_market_data_url: str = "https://data.alpaca.markets"
    execution_enabled: bool = False
    allow_live_trading: bool = False
    execution_default_time_in_force: str = "day"
    trade_gate_enabled: bool = True
    trade_gate_horizon: Literal["15m", "1h", "1d"] = "1h"
    trade_gate_min_evaluated_count: int = 20
    trade_gate_min_win_rate: float = 55.0
    trade_gate_min_avg_return: float = 0.15
    validation_primary_horizon: Literal["15m", "1h", "1d"] = "1h"
    validation_win_threshold_pct: float = 0.0
    validation_false_positive_threshold_pct: float = 0.0
    trade_gate_allowed_signals: str = "BUY,SELL"
    trade_gate_max_notional: float = 1000.0
    trade_gate_max_qty: float = 5.0
    marketdata_api_token: str = Field(
        default="",
        validation_alias=AliasChoices("MARKETDATA_API_TOKEN", "MarketData_API_token"),
    )
    marketaux_api_token: str = ""
    finnhub_api_key: str = ""
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    coingecko_api_key: str = ""
    alt_fng_api_url: str = "https://api.alternative.me/fng/?limit=1&format=json"
    sec_user_agent: str = "MarketMateScanner your-email@example.com"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_alerts_enabled: bool = True
    alert_score_threshold: float = 65.0
    news_check_score_threshold: float = 60.0
    news_cache_minutes: int = 45

    watchlist: str = "AAPL,MSFT,NVDA,AMD,META,AMZN,GOOGL,TSLA,PLTR,COIN,SPY,QQQ"
    crypto_watchlist: str = "BTC/USD,ETH/USD"
    scan_interval_seconds: int = 300

    @model_validator(mode="after")
    def normalize_paths(self) -> "Settings":
        self.database_url = _resolve_database_url(self.database_url)
        self.cache_dir = str((SCANNER_ROOT / self.cache_dir).resolve())
        if self.is_production and self.database_url.startswith("sqlite"):
            raise ValueError("SQLite is not allowed when APP_ENV=production")
        if self.is_production and not self.admin_api_token:
            raise ValueError("ADMIN_API_TOKEN is required when APP_ENV=production")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() in {"development", "dev", "local", "test"}

    @property
    def cors_allowed_origin_items(self) -> list[str]:
        return [
            item.strip()
            for item in self.cors_allowed_origins.split(",")
            if item.strip()
        ]

    @property
    def cache_dir_path(self) -> Path:
        return Path(self.cache_dir)

    @property
    def admin_auth_required(self) -> bool:
        return self.is_production or bool(self.admin_api_token)

    @property
    def read_auth_required(self) -> bool:
        return (not self.public_read_access_enabled) or bool(self.read_api_token)

    @property
    def watchlist_items(self) -> list[str]:
        return [item.strip().upper() for item in self.watchlist.split(",") if item.strip()]

    @property
    def crypto_watchlist_items(self) -> list[str]:
        return [item.strip().upper() for item in self.crypto_watchlist.split(",") if item.strip()]

    @property
    def trade_gate_allowed_signal_items(self) -> list[str]:
        return [
            item.strip().upper()
            for item in self.trade_gate_allowed_signals.split(",")
            if item.strip()
        ]

    @property
    def database_path(self) -> str:
        if self.database_url.startswith("sqlite:///"):
            return self.database_url.removeprefix("sqlite:///")
        return self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
