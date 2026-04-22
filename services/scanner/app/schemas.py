from __future__ import annotations

from datetime import datetime
from typing import Literal
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
ExecutionEligibility = Literal["eligible", "blocked", "not_applicable", "review"]
DataGrade = Literal["decision", "research", "degraded"]
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


class VariantComparison(BaseModel):
    primary_variant: str
    comparison_variant: str
    comparison_signal: DecisionSignal = "HOLD"
    comparison_raw_score: float = 0.0
    comparison_calibrated_confidence: float = 0.0
    comparison_provider_status: ProviderStatus = "ok"
    comparison_evidence_quality: EvidenceQuality = "low"
    comparison_execution_eligibility: ExecutionEligibility = "not_applicable"
    changed: bool = False
    summary: str = "Shadow comparison disabled."


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
    strategy_variant: str = "layered-v4"
    score: float
    raw_score: float = 0.0
    calibrated_confidence: float = 0.0
    calibration_source: str = "raw"
    confidence_label: str = "calibrated_confidence"
    strategy_id: str = "scanner-directional"
    strategy_version: str = "v4.0-layered"
    strategy_primary_horizon: str = "1h"
    strategy_entry_assumption: str = ""
    strategy_exit_assumption: str = ""
    evidence_quality: EvidenceQuality = "low"
    evidence_quality_score: float = 0.0
    evidence_quality_reasons: list[str] = []
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
    bar_age_minutes: float | None = None
    freshness_flags: dict[str, str] = {}
    layer_details: dict = {}
    comparison: VariantComparison | None = None
    created_at: datetime


class ScanRun(BaseModel):
    run_id: str
    created_at: datetime
    market_status: MarketStatus
    strategy_variant: str = "layered-v4"
    shadow_enabled: bool = False
    scan_count: int
    watchlist_size: int
    alerts_sent: int = 0
    fear_greed_value: int | None = None
    fear_greed_label: str | None = None
    results: list[ScanResult]


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
    request_id: str | None = None


class OrderPreviewRequest(BaseModel):
    ticker: str
    side: OrderSide
    qty: float = Field(gt=0)
    order_type: OrderType = "market"
    limit_price: float | None = Field(default=None, gt=0)
    preview_audit_id: int | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)

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
    score_contributions: dict[str, float] = {}
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


class HorizonMetrics(BaseModel):
    horizon: Literal["15m", "1h", "1d"]
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


class OutcomeBaselineCheck(BaseModel):
    key: str
    horizon: Literal["15m", "1h", "1d"]
    evaluated_count: int
    mean_return: float | None = None
    meets_min_sample: bool
    passes_mean_return: bool
    passed: bool
    reason: str


class OutcomeBaselineSummary(BaseModel):
    primary_horizon: Literal["15m", "1h", "1d"]
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
    strategy_primary_horizon: str = "1h"
    strategy_entry_assumption: str | None = None
    strategy_exit_assumption: str | None = None
    signal_age_minutes: float | None = None
    confidence_bucket: str | None = None
    raw_score_bucket: str | None = None
    score_band: str | None = None
    horizon: str
    gate_evaluation_mode: str | None = None
    evidence_basis: str | None = None
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
    expectancy_after_friction: float | None = None
    false_positive_rate: float | None = None
    min_sample_met: bool = True
    is_underpowered: bool = False


class ValidationSummary(BaseModel):
    generated_at_field: str = "generated_at"
    start: datetime | None = None
    end: datetime | None = None
    primary_horizon: Literal["15m", "1h", "1d"]
    win_threshold_pct: float
    false_positive_threshold_pct: float
    total_signals: int
    evaluated_count: int
    pending_count: int
    overall: ValidationBucket
    in_sample: ValidationBucket | None = None
    out_of_sample: ValidationBucket | None = None
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
    primary_horizon: Literal["15m", "1h", "1d"]
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
    primary_horizon: Literal["15m", "1h", "1d"]
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
    compare_strategy_variant: str | None = None
    include_secondary_providers: bool = False
    apply_friction: bool = True

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
    comparison: VariantComparison | None = None
    entry_price: float
    future_price: float | None = None
    raw_return_pct: float | None = None
    friction_adjusted_return_pct: float | None = None
    horizon: Literal["15m", "1h", "1d"] = "1h"


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
    compare_strategy_variant: str | None = None
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