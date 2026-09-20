from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

MarketStatus = Literal["bullish", "neutral", "bearish"]
BrokerName = Literal["alpaca"]
OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
JournalDecision = Literal["took", "skipped", "watching"]
DecisionSignal = Literal["BUY", "SELL", "HOLD"]
AssetType = Literal["stock", "crypto"]
ProviderStatus = Literal["ok", "degraded", "critical"]
EvidenceQuality = Literal["high", "moderate", "low", "degraded"]
EvidenceGrade = Literal["Strong", "Mixed", "Weak"]
ExecutionEligibility = Literal["eligible", "blocked", "not_applicable", "review"]
DataGrade = Literal["decision", "research", "degraded"]
RecommendedAction = Literal["ignore", "review", "preview", "dry_run", "blocked"]
ReadinessBand = Literal["high", "watch", "low", "none"]
OutcomeHorizon = Literal["15m", "1h", "1d", "1w"]
# "live_holdout" is the current name for the live-forward ticker-hash holdout;
# "out_of_sample" is its legacy stored spelling (still readable, never rewritten).
SampleSource = Literal[
    "historical", "backfilled_replay", "live_paper_forward", "out_of_sample", "live_holdout"
]
WeeklyEvidenceBasis = Literal["historical_only", "live_forward_proven", "mixed", "insufficient"]
WeeklyDirectionalBias = Literal["bullish", "bearish", "neutral"]
JournalActionState = Literal["watching", "reviewed", "took", "skipped"]
AutomationPhase = Literal["disabled", "shadow", "limited", "broad"]
PaperPositionStatus = Literal["open", "closed"]
AutomationIncidentClass = Literal[
    "duplicate",
    "stale_signal",
    "budget_bypass",
    "breaker_misbehavior",
    "reconciliation_mismatch",
]
AutomationIntentStatus = Literal[
    "pending",
    "claimed",
    "placing",
    "shadowed",
    "dry_run_complete",
    "blocked_by_gate",
    "blocked_by_budget",
    "blocked_by_cooldown",
    "circuit_open",
    "stale_signal",
    "failed_retryable",
    "failed_terminal",
    "no_meaningful_delta",
    "no_open_position",
]


def _normalize_required_symbol(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError("ticker is required")
    return normalized


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None



OptionsFlowSource = Literal["marketdata", "yahooquery", "yfinance", "unavailable"]


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
    source: OptionsFlowSource = "unavailable"


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


class PricePrediction(BaseModel):
    range_low: float
    range_high: float
    horizon: OutcomeHorizon = "1w"
    horizon_label: str = "1 week"
    invalidation: str
    methodology: str = "structural_stop_target"
    disclaimer: str = (
        "Structural range from stop/target levels aligned with paper sizing. "
        "Not a guarantee or price target."
    )


class ExitWindow(BaseModel):
    expected_growth_window_label: str = "~1 week"
    expected_growth_days: int = 7
    estimated_exit_price: float | None = None
    projected_range_low: float | None = None
    projected_range_high: float | None = None
    invalidation_level: float | None = None
    invalidation_note: str = "No directional thesis."
    stop_growing_signal: str = "Growth expected to slow near the projected range high."
    stop_growing_conditions: list[str] = []
    risk_warning: str = ""
    confidence_change_note: str = ""
    methodology: str = "weekly_pattern_exit_window"
    disclaimer: str = (
        "Exit window is a forecast of when growth may slow or the thesis may break. "
        "It is not a sell order or automatic exit; paper-only decision support."
    )


class WeeklyPatternPrediction(BaseModel):
    horizon: Literal["1w"] = "1w"
    horizon_label: str = "1 week"
    pattern_name: str
    directional_bias: WeeklyDirectionalBias
    range_low: float
    range_high: float
    upside_probability_pct: float | None = None
    historical_hit_rate_pct: float | None = None
    avg_forward_1w_return_pct: float | None = None
    sample_size: int = 0
    data_quality: Literal["ok", "low", "degraded"] = "low"
    daily_bars_stale: bool = False
    daily_bars_source: str = "unknown"
    forward_days: int = 7
    hold_return_tolerance_pct: float = 1.0
    evidence_basis: WeeklyEvidenceBasis = "insufficient"
    real_money_trust_blocked: bool = True
    pattern_gate_checks: list[GateCheck] = []
    methodology: str = "pattern_recognition"
    disclaimer: str = (
        "Weekly pattern-recognition range from daily-bar rules and walk-forward stats. "
        "Paper-only; not a guarantee or live execution signal."
    )


class ScanResult(BaseModel):
    ticker: str
    asset_type: AssetType = "stock"
    strategy_variant: str = "layered-v4"
    score: float
    raw_score: float = 0.0
    calibrated_confidence: float = 0.0
    calibration_source: str = "raw"
    confidence_label: str = "calibrated_confidence"
    strategy_id: str = "scanner-directional"
    strategy_version: str = "v4.0-layered"
    strategy_primary_horizon: str = "1w"
    strategy_entry_assumption: str = ""
    strategy_exit_assumption: str = ""
    evidence_quality: EvidenceQuality = "low"
    evidence_quality_score: float = 0.0
    evidence_quality_reasons: list[str] = []
    evidence_grade: EvidenceGrade = "Weak"
    top_reasons: list[str] = []
    price_prediction: PricePrediction | None = None
    weekly_prediction: WeeklyPatternPrediction | None = None
    exit_window: ExitWindow | None = None
    upside_probability_pct: float | None = None
    confidence_score: float = 0.0
    evidence_provenance: WeeklyEvidenceBasis = "insufficient"
    is_buy_candidate: bool = False
    data_grade: DataGrade = "research"
    execution_eligibility: ExecutionEligibility = "not_applicable"
    buy_score: float = 0.0
    sell_score: float = 0.0
    decision_signal: DecisionSignal = "HOLD"
    scoring_version: str = "v4.0-layered"
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
    provider_status: ProviderStatus = "ok"
    provider_warnings: list[str] = []
    price_source: Literal["alpaca", "coinbase_ws", "polygon", "stale_cache"] = "alpaca"
    fallback_used: bool = False
    bar_age_minutes: float | None = None
    bar_as_of: datetime | None = None
    freshness_flags: dict[str, str] = {}
    rank: int | None = None
    recommended_action: RecommendedAction | None = None
    readiness_score: float = 0.0
    readiness_band: ReadinessBand = "none"
    readiness_hard_stop: bool = False
    readiness_reason: str | None = None
    selection_rank: int | None = None
    is_top_pick: bool = False
    layer_details: dict = {}
    created_at: datetime


class ScanRun(BaseModel):
    run_id: str
    created_at: datetime
    market_status: MarketStatus
    strategy_variant: str = "layered-v4"
    scan_count: int
    watchlist_size: int
    alerts_sent: int = 0
    fear_greed_value: int | None = None
    fear_greed_label: str | None = None
    scan_age_minutes: float | None = None
    scan_fresh: bool | None = None
    results: list[ScanResult]
    top_stocks: list[ScanResult] = []
    top_crypto: list[ScanResult] = []


class CryptoMarketPrice(BaseModel):
    symbol: str
    product_id: str
    price: float
    received_at: datetime
    channel: str | None = None
    event_type: str | None = None
    sequence_num: int | None = None
    source: str = "coinbase_advanced_trade_ws"


class CryptoMarketSnapshotResponse(BaseModel):
    prices: list[CryptoMarketPrice] = []


class HealthResponse(BaseModel):
    ok: bool
    env: str
    app_version: str | None = None
    ready: bool = False
    live: bool = True
    schema_ok: bool = True
    missing_schema_items: list[str] = []
    scheduler_running: bool = False
    worker_alive: bool = False
    last_worker_heartbeat_at: datetime | None = None
    last_scan_at: datetime | None = None
    last_scan_age_minutes: float | None = None
    max_stale_minutes: int | None = None
    scan_fresh: bool | None = None
    scheduler_enabled: bool = False
    scheduler_interval_seconds: int | None = None
    next_scan_due_at: datetime | None = None
    last_scheduler_run_started_at: datetime | None = None
    last_scheduler_run_finished_at: datetime | None = None
    last_scheduler_error: str | None = None
    trust_window_start: datetime | None = None
    trust_window_end: datetime | None = None
    trust_recent_window_days: int | None = None
    trust_total_signals: int | None = None
    trust_evaluated_count: int | None = None
    trust_pending_count: int | None = None
    trust_buy_passed_evaluated_count: int | None = None
    trust_sell_passed_evaluated_count: int | None = None
    trust_threshold_evidence_status: str | None = None
    trust_threshold_source: str | None = None
    trust_threshold_warning_count: int | None = None
    trust_evidence_ready: bool | None = None
    pending_due_15m_count: int | None = None
    pending_due_1h_count: int | None = None
    pending_due_1d_count: int | None = None
    pending_due_1w_count: int | None = None
    request_id: str | None = None


class OrderPreviewRequest(BaseModel):
    ticker: str
    side: OrderSide
    qty: float = Field(gt=0)
    order_type: OrderType = "market"
    limit_price: float | None = Field(default=None, gt=0)
    preview_audit_id: int | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    # Paper-only build: the only accepted mode is an omitted value or "dry_run".
    # Any other mode is rejected at the schema boundary (422) before the service.
    mode: Literal["dry_run"] | None = None
    entry_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    target_price: float | None = Field(default=None, gt=0)
    recommended_action_snapshot: str | None = None

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return _normalize_required_symbol(value)

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
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    position_size: float | None = None
    estimated_pnl_usd: float | None = None
    gate_result: str | None = None
    freshness: str | None = None
    reject_reasons: list[str] = []


class OrderPlaceRequest(OrderPreviewRequest):
    # Paper-only build: dry_run is structurally fixed to True. A request with
    # dry_run=false is rejected at the schema boundary (422) before the service.
    dry_run: Literal[True] = True


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
    ledger_id: int | None = None
    fill_price: float | None = None
    filled_qty: float | None = None
    slippage_assumption_bps: float | None = None
    recommended_action_snapshot: str | None = None


class ExecutionAuditSummary(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    ticker: str
    asset_type: AssetType = "stock"
    side: OrderSide
    order_type: OrderType
    qty: float
    dry_run: bool = False
    lifecycle_status: str
    latest_price: float | None = None
    notional_estimate: float | None = None
    signal_outcome_id: int | None = None
    signal_run_id: str | None = None
    signal_generated_at: datetime | None = None
    latest_signal: DecisionSignal | None = None
    confidence: float | None = None
    raw_score: float | None = None
    evidence_quality: EvidenceQuality | None = None
    execution_eligibility: ExecutionEligibility | None = None
    trade_gate_horizon: str | None = None
    gate_evaluation_mode: str | None = None
    evidence_basis: str | None = None
    trust_window_start: datetime | None = None
    trust_window_end: datetime | None = None
    latest_scan_age_minutes: float | None = None
    latest_scan_fresh: bool | None = None
    stored_gate_passed: bool | None = None
    stored_gate_reason: str | None = None
    gate_consistent_with_signal: bool | None = None
    trade_gate_allowed: bool | None = None
    trade_gate_reason: str | None = None
    recommended_action_snapshot: str | None = None
    submitted: bool = False
    broker_order_id: str | None = None
    broker_status: str | None = None
    error_message: str | None = None


class AutomationIntentSummary(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    run_id: str
    symbol: str
    asset_type: AssetType = "stock"
    side: OrderSide
    qty: float
    strategy_version: str | None = None
    confidence: float | None = None
    horizon: str | None = None
    status: AutomationIntentStatus
    status_reason: str | None = None
    idempotency_key: str | None = None
    execution_audit_id: int | None = None
    attempt_count: int = 0
    request_count_used: int = 0
    request_count_avoided: int = 0
    last_attempt_at: datetime | None = None
    next_retry_at: datetime | None = None
    cooldown_until: datetime | None = None
    incident_class: AutomationIncidentClass | None = None


class AutomationBudgetSnapshot(BaseModel):
    hourly_limit: int
    hourly_used: int
    daily_limit: int
    daily_used: int
    per_symbol_window_limit: int
    per_symbol_window_seconds: int
    per_cycle_limit: int


class AutomationBreakerSnapshot(BaseModel):
    state: Literal["closed", "open", "half_open"] = "closed"
    opened_at: datetime | None = None
    open_until: datetime | None = None
    consecutive_failures: int = 0
    last_error: str | None = None
    probe_owner: str | None = None
    probe_expires_at: datetime | None = None


class AutomationStatusResponse(BaseModel):
    enabled: bool
    phase: AutomationPhase
    dry_run_only: bool = True
    kill_switch_enabled: bool = False
    scheduler_triggered: bool = True
    last_processed_run_id: str | None = None
    last_processed_run_at: datetime | None = None
    last_recovery_at: datetime | None = None
    requests_made: int = 0
    requests_avoided: int = 0
    dedupe_hits: int = 0
    retries: int = 0
    blocked_by_budget: int = 0
    blocked_by_gate: int = 0
    blocked_by_cooldown: int = 0
    blocked_by_circuit: int = 0
    recent_status_counts: dict[str, int] = {}
    budget: AutomationBudgetSnapshot
    breaker: AutomationBreakerSnapshot
    recent_intents: list[AutomationIntentSummary] = []
    candidates_considered: int = 0
    candidates_reached_execution_call: int = 0
    filter_rate_pct: float | None = None


class SystemReadinessAutomation(BaseModel):
    scheduler_enabled: bool = False
    scheduler_running: bool = False
    worker_alive: bool = False
    automation_enabled: bool = False
    automation_phase: AutomationPhase = "disabled"
    automation_ready: bool = False
    dry_run_only: bool = True
    kill_switch_enabled: bool = False
    breaker_state: Literal["closed", "open", "half_open", "unknown"] = "unknown"


class SystemReadinessProviderSummary(BaseModel):
    worst_status: str = "unknown"
    total_count: int = 0
    critical_count: int = 0
    degraded_count: int = 0


class SystemReadinessFreshnessSummary(BaseModel):
    last_scan_at: datetime | None = None
    last_scan_age_minutes: float | None = None
    max_stale_minutes: int | None = None
    scan_fresh: bool | None = None
    total_count: int = 0
    stale_count: int = 0
    severe_stale_count: int = 0


class SystemReadinessDiagnostics(BaseModel):
    """First-class answers to 'why no candidates?' and 'did we miss a window?'."""

    top_rejection_reasons: list[dict[str, object]] = []
    pending_prediction_resolutions: int = 0
    candidate_shortage: bool = False


class SystemReadinessResponse(BaseModel):
    status: Literal["PASS", "FAIL"]
    reasons: list[str] = []
    safety_blockers: list[str] = []
    automation: SystemReadinessAutomation
    provider: SystemReadinessProviderSummary
    freshness: SystemReadinessFreshnessSummary
    diagnostics: SystemReadinessDiagnostics = SystemReadinessDiagnostics()
    request_id: str | None = None

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
    override_reason: str | None = None
    action_state: JournalActionState | None = None

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return _normalize_required_symbol(value)

    @field_validator("run_id", "signal_label", "news_source", "override_reason", mode="before")
    @classmethod
    def normalize_optional_fields(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str:
        return (_normalize_optional_text(value) or "")



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
    override_reason: str | None = None
    action_state: JournalActionState | None = None


class JournalEntryUpdateRequest(BaseModel):
    decision: JournalDecision | None = None
    entry_price: float | None = Field(default=None, gt=0)
    exit_price: float | None = Field(default=None, gt=0)
    pnl_pct: float | None = None
    notes: str | None = None
    override_reason: str | None = None
    action_state: JournalActionState | None = None

    @field_validator("notes", "override_reason", mode="before")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

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
    raw_score: float | None = None
    calibration_source: str = "raw"
    confidence_label: str = "calibrated_confidence"
    evidence_quality: EvidenceQuality | None = None
    evidence_quality_score: float | None = None
    evidence_quality_reasons: tuple[str, ...] = ()
    data_grade: DataGrade | None = None
    execution_eligibility: ExecutionEligibility | None = None
    provider_status: ProviderStatus | None = None
    gate_passed: bool | None = None
    bar_age_minutes: float | None = None
    signal_age_minutes: float | None = None
    freshness_flags: dict[str, str] | None = None
    recommended_action: Literal["ignore", "review", "preview", "dry_run", "blocked"] | None = None
    readiness_score: float | None = None
    readiness_band: ReadinessBand | None = None
    readiness_hard_stop: bool | None = None
    readiness_reason: str | None = None
    selection_rank: int | None = None
    is_top_pick: bool | None = None
    rank: int | None = None
    score_contributions: dict[str, float] = {}
    evidence_grade: EvidenceGrade | None = None
    top_reasons: list[str] = []
    price_prediction: PricePrediction | None = None
    weekly_prediction: WeeklyPatternPrediction | None = None
    exit_window: ExitWindow | None = None
    upside_probability_pct: float | None = None
    confidence_score: float | None = None
    evidence_provenance: WeeklyEvidenceBasis | None = None
    is_buy_candidate: bool | None = None
    strategy_version: str | None = None
    short_metric_summary: str
    last_updated: datetime


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
    evaluated_1w_count: int = 0
    win_rate_1w: float | None = None
    avg_return_1w: float | None = None


class SignalOutcomeSummary(BaseModel):
    total_signals: int
    pending_15m_count: int
    pending_1h_count: int
    pending_1d_count: int
    pending_1w_count: int = 0
    overall: SignalOutcomePerformanceBucket
    by_signal: list[SignalOutcomePerformanceBucket]
    by_confidence_bucket: list[SignalOutcomePerformanceBucket]
    by_signal_confidence_bucket: list[SignalOutcomePerformanceBucket]
    by_signal_score_bucket: list[SignalOutcomePerformanceBucket]


class TickerScanHistoryRow(BaseModel):
    run_id: str
    run_created_at: datetime
    market_status: MarketStatus
    result: ScanResult


class TickerSignalOutcomeRecord(BaseModel):
    id: int
    run_id: str
    ticker: str
    asset_type: AssetType = "stock"
    signal: DecisionSignal
    confidence: float
    raw_score: float
    generated_at: datetime
    entry_price: float
    horizon: Literal["15m", "1h", "1d", "1w"]
    status: str
    return_pct: float | None = None
    evaluated_at: datetime | None = None
    strategy_variant: str | None = None
    gate_passed: bool | None = None
    gate_reason: str | None = None


class TickerSignalOutcomeEvidence(BaseModel):
    ticker: str
    horizon: Literal["15m", "1h", "1d", "1w"]
    strategy_variant: str | None = None
    trust_window_start: datetime | None = None
    trust_window_end: datetime | None = None
    sample_size: int
    evaluated_count: int
    pending_count: int
    win_count: int
    loss_count: int
    win_rate: float | None = None
    mean_return: float | None = None
    median_return: float | None = None
    insufficient_sample: bool
    min_evaluated_for_rate: int
    recent_outcomes: list[TickerSignalOutcomeRecord] = []


class HorizonMetrics(BaseModel):
    horizon: Literal["15m", "1h", "1d", "1w"]
    total_signals: int
    evaluated_count: int
    pending_count: int
    win_count: int
    loss_count: int
    false_positive_count: int
    win_rate: float | None = None
    mean_return: float | None = None
    median_return: float | None = None
    avg_win_return: float | None = None
    avg_loss_return: float | None = None
    expectancy: float | None = None
    false_positive_rate: float | None = None
    meets_min_sample: bool
    insufficient_sample: bool


class OutcomePerformanceSlice(BaseModel):
    key: str
    total_signals: int
    metrics_15m: HorizonMetrics
    metrics_1h: HorizonMetrics
    metrics_1d: HorizonMetrics
    metrics_1w: HorizonMetrics


class OutcomeBaselineCheck(BaseModel):
    key: str
    horizon: OutcomeHorizon
    evaluated_count: int
    mean_return: float | None = None
    meets_min_sample: bool
    passes_mean_return: bool
    passed: bool
    reason: str


class OutcomeBaselineSummary(BaseModel):
    primary_horizon: Literal["15m", "1h", "1d", "1w"]
    min_evaluated_per_horizon: int
    min_mean_return_pct: float
    passes_baseline: bool
    details: list[str] = []
    checks: list[OutcomeBaselineCheck] = []


class SignalOutcomePerformanceReportResponse(BaseModel):
    generated_at_field: str = "generated_at"
    start: datetime
    end: datetime
    asset_type: AssetType | None = None
    regime: MarketStatus | None = None
    friction_scenario: Literal["base", "stressed", "worst"] = "base"
    strict_walkforward: bool = False
    total_signals: int
    min_evaluated_per_horizon: int
    overall: OutcomePerformanceSlice
    by_signal: list[OutcomePerformanceSlice]
    by_signal_and_gate: list[OutcomePerformanceSlice]
    by_asset_type: list[OutcomePerformanceSlice]
    baseline: OutcomeBaselineSummary


class TradeEligibility(BaseModel):
    ticker: str
    asset_type: AssetType = "stock"
    strategy_variant: str = "layered-v4"
    requested_side: OrderSide
    required_signal: DecisionSignal
    signal_outcome_id: int | None = None
    signal_run_id: str | None = None
    signal_generated_at: datetime | None = None
    latest_signal: DecisionSignal | None = None
    confidence: float | None = None
    calibration_source: str | None = None
    raw_score: float | None = None
    confidence_label: str = "calibrated_confidence"
    evidence_quality: EvidenceQuality | None = None
    evidence_quality_score: float | None = None
    evidence_quality_reasons: list[str] = []
    execution_eligibility: ExecutionEligibility | None = None
    strategy_id: str = "scanner-directional"
    strategy_version: str = "v4.0-layered"
    strategy_primary_horizon: str = "1w"
    strategy_entry_assumption: str | None = None
    strategy_exit_assumption: str | None = None
    signal_age_minutes: float | None = None
    confidence_bucket: str | None = None
    raw_score_bucket: str | None = None
    score_band: str | None = None
    horizon: str
    gate_evaluation_mode: str | None = None
    evidence_basis: str | None = None
    real_money_trust_blocked: bool | None = None
    real_money_eligible: bool = False
    trust_window_start: datetime | None = None
    trust_window_end: datetime | None = None
    latest_scan_age_minutes: float | None = None
    latest_scan_fresh: bool | None = None
    stored_gate_passed: bool | None = None
    stored_gate_reason: str | None = None
    gate_consistent_with_signal: bool | None = None
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
    portfolio_checks: list[GateCheck] = []
    portfolio_summary: str | None = None


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
    avg_return_after_friction: float | None = None
    # Derived view: win rate recomputed after friction is deducted from the
    # canonical raw returns. Raw outcomes stay canonical; this reinterprets.
    win_rate_after_friction: float | None = None
    expectancy_after_friction: float | None = None
    false_positive_rate: float | None = None
    min_sample_met: bool = True
    is_underpowered: bool = False


class ValidationSummary(BaseModel):
    generated_at_field: str = "generated_at"
    start: datetime | None = None
    end: datetime | None = None
    primary_horizon: Literal["15m", "1h", "1d", "1w"]
    win_threshold_pct: float
    false_positive_threshold_pct: float
    total_signals: int
    evaluated_count: int
    pending_count: int
    minimum_sample_size: int = 30
    sample_size_sufficient: bool = False
    evaluated_fraction: float | None = None
    confidence_note: str = ""
    overall: ValidationBucket
    # Recency half-split of the selected window. This is a stability check on
    # serving data, not a genuine out-of-sample test (the strategy saw none of
    # it in training, but thresholds were tuned on overlapping history).
    earlier_window: ValidationBucket | None = None
    recent_window: ValidationBucket | None = None
    degradation_warnings: list[str] = []
    regime_advisories: list[str] = []
    by_signal: list[ValidationBucket]
    by_confidence_bucket: list[ValidationBucket] = []
    by_score_band: list[ValidationBucket]
    by_age_bucket: list[ValidationBucket] = []
    by_signal_label: list[ValidationBucket]
    by_market_status: list[ValidationBucket]
    by_news_source: list[ValidationBucket]
    by_volatility_regime: list[ValidationBucket]
    by_data_quality: list[ValidationBucket]
    by_data_grade: list[ValidationBucket] = []
    by_options_flow_bias: list[ValidationBucket]
    by_signal_and_gate: list[ValidationBucket]
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
    avg_return_after_friction: float | None = None
    expectancy_after_friction: float | None = None
    false_positive_rate: float | None = None


class ThresholdRecommendation(BaseModel):
    min_evaluated_count: int
    min_win_rate: float
    min_avg_return: float
    score_band_required: bool
    source: Literal["candidate", "configured_fallback"]
    evidence_status: Literal["ready", "provisional"]
    rationale: str
    warnings: list[str] = []


class ThresholdSweepResponse(BaseModel):
    generated_at_field: str = "generated_at"
    start: datetime | None = None
    end: datetime | None = None
    primary_horizon: Literal["15m", "1h", "1d", "1w"]
    win_threshold_pct: float
    false_positive_threshold_pct: float
    baseline: ValidationBucket
    by_signal_and_gate: list[ValidationBucket]
    recommendation: ThresholdRecommendation
    candidates: list[ThresholdSweepRow]


class CohortValidationSummary(BaseModel):
    cohort: str
    total_signals: int
    evaluated_count: int
    pending_count: int
    win_rate: float | None = None
    avg_return: float | None = None
    expectancy: float | None = None
    avg_return_after_friction: float | None = None
    expectancy_after_friction: float | None = None
    false_positive_rate: float | None = None
    min_sample_met: bool = True
    is_underpowered: bool = False


class ExecutionAlignmentResponse(BaseModel):
    generated_at_field: str = "generated_at"
    start: datetime | None = None
    end: datetime | None = None
    primary_horizon: Literal["15m", "1h", "1d", "1w"]
    win_threshold_pct: float
    false_positive_threshold_pct: float
    all_signals: CohortValidationSummary
    taken_trades: CohortValidationSummary
    journal_took: CohortValidationSummary | None = None
    skipped_or_watched: CohortValidationSummary
    blocked_previews: CohortValidationSummary
    automation_dry_run: CohortValidationSummary | None = None


class PaperPositionSummary(BaseModel):
    id: int
    intent_key: str
    execution_audit_id: int | None = None
    ticker: str
    asset_type: AssetType = "stock"
    side: OrderSide
    quantity: float
    simulated_fill_price: float
    notional_usd: float
    cost_basis_usd: float
    close_price: float | None = None
    realized_pnl: float | None = None
    status: PaperPositionStatus = "open"
    opened_at: datetime
    closed_at: datetime | None = None
    strategy_version: str | None = None
    confidence: float | None = None


class PaperLedgerSummaryResponse(BaseModel):
    open_positions: int
    closed_positions: int
    total_notional_usd: float
    total_realized_pnl: float
    total_closed_notional_usd: float
    long_positions: int
    short_positions: int
    last_opened_at: datetime | None = None
    last_closed_at: datetime | None = None
    total_count: int = 0
    win_rate_pct: float | None = None
    gross_pnl_usd: float = 0.0
    max_drawdown_usd: float = 0.0
    total_unrealized_pnl: float | None = None


class ProofLoopMetrics(BaseModel):
    recent_dry_runs: int
    recent_previewed: int
    recent_blocked: int
    total_audits: int


class PredictionAccuracyMetrics(BaseModel):
    evaluated_count: int = 0
    pending_count: int = 0
    in_range_count: int = 0
    in_range_rate_pct: float | None = None
    below_range_count: int = 0
    above_range_count: int = 0
    missed_count: int = 0
    # Headline honesty metrics: was the direction right, and was the stated
    # probability sharp (Brier: lower is better, 0.25 = coin-flip forecast)?
    direction_evaluated_count: int = 0
    direction_hit_rate_pct: float | None = None
    brier_score: float | None = None
    # Missingness: evaluated snapshots whose resolution never found a usable
    # bar. High missingness silently biases every other number here.
    missing_rate_pct: float | None = None
    # Scope: which prediction campaign these numbers cover ("all campaigns"
    # mixes strategy identities and is only for transparency).
    campaign_id: str | None = None
    scope: str = "all_campaigns"
    note: str | None = None


class WeeklyEvidenceProgress(BaseModel):
    live_forward_samples: int = 0
    out_of_sample_samples: int = 0
    historical_samples: int = 0
    backfilled_replay_samples: int = 0
    min_live_forward_samples: int = 0
    min_out_of_sample_samples: int = 0
    min_historical_samples: int = 0
    min_backfilled_replay_samples: int = 0
    # Sample-count gate only. Per-candidate performance (win-rate / avg-return) and
    # per-pattern checks still apply; this is transparency progress, not a trust grant.
    trust_sample_gate_met: bool = False
    calibration_sample_gate_met: bool = False


class LiveForwardAssetProgress(BaseModel):
    asset_type: str
    selected: int = 0
    accepted_outside_top_n: int = 0
    rejected: int = 0
    resolved: int = 0
    pending: int = 0
    resolved_late: int = 0


class LiveForwardProgress(BaseModel):
    """Live-forward evidence accumulation for the active campaign. This is
    completion/transparency progress, NOT a real-money readiness signal."""

    campaign_id: str | None = None
    campaign_started_at: datetime | None = None
    config_fingerprint: str | None = None
    strategy_version: str | None = None
    code_commit: str | None = None
    selected_count: int = 0
    accepted_outside_top_n_count: int = 0
    rejected_count: int = 0
    resolved_count: int = 0
    pending_count: int = 0
    resolved_late_count: int = 0
    by_asset: list[LiveForwardAssetProgress] = []
    last_scan_at: datetime | None = None
    last_scan_age_minutes: float | None = None
    note: str | None = None


class ConfidenceTierBucket(BaseModel):
    score_band: str
    asset_type: str
    signal: str
    sample_source: str
    evaluated_count: int
    win_rate_pct: float | None = None
    avg_return_pct: float | None = None
    avg_return_after_friction_base_pct: float | None = None
    avg_return_after_friction_stressed_pct: float | None = None


class ConfidenceRanking(BaseModel):
    buckets: list[ConfidenceTierBucket] = []
    # True only if every comparable group (same asset_type/signal/sample_source with
    # 2+ evaluated bands) is non-decreasing in avg return as confidence rises; None if
    # there is not yet enough data to judge ranking.
    monotonic_by_group: bool | None = None
    note: str | None = None


class ConfidenceCalibrationBucket(BaseModel):
    probability_band: str
    asset_type: str
    evaluated_count: int
    avg_predicted_pct: float | None = None
    realized_up_rate_pct: float | None = None
    reliability_gap_pct: float | None = None


class ConfidenceCalibration(BaseModel):
    buckets: list[ConfidenceCalibrationBucket] = []
    mean_abs_reliability_gap_pct: float | None = None
    campaign_id: str | None = None
    scope: str = "all_campaigns"
    note: str | None = None


class ConfidencePerformance(BaseModel):
    ranking: ConfidenceRanking = ConfidenceRanking()
    calibration: ConfidenceCalibration = ConfidenceCalibration()


class ExitWindowAssetMetrics(BaseModel):
    asset_type: str
    evaluated_count: int = 0
    pending_count: int = 0
    helped_count: int = 0
    helped_rate_pct: float | None = None
    avg_protected_return_pct: float | None = None
    avg_hold_return_pct: float | None = None
    avg_protected_after_friction_stressed_pct: float | None = None
    avg_hold_after_friction_stressed_pct: float | None = None


class ExitWindowAccuracyMetrics(BaseModel):
    evaluated_count: int = 0
    pending_count: int = 0
    helped_count: int = 0
    helped_rate_pct: float | None = None
    by_asset_type: list[ExitWindowAssetMetrics] = []
    note: str | None = None


WalkForwardTrack = Literal["research", "validation", "holdout"]


class WalkForwardCalibrationBucket(BaseModel):
    probability_band: str
    asset_type: AssetType
    track: WalkForwardTrack
    evaluated_count: int = 0
    avg_predicted_pct: float | None = None
    realized_up_rate_pct: float | None = None
    reliability_gap_pct: float | None = None


class WalkForwardAssetMetrics(BaseModel):
    asset_type: AssetType
    track: WalkForwardTrack
    prediction_count: int = 0
    resolved_count: int = 0
    pending_count: int = 0
    upside_hit_rate_pct: float | None = None
    # Derived view: hit rate after friction is deducted from canonical raw returns.
    upside_hit_rate_after_friction_pct: float | None = None
    # Brier score of stated upside probability vs realized direction (lower is
    # better; 0.25 = coin flip). Missing resolution rate reports how many
    # selected predictions never found a usable forward bar.
    brier_score: float | None = None
    missing_resolution_rate_pct: float | None = None
    avg_return_pct: float | None = None
    avg_return_after_friction_pct: float | None = None
    avg_return_after_friction_stressed_pct: float | None = None
    calibration_mean_abs_gap_pct: float | None = None
    calibrated_calibration_gap_pct: float | None = None
    confidence_discrimination_pct: float | None = None
    exit_window_helped_rate_pct: float | None = None
    exit_conflict_rate_pct: float | None = None
    avg_protected_return_pct: float | None = None
    avg_hold_return_pct: float | None = None
    worst_return_pct: float | None = None
    p05_return_pct: float | None = None
    worst_decile_mean_pct: float | None = None
    max_drawdown_pct: float | None = None
    # Statistical-solidity measures (quant-research rigor): significance of the
    # realized edge, signal-vs-outcome information coefficient, and cross-regime
    # robustness. Reported for confidence; real-money trust stays separately gated.
    upside_hit_rate_lb95_pct: float | None = None
    edge_significant: bool | None = None
    information_coefficient: float | None = None
    ic_t_stat: float | None = None
    regime_sample_counts: dict[str, int] | None = None
    regime_avg_return_pct: dict[str, float] | None = None
    cross_regime_edge_ok: bool | None = None
    edge_after_friction_vs_buy_and_hold_pct: float | None = None
    edge_after_friction_vs_market_pct: float | None = None
    edge_after_friction_vs_momentum_pct: float | None = None
    edge_after_friction_vs_sma_cross_pct: float | None = None
    edge_after_friction_vs_random_pct: float | None = None


class WalkForwardBenchmark(BaseModel):
    asset_type: AssetType
    track: WalkForwardTrack
    strategy: str
    periods: int = 0
    avg_return_pct: float | None = None
    avg_return_after_friction_pct: float | None = None


class WalkForwardCoverageRow(BaseModel):
    symbol: str
    asset_type: AssetType
    bar_count: int = 0
    first_date: str | None = None
    last_date: str | None = None
    years_available: float = 0.0
    source: str = "cache"
    sufficient: bool = False
    note: str = ""


class WalkForwardAssetVerdict(BaseModel):
    # Independent per-asset-class verdict. Stock and crypto are judged separately
    # and never merged; each carries its own checks and sample floors.
    asset_type: AssetType
    ready: bool = False
    real_money_trust_blocked: bool = True
    summary: str = "Historical walk-forward proof only; not a real-money trust grant."
    checks: list[GateCheck] = []


class WalkForwardPilotVerdict(BaseModel):
    # Report-only. This never enables execution; real-money trust stays blocked
    # and paper-only / dry-run boundaries are unaffected. `ready` is true only if
    # every asset class in `by_asset` is ready, but the per-asset verdicts are the
    # authoritative, independent results.
    ready: bool = False
    real_money_trust_blocked: bool = True
    summary: str = "Historical walk-forward proof only; not a real-money trust grant."
    checks: list[GateCheck] = []
    by_asset: list[WalkForwardAssetVerdict] = []
    # Trials ledger: distinct configurations evaluated against this history.
    # Many trials weaken any single passing verdict (multiple testing).
    trials: dict[str, Any] | None = None
    # Non-gating honesty caveats (survivorship, adjustment policy, ...).
    caveats: list[str] = []


class EvidenceTrackDescriptor(BaseModel):
    key: str
    label: str
    description: str
    is_forward: bool
    counts_toward_real_money: bool


class WalkForwardRunSummary(BaseModel):
    run_id: str
    created_at: datetime
    window_start: datetime | None = None
    window_end: datetime | None = None
    holdout_start: datetime | None = None
    target_years: int = 3
    step_days: int = 7
    forward_days: int = 7
    top_n_per_asset: int = 5
    symbol_count: int = 0
    prediction_count: int = 0
    resolved_count: int = 0
    pending_count: int = 0
    evidence_track: str = "historical_walk_forward"
    validation_start: datetime | None = None
    by_asset_track: list[WalkForwardAssetMetrics] = []
    calibration_buckets: list[WalkForwardCalibrationBucket] = []
    benchmarks: list[WalkForwardBenchmark] = []
    coverage: list[WalkForwardCoverageRow] = []
    pilot_verdict: WalkForwardPilotVerdict = WalkForwardPilotVerdict()
    # Run manifest for deterministic, versioned, auditable reruns.
    config_fingerprint: str | None = None
    code_commit: str | None = None
    engine_version: str | None = None
    policy_id: str | None = None
    policy_version: str | None = None
    decision_fingerprint: str | None = None
    learned_artifacts_fingerprint: str | None = None
    # Ruler identity: how this evidence was judged. Separate from the decision
    # fingerprints of the evidence itself; ruler changes never rotate campaigns.
    ruler_version: str | None = None
    ruler_fingerprint: str | None = None
    universe: list[str] = []
    universe_source: str | None = None
    data_quality_ok: bool | None = None
    data_quality_issues: list[str] = []
    survivorship_caveat: str = (
        "Universe is the current watchlist only; delisted names are absent, so "
        "results are survivorship-limited."
    )
    overlap_status: str | None = None
    note: str | None = None


class WalkForwardProofRequest(BaseModel):
    symbols: list[str] | None = None
    years: int | None = Field(default=None, ge=1, le=10)
    step_days: int | None = Field(default=None, ge=1, le=31)
    top_n_per_asset: int | None = Field(default=None, ge=3, le=5)
    force_refresh: bool = False

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [_normalize_required_symbol(value) for value in values]
        return normalized or None


class WalkForwardProofRunResponse(BaseModel):
    run_id: str
    summary: WalkForwardRunSummary


class PolicyPromotionCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class PolicyPromotionReport(BaseModel):
    champion_policy_id: str
    challenger_policy_id: str
    challenger_replayable: bool = True
    ruler_version: str
    ruler_fingerprint: str | None = None
    champion_decision_fingerprint: str | None = None
    challenger_decision_fingerprint: str | None = None
    gates_cleared: bool
    walk_forward_holdout_passed: bool
    summary: str
    checks: list[PolicyPromotionCheck] = []
    paired_returns_total: int = 0
    paired_returns_informative: int = 0
    paired_returns_both_abstained: int = 0
    paired_returns_resolution_clusters: int = 0
    paired_returns_cluster_metadata_complete: bool = False
    paired_returns_superior: bool = False
    pair_exclusion_counts: dict[str, int] = {}
    effective_champion_policy_id: str
    requested_champion_policy_id: str


class ProofSummaryResponse(BaseModel):
    generated_at: datetime
    ledger: PaperLedgerSummaryResponse
    loop_metrics: ProofLoopMetrics
    prediction_accuracy: PredictionAccuracyMetrics | None = None
    confidence_performance: ConfidencePerformance | None = None
    exit_window_accuracy: ExitWindowAccuracyMetrics | None = None
    weekly_evidence: WeeklyEvidenceProgress | None = None
    walk_forward: WalkForwardRunSummary | None = None
    live_forward: LiveForwardProgress | None = None
    evidence_contract: list[EvidenceTrackDescriptor] = []
    last_scan_at: datetime | None = None
    scan_fresh: bool | None = None
    mark_prices_source: str = "latest_scan"
    note: str | None = None
    # Ruler identity for the proof summary as a whole. This describes how
    # evidence is judged and stays separate from decision policy fingerprints.
    ruler_version: str | None = None
    ruler_fingerprint: str | None = None
    policy_promotion: PolicyPromotionReport | None = None


class PromotionGateResult(BaseModel):
    key: str
    passed: bool
    detail: str


class PromotionReadinessResponse(BaseModel):
    current_phase: AutomationPhase
    target_phase: AutomationPhase | None = None
    passed: bool
    generated_at: datetime
    details: list[str] = []
    checks: list[PromotionGateResult] = []


class ReconciliationIssue(BaseModel):
    kind: str
    detail: str
    intent_id: int | None = None
    execution_audit_id: int | None = None
    paper_position_id: int | None = None


class ReconciliationReportResponse(BaseModel):
    generated_at: datetime
    ok: bool
    total_issues: int
    issues: list[ReconciliationIssue] = []
    issues_by_kind: dict[str, int] = {}


class StrategySignalContractResponse(BaseModel):
    signal: DecisionSignal
    intent: Literal["long", "short", "flat"]
    operational_meaning: str


class StrategyContractResponse(BaseModel):
    strategy_id: str
    strategy_version: str
    name: str
    primary_holding_horizon: str
    entry_assumption: str
    exit_assumption: str
    buy_definition: StrategySignalContractResponse
    sell_definition: StrategySignalContractResponse
    hold_definition: StrategySignalContractResponse
    evidence_inputs: list[str]
    critical_provider_inputs: list[str]
    supportive_provider_inputs: list[str]
    known_limitations: list[str]


class FrictionAssumptions(BaseModel):
    stock_slippage_bps: float
    stock_spread_bps: float
    stock_fee_bps: float
    crypto_slippage_bps: float
    crypto_spread_bps: float
    crypto_fee_bps: float


class ReplayRequest(BaseModel):
    symbols: list[str] = Field(min_length=1)
    start: datetime
    end: datetime
    interval_minutes: int = Field(default=60, ge=5, le=1440)
    warmup_bars: int = Field(default=30, ge=10, le=300)
    strategy_variant: str | None = None
    include_secondary_providers: bool = False
    apply_friction: bool = True
    replay_mode: Literal["intraday", "weekly"] = "intraday"
    sample_source: SampleSource = "backfilled_replay"
    persist_outcomes: bool = False

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        normalized = [_normalize_required_symbol(value) for value in values]
        if not normalized:
            raise ValueError("at least one symbol is required")
        return normalized

    @model_validator(mode="after")
    def validate_window(self) -> "ReplayRequest":
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class ReplaySignalRow(BaseModel):
    symbol: str
    asset_type: AssetType
    observed_at: datetime
    strategy_variant: str = "layered-v4"
    signal: DecisionSignal
    raw_score: float
    calibrated_confidence: float
    evidence_quality: EvidenceQuality
    execution_eligibility: ExecutionEligibility
    strategy_version: str
    market_status: MarketStatus
    provider_status: ProviderStatus
    entry_price: float
    future_price: float | None = None
    raw_return_pct: float | None = None
    friction_adjusted_return_pct: float | None = None
    horizon: OutcomeHorizon = "1w"


class ReplaySummary(BaseModel):
    total_snapshots: int
    actionable_signals: int
    eligible_signals: int
    blocked_signals: int
    win_rate: float | None = None
    avg_return: float | None = None
    avg_return_after_friction: float | None = None
    expectancy: float | None = None
    expectancy_after_friction: float | None = None


class ReplayResponse(BaseModel):
    strategy_id: str
    strategy_version: str
    strategy_variant: str = "layered-v4"
    start: datetime
    end: datetime
    interval_minutes: int
    warmup_bars: int
    apply_friction: bool
    friction: FrictionAssumptions
    assumptions: list[str]
    summary: ReplaySummary
    rows: list[ReplaySignalRow]


ConfidenceGrade = Literal["A", "B", "C", "D"]


class ProjectionWeek(BaseModel):
    week: int
    median: float
    optimistic_p75: float
    pessimistic_p25: float


class ProjectionResponse(BaseModel):
    base_amount: float = 100.0
    ticker: str
    signal: DecisionSignal
    score_band: str
    sample_count: int
    low_sample_size: bool = False
    regime: MarketStatus | None = None
    regime_adjusted: bool = False
    projections: list[ProjectionWeek] = []
    confidence_grade: ConfidenceGrade
    disclaimer: str = (
        "Projection based on historical outcomes of similar signals. "
        "Past performance does not guarantee future results."
    )
