from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator

MarketStatus = Literal["bullish", "neutral", "bearish"]
BrokerName = Literal["alpaca"]
OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
JournalDecision = Literal["took", "skipped", "watching"]
DecisionSignal = Literal["BUY", "SELL", "HOLD"]
AssetType = Literal["stock", "crypto"]



class OptionsFlowSnapshot(BaseModel):
    expiry: str | None = None
    call_volume: int = 0
    put_volume: int = 0
    call_open_interest: int = 0
    put_open_interest: int = 0
    put_call_volume_ratio: float = 0.0
    unusual_contract_count: int = 0
    bullish_score: float = 0.0
    bearish_score: float = 0.0
    summary: str = "No options data."


class GateCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class ErrorDetails(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict = {}


class ErrorResponse(BaseModel):
    detail: str
    error: ErrorDetails


class ScanResult(BaseModel):
    ticker: str
    asset_type: AssetType = "stock"
    score: float
    calibrated_confidence: float = 0.0
    calibration_source: str = "raw"
    buy_score: float = 0.0
    sell_score: float = 0.0
    decision_signal: DecisionSignal = "HOLD"
    scoring_version: str = "v2-directional"
    explanation: str
    price: float
    price_change_pct: float
    relative_volume: float
    sentiment_score: float
    filing_flag: bool
    breakout_flag: bool
    market_status: MarketStatus
    sector_strength_score: float
    relative_strength_pct: float = 0.0
    options_flow_score: float = 0.0
    options_flow_summary: str = "No options signal."
    options_flow_bullish: bool = False
    options_call_put_ratio: float = 0.0
    alert_sent: bool = False
    news_checked: bool = False
    news_source: str = "none"
    news_cache_label: str | None = None
    signal_label: str = "weak"
    data_quality: str = "ok"
    volatility_regime: str = "normal"
    benchmark_ticker: str | None = None
    benchmark_change_pct: float | None = None
    gate_passed: bool = False
    gate_reason: str = "Signal gate not evaluated."
    gate_checks: list[GateCheck] = []
    coingecko_price_change_pct_24h: float | None = None
    coingecko_market_cap_rank: int | None = None
    fear_greed_value: int | None = None
    fear_greed_label: str | None = None
    provider_status: str = "ok"
    provider_warnings: list[str] = []
    created_at: datetime


class ScanRun(BaseModel):
    run_id: str
    created_at: datetime
    market_status: MarketStatus
    scan_count: int
    watchlist_size: int
    alerts_sent: int = 0
    fear_greed_value: int | None = None
    fear_greed_label: str | None = None
    results: list[ScanResult]


class HealthResponse(BaseModel):
    ok: bool
    env: str
    app_version: str | None = None
    ready: bool = False
    live: bool = True
    schema_ok: bool = True
    missing_schema_items: list[str] = []
    scheduler_running: bool = False
    last_scan_at: datetime | None = None
    request_id: str | None = None


class MetricsResponse(BaseModel):
    counters: dict[str, int]
    durations: dict[str, dict]


class OrderPreviewRequest(BaseModel):
    ticker: str
    side: OrderSide
    qty: float = Field(gt=0)
    order_type: OrderType = "market"
    limit_price: float | None = Field(default=None, gt=0)
    preview_audit_id: int | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_limit_order_price(self) -> "OrderPreviewRequest":
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")
        return self


class OrderPreviewResponse(BaseModel):
    broker: BrokerName = "alpaca"
    ticker: str
    side: OrderSide
    qty: float
    order_type: OrderType
    notional_estimate: float
    latest_price: float
    time_in_force: str
    warnings: list[str] = []
    trade_gate: TradeEligibility | None = None
    execution_audit_id: int | None = None


class OrderPlaceRequest(OrderPreviewRequest):
    dry_run: bool = False


class OrderPlaceResponse(BaseModel):
    ok: bool
    broker: BrokerName = "alpaca"
    submitted: bool
    dry_run: bool
    message: str
    idempotency_key: str | None = None
    order_id: str | None = None
    status: str | None = None
    raw: dict | None = None
    trade_gate: TradeEligibility | None = None
    execution_audit_id: int | None = None

class JournalEntryCreateRequest(BaseModel):
    ticker: str
    run_id: str | None = None
    decision: JournalDecision
    entry_price: float | None = Field(default=None, gt=0)
    exit_price: float | None = Field(default=None, gt=0)
    pnl_pct: float | None = None
    notes: str = ""
    signal_label: str | None = None
    score: float | None = None
    news_source: str | None = None



class JournalEntryResponse(BaseModel):
    id: int
    ticker: str
    run_id: str | None = None
    decision: JournalDecision
    entry_price: float | None = None
    exit_price: float | None = None
    pnl_pct: float | None = None
    notes: str = ""
    created_at: datetime
    signal_label: str | None = None
    score: float | None = None
    news_source: str | None = None


class JournalEntryUpdateRequest(BaseModel):
    decision: JournalDecision | None = None
    entry_price: float | None = Field(default=None, gt=0)
    exit_price: float | None = Field(default=None, gt=0)
    pnl_pct: float | None = None
    notes: str | None = None
class JournalAnalyticsBucket(BaseModel):
    key: str
    total: int
    open_count: int
    closed_count: int
    win_rate: float | None = None
    avg_pnl_pct: float | None = None


class JournalAnalyticsResponse(BaseModel):
    total_entries: int
    took_count: int
    skipped_count: int
    watching_count: int
    open_trades: int
    closed_trades: int
    win_rate: float | None = None
    avg_pnl_pct: float | None = None
    by_signal_label: list[JournalAnalyticsBucket]
    by_news_source: list[JournalAnalyticsBucket]
    by_ticker: list[JournalAnalyticsBucket]


class DecisionRow(BaseModel):
    symbol: str
    asset_type: AssetType = "stock"
    signal: DecisionSignal
    confidence: float
    calibration_source: str = "raw"
    short_metric_summary: str
    last_updated: datetime


class SignalOutcome(BaseModel):
    id: int
    run_id: str
    symbol: str
    asset_type: AssetType = "stock"
    signal: DecisionSignal
    confidence: float
    calibrated_confidence: float | None = None
    calibration_source: str | None = None
    raw_score: float | None = None
    score_band: str | None = None
    scoring_version: str | None = None
    market_status: MarketStatus | None = None
    buy_score: float | None = None
    sell_score: float | None = None
    signal_label: str | None = None
    gate_passed: bool | None = None
    gate_reason: str | None = None
    news_source: str | None = None
    relative_volume: float | None = None
    price_change_pct: float | None = None
    relative_strength_pct: float | None = None
    options_flow_score: float | None = None
    options_flow_bullish: bool | None = None
    volatility_regime: str | None = None
    data_quality: str | None = None
    benchmark_change_pct: float | None = None
    entry_price: float
    generated_at: datetime
    price_after_15m: float | None = None
    return_after_15m: float | None = None
    evaluated_at_15m: datetime | None = None
    status_15m: str = "pending"
    price_after_1h: float | None = None
    return_after_1h: float | None = None
    evaluated_at_1h: datetime | None = None
    status_1h: str = "pending"
    price_after_1d: float | None = None
    return_after_1d: float | None = None
    evaluated_at_1d: datetime | None = None
    status_1d: str = "pending"


class SignalOutcomePerformanceBucket(BaseModel):
    key: str
    total_signals: int
    evaluated_15m_count: int
    win_rate_15m: float | None = None
    avg_return_15m: float | None = None
    evaluated_1h_count: int
    win_rate_1h: float | None = None
    avg_return_1h: float | None = None
    evaluated_1d_count: int
    win_rate_1d: float | None = None
    avg_return_1d: float | None = None


class SignalOutcomeSummary(BaseModel):
    total_signals: int
    pending_15m_count: int
    pending_1h_count: int
    pending_1d_count: int
    overall: SignalOutcomePerformanceBucket
    by_signal: list[SignalOutcomePerformanceBucket]
    by_confidence_bucket: list[SignalOutcomePerformanceBucket]
    by_signal_confidence_bucket: list[SignalOutcomePerformanceBucket]
    by_signal_score_bucket: list[SignalOutcomePerformanceBucket]


class TradeEligibility(BaseModel):
    ticker: str
    asset_type: AssetType = "stock"
    requested_side: OrderSide
    required_signal: DecisionSignal
    signal_run_id: str | None = None
    signal_generated_at: datetime | None = None
    latest_signal: DecisionSignal | None = None
    confidence: float | None = None
    calibration_source: str | None = None
    raw_score: float | None = None
    signal_age_minutes: float | None = None
    confidence_bucket: str | None = None
    raw_score_bucket: str | None = None
    score_band: str | None = None
    horizon: str
    allowed: bool
    reason: str
    notional_estimate: float
    qty: float
    signal_evaluated_count: int | None = None
    signal_win_rate: float | None = None
    signal_avg_return: float | None = None
    score_band_evaluated_count: int | None = None
    score_band_win_rate: float | None = None
    score_band_avg_return: float | None = None
    gate_checks: list[GateCheck] = []


class TradeEligibilityResponse(BaseModel):
    eligibility: TradeEligibility


class ValidationBucket(BaseModel):
    key: str
    total_signals: int
    evaluated_count: int
    pending_count: int
    win_count: int
    loss_count: int
    false_positive_count: int
    win_rate: float | None = None
    avg_return: float | None = None
    median_return: float | None = None
    avg_win_return: float | None = None
    avg_loss_return: float | None = None
    expectancy: float | None = None
    false_positive_rate: float | None = None


class ValidationSummary(BaseModel):
    primary_horizon: Literal["15m", "1h", "1d"]
    win_threshold_pct: float
    false_positive_threshold_pct: float
    total_signals: int
    evaluated_count: int
    pending_count: int
    overall: ValidationBucket
    by_signal: list[ValidationBucket]
    by_score_band: list[ValidationBucket]
    by_signal_label: list[ValidationBucket]
    by_market_status: list[ValidationBucket]
    by_news_source: list[ValidationBucket]
    by_volatility_regime: list[ValidationBucket]
    by_data_quality: list[ValidationBucket]
    by_options_flow_bias: list[ValidationBucket]
    by_gate_status: list[ValidationBucket]
    by_asset_type: list[ValidationBucket]


class ThresholdSweepRow(BaseModel):
    min_evaluated_count: int
    min_win_rate: float
    min_avg_return: float
    score_band_required: bool
    kept_signals: int
    blocked_signals: int
    kept_rate: float
    win_rate: float | None = None
    avg_return: float | None = None
    expectancy: float | None = None
    false_positive_rate: float | None = None


class ThresholdSweepResponse(BaseModel):
    primary_horizon: Literal["15m", "1h", "1d"]
    win_threshold_pct: float
    false_positive_threshold_pct: float
    baseline: ValidationBucket
    candidates: list[ThresholdSweepRow]


class CohortValidationSummary(BaseModel):
    cohort: str
    total_signals: int
    evaluated_count: int
    pending_count: int
    win_rate: float | None = None
    avg_return: float | None = None
    expectancy: float | None = None
    false_positive_rate: float | None = None


class ExecutionAlignmentResponse(BaseModel):
    primary_horizon: Literal["15m", "1h", "1d"]
    win_threshold_pct: float
    false_positive_threshold_pct: float
    all_signals: CohortValidationSummary
    taken_trades: CohortValidationSummary
    skipped_or_watched: CohortValidationSummary
    blocked_previews: CohortValidationSummary