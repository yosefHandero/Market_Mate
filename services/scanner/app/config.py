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
    cors_allowed_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3001,http://127.0.0.1:3001"
    )
    public_read_access_enabled: bool = False
    read_api_token: str = ""
    admin_api_token: str = ""
    startup_check_timeout_seconds: int = 5
    health_max_stale_minutes: int = 30
    stale_signal_max_age_minutes: int = 10
    signal_buy_threshold: float = 52.0
    signal_sell_threshold: float = 52.0
    signal_margin: float = 6.0
    signal_crypto_buy_threshold: float = 52.0
    signal_crypto_sell_threshold: float = 52.0
    signal_crypto_margin: float = 6.0
    trust_recent_window_days: int = 14
    scan_concurrency_limit: int = 8
    provider_timeout_seconds: float = 20.0
    provider_retry_attempts: int = 2
    provider_retry_backoff_seconds: float = 0.5
    # Per-bar staleness threshold. Higher than health_max_stale_minutes because
    # delayed/5-minute Alpaca bars routinely land ~31 min old without being unreliable.
    # Scan-run freshness still uses health_max_stale_minutes (30).
    provider_max_bar_age_minutes: int = 45
    alpaca_latest_data_cache_seconds: int = 5
    sec_company_tickers_cache_seconds: int = 21600
    sec_filings_cache_seconds: int = 900
    sec_company_facts_cache_seconds: int = 3600
    coingecko_cache_seconds: int = 120
    fear_greed_cache_seconds: int = 300
    options_flow_cache_seconds: int = 600
    binance_cache_seconds: int = 5
    deribit_cache_seconds: int = 30
    fred_cache_seconds: int = 3600
    defillama_cache_seconds: int = 900
    scheduler_enabled: bool = False
    scheduler_poll_seconds: int = 15
    scheduler_lease_seconds: int = 120
    worker_heartbeat_stale_seconds: int = 90
    scheduler_run_missed_on_startup: bool = True
    cache_dir: str = "./var/cache"
    log_level: str = "INFO"
    log_json: bool = True
    metrics_enabled: bool = True
    paper_loop_enabled: bool = False
    paper_loop_phase: Literal["disabled", "shadow", "limited", "broad"] = "disabled"
    paper_loop_kill_switch: bool = False
    paper_loop_symbol_allowlist: str = ""
    paper_loop_target_notional_usd: float = 100.0
    paper_loop_max_actions_per_cycle: int = 2
    paper_loop_max_requests_per_hour: int = 6
    paper_loop_max_requests_per_day: int = 20
    paper_loop_max_requests_per_symbol_window: int = 1
    paper_loop_symbol_window_seconds: int = 21600
    paper_loop_symbol_cooldown_minutes: int = 360
    paper_loop_same_side_repeat_requires_delta: bool = True
    paper_loop_opposite_side_requires_unwound: bool = True
    paper_loop_min_confidence_delta: float = 5.0
    paper_loop_claim_ttl_seconds: int = 90
    paper_loop_retry_max_attempts: int = 3
    paper_loop_retry_base_seconds: int = 300
    paper_loop_retry_jitter_ratio: float = 0.2
    paper_loop_breaker_failures_to_open: int = 3
    paper_loop_breaker_failure_window_minutes: int = 15
    paper_loop_breaker_open_minutes: int = 30

    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_market_data_url: str = "https://data.alpaca.markets"
    # Paper-only build: these two flags must always be false. They are retained
    # solely so the process can refuse to start when either is set truthy (see
    # forbid_live_execution). There is no broker order-submission code to enable.
    execution_enabled: bool = False
    allow_live_trading: bool = False
    execution_default_time_in_force: str = "day"
    trade_gate_enabled: bool = True
    trade_gate_horizon: Literal["15m", "1h", "1d", "1w"] = "1w"
    trade_gate_min_evaluated_count: int = 20
    trade_gate_min_win_rate: float = 55.0
    trade_gate_min_avg_return: float = 0.15
    # Crypto BUY is poorer and underpowered in the friction/out-of-sample evidence,
    # so it must clear a higher sample bar before it is allowed past review-only.
    # Stricter only; never loosens the global BUY gate.
    trade_gate_crypto_buy_min_evaluated_count: int = 30
    calibration_min_signal_samples: int = 20
    calibration_min_score_band_samples: int = 10
    outcome_report_min_evaluated_per_horizon: int = 20
    outcome_baseline_min_evaluated_per_horizon: int = 20
    outcome_baseline_min_mean_return_pct: float = 0.0
    outcome_evaluation_batch_limit: int = 2000
    track_hold_outcomes: bool = True
    validation_primary_horizon: Literal["15m", "1h", "1d", "1w"] = "1w"
    validation_win_threshold_pct: float = 0.0
    validation_false_positive_threshold_pct: float = 0.0
    validation_min_sample_size: int = 30
    stock_slippage_bps: float = 5.0
    stock_spread_bps: float = 2.0
    stock_fee_bps: float = 0.0
    crypto_slippage_bps: float = 12.0
    crypto_spread_bps: float = 6.0
    crypto_fee_bps: float = 10.0
    replay_default_interval_minutes: int = 60
    replay_default_warmup_bars: int = 30
    weekly_primary_horizon_enabled: bool = True
    weekly_daily_lookback_bars_default: int = 500
    weekly_daily_lookback_bars_min: int = 250
    weekly_daily_lookback_bars_preferred: int = 500
    weekly_daily_lookback_bars_max: int = 1250
    weekly_daily_bar_cache_ttl_seconds: int = 86400
    weekly_trust_window_days: int = 730
    weekly_pattern_gate_min_historical_samples: int = 30
    weekly_pattern_gate_min_backfilled_samples: int = 20
    weekly_pattern_gate_min_live_forward_samples: int = 20
    weekly_pattern_gate_min_out_of_sample_samples: int = 10
    weekly_pattern_gate_min_win_rate: float = 52.0
    weekly_pattern_gate_min_avg_return: float = 0.10
    # Fraction of the live watchlist whose real forward outcomes are tagged as an
    # out-of-sample holdout (never used for calibration). This lets the required
    # out-of-sample evidence track accrue automatically from genuine forward data,
    # kept strictly separate from the in-sample live_paper_forward track. 0 disables.
    weekly_out_of_sample_holdout_ratio: float = 0.25
    weekly_forward_days: int = 7
    weekly_forward_tolerance_days: int = 3
    weekly_hold_return_tolerance_pct: float = 1.0
    top_pick_limit: int = 5
    upside_prob_shrinkage_k: float = 20.0
    # Apply the research-window reliability map from the latest walk-forward proof
    # run to the live upside probability (out-of-sample-safe; no live data used to
    # calibrate). Disabled falls back to the raw shrunk hit-rate probability.
    weekly_apply_calibration_map: bool = True
    # Enforce the proof-grade BUY-candidate quality gate on the live weekly path so
    # served candidates match the proven ones. Fails closed to fewer candidates.
    weekly_apply_proof_candidate_filters: bool = True
    weekly_daily_bar_max_age_days_stock: int = 5
    weekly_daily_bar_max_age_days_crypto: int = 2
    wf_holdout_days: int = 7
    # Historical walk-forward proof engine (daily-bar weekly-pattern layer).
    proof_target_years: int = 3
    proof_min_years: int = 2
    proof_max_years: int = 5
    proof_holdout_months: int = 9
    # Validation segment sits immediately before the final holdout. Thresholds and
    # filters may be tuned on research+validation; the holdout stays read-only
    # evidence. This makes the research/validation/holdout separation explicit.
    proof_validation_months: int = 3
    proof_lookback_context_months_min: int = 6
    proof_lookback_context_months_max: int = 24
    # Decision-side nested sampling step: how densely each policy's own
    # hit-rate construction samples history. Part of decision identity.
    proof_step_days: int = 7
    # Ruler-side walk-forward evaluation schedule: the step between replay
    # dates the proof engine stands at. Must clear the full forward window
    # (forward + tolerance) so consecutive evaluated predictions never share
    # forward horizons (overlap inflates sample counts, understates drawdown).
    proof_eval_step_days: int = 10
    proof_top_n_per_asset: int = 5
    proof_min_pattern_samples: int = 12
    # Persistent historical bar store fetch cap, kept separate from the live-scan
    # lookback trim so multi-year proof history can be pulled without changing
    # live scan behaviour or data-quality gates.
    proof_daily_lookback_bars_max: int = 1300
    proof_fetch_chunk_days: int = 3650
    # Pilot-ready verdict thresholds (report-only; never auto-enables execution).
    proof_pilot_min_predictions_per_asset: int = 120
    proof_pilot_min_upside_hit_rate_pct: float = 55.0
    proof_pilot_max_calibration_gap_pct: float = 10.0
    proof_pilot_min_after_friction_return_pct: float = 0.0
    proof_pilot_max_drawdown_pct: float = 25.0
    proof_pilot_min_exit_window_helped_rate_pct: float = 50.0
    proof_pilot_min_confidence_discrimination_pct: float = 0.0
    # Statistical-solidity thresholds for the paper-readiness confidence view. These
    # do NOT gate real-money trust (which stays blocked); they certify the proof
    # signal is real rather than noise before paper readiness is called complete.
    proof_min_regime_samples: int = 8
    proof_pilot_min_information_coefficient: float = 0.02
    proof_pilot_min_ic_t_stat: float = 2.0
    proof_pilot_require_edge_significant: bool = True
    proof_pilot_require_cross_regime_edge: bool = True
    # Prediction-quality uplift: benchmarks, filters, EV gate, exit-window sizing.
    proof_benchmark_random_draws: int = 25
    proof_benchmark_random_seed: int = 1729
    proof_momentum_lookback_days: int = 63
    proof_min_expected_value_pct: float = 0.0
    proof_min_pattern_edge_pct: float = 2.0
    proof_rsi_overbought: float = 80.0
    proof_atr_lookback_days: int = 14
    proof_atr_target_mult: float = 2.5
    proof_atr_stop_mult: float = 1.5
    proof_confidence_shrinkage_k: float = 20.0
    proof_pilot_min_edge_vs_buy_hold_pct: float = 0.0
    proof_volume_lookback_days: int = 20
    proof_min_volume_median_ratio: float = 0.5
    proof_require_buy_hold_baseline: bool = True
    # BUY-only decision product: SELL is a detector classification, never an
    # actionable/executable decision. Do not re-add SELL here.
    trade_gate_allowed_signals: str = "BUY"
    # Champion policy id. ``hybrid_legacy`` is always allowed. Any other id is
    # applied only when the promotion report clears its gates.
    brain_champion_policy_id: str = "hybrid_legacy"
    brain_promotion_min_pairs: int = 40
    brain_min_wilson_lb_pct: float = 50.0
    trade_gate_max_notional: float = 1000.0
    trade_gate_max_qty: float = 5.0
    portfolio_risk_enabled: bool = True
    portfolio_max_daily_notional: float = 2500.0
    portfolio_max_symbol_notional: float = 1000.0
    portfolio_max_asset_type_notional: float = 2000.0
    portfolio_daily_loss_limit_pct: float = -2.0
    portfolio_max_loss_streak: int = 3
    portfolio_max_drawdown_pct: float = 5.0
    require_readyz_for_execution: bool = True
    marketdata_api_token: str = Field(
        default="",
        validation_alias=AliasChoices("MARKETDATA_API_TOKEN", "MarketData_API_token"),
    )
    marketdata_options_enabled: bool = False
    marketaux_api_token: str = ""
    finnhub_api_key: str = ""
    polygon_api_key: str = ""
    polygon_base_url: str = "https://api.polygon.io"
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    coingecko_api_key: str = ""
    coinbase_ws_enabled: bool = True
    coinbase_ws_url: str = "wss://advanced-trade-ws.coinbase.com"
    coinbase_ws_channel: str = "ticker"
    coinbase_ws_products: str = "BTC-USD,ETH-USD"
    coinbase_ws_reconnect_base_seconds: float = 1.0
    coinbase_ws_reconnect_max_seconds: float = 30.0
    coinbase_ws_snapshot_stale_seconds: int = 150
    coinbase_ws_log_messages: bool = False
    alt_fng_api_url: str = "https://api.alternative.me/fng/?limit=1&format=json"
    sec_user_agent: str = "MarketMateScanner your-email@example.com"
    scanner_strategy_variant: str = "layered-v4"
    binance_enabled: bool = False
    deribit_enabled: bool = False
    sec_enhanced_enabled: bool = False
    fred_enabled: bool = False
    internal_breadth_enabled: bool = False
    defillama_enabled: bool = False
    binance_base_url: str = "https://api.binance.com"
    deribit_base_url: str = "https://www.deribit.com/api/v2/public"
    fred_csv_url: str = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    defillama_base_url: str = "https://api.llama.fi"
    defillama_stablecoins_url: str = "https://stablecoins.llama.fi/stablecoins?includePrices=true"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_alerts_enabled: bool = True
    alert_score_threshold: float = 65.0
    news_trigger_abs_move_pct: float = 1.25
    news_cache_minutes: int = 45

    watchlist: str = (
        "AAPL,MSFT,NVDA,AMD,META,AMZN,GOOGL,AVGO,CRM,ORCL,CSCO,INTC,"
        "TSLA,NFLX,DIS,"
        "JPM,BAC,GS,MS,V,MA,BRK.B,"
        "UNH,JNJ,LLY,MRK,ABBV,"
        "XOM,CVX,"
        "CAT,DE,UPS,"
        "WMT,PG,KO,PEP,HD,NKE,MCD,"
        "LIN,NEE,"
        "T,VZ,"
        "AMAT,LRCX,"
        "COIN,PLTR,"
        "SPY,QQQ"
    )
    crypto_watchlist: str = (
        "BTC/USD,ETH/USD,SOL/USD,XRP/USD,DOGE/USD,"
        "ADA/USD,AVAX/USD,LINK/USD,DOT/USD,LTC/USD,"
        "UNI/USD,SHIB/USD,BCH/USD,AAVE/USD,POL/USD,"
        "PEPE/USD,FIL/USD,GRT/USD,RENDER/USD,BONK/USD"
    )
    scan_interval_seconds: int = 300

    @model_validator(mode="after")
    def forbid_live_execution(self) -> "Settings":
        # Structural paper-only guarantee: any process (API, worker, scripts,
        # tests) that loads settings with a live-execution flag set fails fast
        # here rather than relying on a single startup assertion. There is no
        # broker order-submission code path that these flags could enable.
        if self.execution_enabled or self.allow_live_trading:
            raise ValueError(
                "Paper-only build enforcement: EXECUTION_ENABLED and "
                "ALLOW_LIVE_TRADING must be false. Live broker submission is "
                "not implemented and cannot be enabled."
            )
        return self

    @model_validator(mode="after")
    def enforce_non_overlapping_proof_steps(self) -> "Settings":
        # Consecutive walk-forward predictions must not share forward windows.
        # step_days < forward_days creates overlapping horizons that inflate
        # sample counts and understate drawdown; refuse that configuration.
        if int(self.proof_step_days) < int(self.weekly_forward_days):
            raise ValueError(
                "PROOF_STEP_DAYS must be >= WEEKLY_FORWARD_DAYS so walk-forward "
                "prediction horizons do not overlap."
            )
        # The ruler's replay-date schedule must clear the entire resolution
        # window (forward days + resolution tolerance): a bar used to resolve
        # one prediction must not fall inside the next prediction's horizon.
        if int(self.proof_eval_step_days) < int(self.weekly_forward_days) + int(
            self.weekly_forward_tolerance_days
        ):
            raise ValueError(
                "PROOF_EVAL_STEP_DAYS must be >= WEEKLY_FORWARD_DAYS + "
                "WEEKLY_FORWARD_TOLERANCE_DAYS so evaluated walk-forward "
                "predictions are truly non-overlapping."
            )
        return self

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
    def effective_top_pick_limit(self) -> int:
        return max(3, min(5, int(self.top_pick_limit)))

    @property
    def proof_effective_top_n_per_asset(self) -> int:
        return max(3, min(5, int(self.proof_top_n_per_asset)))

    @property
    def proof_effective_years(self) -> int:
        target = int(self.proof_target_years)
        return max(int(self.proof_min_years), min(int(self.proof_max_years), target))

    @property
    def trade_gate_allowed_signal_items(self) -> list[str]:
        return [
            item.strip().upper()
            for item in self.trade_gate_allowed_signals.split(",")
            if item.strip()
        ]

    @property
    def coinbase_ws_product_items(self) -> list[str]:
        return [item.strip().upper() for item in self.coinbase_ws_products.split(",") if item.strip()]

    @property
    def paper_loop_symbol_allowlist_items(self) -> list[str]:
        return [item.strip().upper() for item in self.paper_loop_symbol_allowlist.split(",") if item.strip()]

    @property
    def database_path(self) -> str:
        if self.database_url.startswith("sqlite:///"):
            return self.database_url.removeprefix("sqlite:///")
        return self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
