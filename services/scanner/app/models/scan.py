from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from app.db import Base


class ScanRunORM(Base):
    __tablename__ = "scan_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    market_status: Mapped[str] = mapped_column(String(16), index=True)
    strategy_variant: Mapped[str] = mapped_column(String(32), default="layered-v4", index=True)
    shadow_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    scan_count: Mapped[int] = mapped_column(Integer)
    watchlist_size: Mapped[int] = mapped_column(Integer)
    alerts_sent: Mapped[int] = mapped_column(Integer, default=0)
    fear_greed_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fear_greed_label: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ScanResultORM(Base):
    __tablename__ = "scan_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    asset_type: Mapped[str] = mapped_column(String(16), default="stock", index=True)
    strategy_variant: Mapped[str] = mapped_column(String(32), default="layered-v4", index=True)
    score: Mapped[float] = mapped_column(Float)
    calibrated_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    calibration_source: Mapped[str] = mapped_column(String(16), default="raw")
    buy_score: Mapped[float] = mapped_column(Float, default=0.0)
    sell_score: Mapped[float] = mapped_column(Float, default=0.0)
    decision_signal: Mapped[str] = mapped_column(String(16), default="HOLD", index=True)
    scoring_version: Mapped[str] = mapped_column(String(32), default="v4.0-layered")
    explanation: Mapped[str] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Float)
    price_change_pct: Mapped[float] = mapped_column(Float)
    relative_volume: Mapped[float] = mapped_column(Float)
    sentiment_score: Mapped[float] = mapped_column(Float)
    filing_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    breakout_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    market_status: Mapped[str] = mapped_column(String(16), index=True)
    sector_strength_score: Mapped[float] = mapped_column(Float, default=0.0)
    relative_strength_pct: Mapped[float] = mapped_column(Float, default=0.0)
    options_flow_score: Mapped[float] = mapped_column(Float, default=0.0)
    options_flow_summary: Mapped[str] = mapped_column(Text, default="No options signal.")
    options_flow_bullish: Mapped[bool] = mapped_column(Boolean, default=False)
    options_call_put_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    alert_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    news_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    news_source: Mapped[str] = mapped_column(String(32), default="none")
    news_cache_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_label: Mapped[str] = mapped_column(String(16), default="weak")
    data_quality: Mapped[str] = mapped_column(String(16), default="ok")
    volatility_regime: Mapped[str] = mapped_column(String(16), default="normal")
    benchmark_ticker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    benchmark_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    gate_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    gate_reason: Mapped[str] = mapped_column(Text, default="Signal gate not evaluated.")
    gate_checks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    coingecko_price_change_pct_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    coingecko_market_cap_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fear_greed_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fear_greed_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_status: Mapped[str] = mapped_column(String(16), default="ok")
    provider_warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_grade: Mapped[str] = mapped_column(String(16), default="research", index=True)
    bar_age_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    bar_as_of: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    freshness_flags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    layer_details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    comparison_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    readiness_score: Mapped[float] = mapped_column(Float, default=0.0)
    readiness_band: Mapped[str] = mapped_column(String(16), default="none")
    readiness_hard_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    readiness_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    selection_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_top_pick: Mapped[bool] = mapped_column(Boolean, default=False)


class SignalOutcomeORM(Base):
    __tablename__ = "signal_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    asset_type: Mapped[str] = mapped_column(String(16), default="stock", index=True)
    strategy_variant: Mapped[str] = mapped_column(String(32), default="layered-v4", index=True)
    signal: Mapped[str] = mapped_column(String(16), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    calibrated_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    calibration_source: Mapped[str] = mapped_column(String(16), default="raw")
    raw_score: Mapped[float] = mapped_column(Float, default=0.0)
    score_band: Mapped[str] = mapped_column(String(16), default="0-59", index=True)
    scoring_version: Mapped[str] = mapped_column(String(32), default="v4.0-layered")
    market_status: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    buy_score: Mapped[float] = mapped_column(Float, default=0.0)
    sell_score: Mapped[float] = mapped_column(Float, default=0.0)
    signal_label: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    gate_passed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    gate_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_grade: Mapped[str] = mapped_column(String(16), default="research", index=True)
    news_source: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    relative_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_strength_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    options_flow_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    options_flow_bullish: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    volatility_regime: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    data_quality: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    benchmark_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_price: Mapped[float] = mapped_column(Float)
    generated_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    price_after_15m: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_after_15m: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluated_at_15m: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_15m: Mapped[str] = mapped_column(String(16), default="pending")
    price_after_1h: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_after_1h: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluated_at_1h: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_1h: Mapped[str] = mapped_column(String(16), default="pending")
    price_after_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_after_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluated_at_1d: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_1d: Mapped[str] = mapped_column(String(16), default="pending")
    price_after_1w: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_after_1w: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluated_at_1w: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_1w: Mapped[str] = mapped_column(String(16), default="pending")
    sample_source: Mapped[str] = mapped_column(String(32), default="live_paper_forward", index=True)
    pattern_name: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class ExecutionAuditORM(Base):
    __tablename__ = "execution_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    asset_type: Mapped[str] = mapped_column(String(16), default="stock", index=True)
    side: Mapped[str] = mapped_column(String(16), index=True)
    order_type: Mapped[str] = mapped_column(String(16))
    qty: Mapped[float] = mapped_column(Float)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    idempotency_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    recommended_action_snapshot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="previewed", index=True)
    latest_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    notional_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_outcome_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    signal_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    signal_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    latest_signal: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_gate_horizon: Mapped[str | None] = mapped_column(String(16), nullable=True)
    evidence_basis: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trust_window_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trust_window_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trade_gate_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    trade_gate_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    broker_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_payload: Mapped[str] = mapped_column(Text, default="{}")
    request_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    broker_payload: Mapped[str | None] = mapped_column(Text, nullable=True)


class AutomationIntentORM(Base):
    __tablename__ = "automation_intents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    asset_type: Mapped[str] = mapped_column(String(16), default="stock", index=True)
    side: Mapped[str] = mapped_column(String(16), index=True)
    qty: Mapped[float] = mapped_column(Float)
    strategy_version: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizon: Mapped[str | None] = mapped_column(String(16), nullable=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    intent_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    intent_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    execution_audit_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    decision_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    request_count_used: Mapped[int] = mapped_column(Integer, default=0)
    request_count_avoided: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    incident_class: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class PaperPositionORM(Base):
    __tablename__ = "paper_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    intent_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    execution_audit_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    asset_type: Mapped[str] = mapped_column(String(16), default="stock", index=True)
    side: Mapped[str] = mapped_column(String(16), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    simulated_fill_price: Mapped[float] = mapped_column(Float)
    notional_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cost_basis_usd: Mapped[float] = mapped_column(Float, default=0.0)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    strategy_version: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class PredictionSnapshotORM(Base):
    __tablename__ = "prediction_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    asset_type: Mapped[str] = mapped_column(String(16), default="stock", index=True)
    signal: Mapped[str] = mapped_column(String(16), index=True)
    evidence_grade: Mapped[str] = mapped_column(String(16), default="Weak")
    entry_price: Mapped[float] = mapped_column(Float)
    range_low: Mapped[float] = mapped_column(Float)
    range_high: Mapped[float] = mapped_column(Float)
    horizon: Mapped[str] = mapped_column(String(16), default="1h", index=True)
    invalidation: Mapped[str] = mapped_column(Text, default="")
    methodology: Mapped[str] = mapped_column(String(32), default="structural_stop_target")
    generated_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    price_at_horizon: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    in_range: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    sample_source: Mapped[str] = mapped_column(String(32), default="live_paper_forward", index=True)
    pattern_name: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    pattern_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    invalidation_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    projected_range_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_window_status: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    exit_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    invalidation_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    protected_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    hold_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_window_helped: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # --- Phase 4 immutable live-forward provenance (all nullable for back-compat) ---
    # Existing pre-campaign rows keep these NULL and are rendered as "pre-campaign
    # evidence", excluded from campaign metrics.
    campaign_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    strategy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    code_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    feature_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    data_cutoff_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expected_friction_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    candidate_rank: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # selected | accepted_outside_top_n | rejected
    selection_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    resolve_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    resolved_late: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # SHA-256 over the immutable core prediction fields, set once at insert.
    record_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    policy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision_role: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    decision_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    learned_artifacts_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class EvidenceCampaignORM(Base):
    """A frozen strategy+config window over which live-forward evidence is collected.

    A meaningful change to the strategy or evidence-relevant configuration closes
    the active campaign and opens a new one, so incompatible results never mix.
    """

    __tablename__ = "evidence_campaigns"

    campaign_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), default="")
    strategy_version: Mapped[str] = mapped_column(String(32), default="")
    feature_version: Mapped[str] = mapped_column(String(32), default="")
    config_fingerprint: Mapped[str] = mapped_column(String(64), default="", index=True)
    code_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    effective_policy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    effective_decision_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    learned_artifacts_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    learned_artifacts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScanWindowORM(Base):
    """Expected scheduler window instances vs actual execution.

    Lets the app answer "did we scan when we should have?" and surface missed
    windows after downtime, sleep, or a skipped wake timer.
    """

    __tablename__ = "scan_windows"
    __table_args__ = (
        UniqueConstraint(
            "window_name", "expected_start", name="uq_scan_windows_name_start"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    window_name: Mapped[str] = mapped_column(String(48), index=True)
    expected_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    expected_end: Mapped[datetime] = mapped_column(DateTime)
    # executed | missed | partial | pending
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    scan_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class PaperLoopBreakerORM(Base):
    """Single-row persisted circuit breaker for paper-loop execution (dry-run)."""

    __tablename__ = "paper_loop_breaker"

    breaker_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    phase: Mapped[str] = mapped_column(String(16), default="closed", index=True)
    open_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failures_in_window: Mapped[int] = mapped_column(Integer, default=0)
    failures_window_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    probe_owner: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    probe_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class StrategyReplayRunORM(Base):
    __tablename__ = "strategy_replay_runs"

    replay_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    request_json: Mapped[str] = mapped_column(Text, default="{}")
    response_json: Mapped[str] = mapped_column(Text, default="{}")
    symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_count: Mapped[int] = mapped_column(Integer, default=0)


class DailyBarHistoryORM(Base):
    """Persistent, incremental daily OHLCV cache for reproducible walk-forward proof.

    Separate from the 24h TTL file cache used by live scans; append-only per
    (symbol, asset_type, bar_date) so provider limits do not block long-range proof.
    """

    __tablename__ = "daily_bar_history"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "asset_type", "bar_date", name="uq_daily_bar_history_symbol_asset_date"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    asset_type: Mapped[str] = mapped_column(String(16), default="stock", index=True)
    bar_date: Mapped[str] = mapped_column(String(10), index=True)
    bar_ts: Mapped[str] = mapped_column(String(40))
    open: Mapped[float] = mapped_column(Float, default=0.0)
    high: Mapped[float] = mapped_column(Float, default=0.0)
    low: Mapped[float] = mapped_column(Float, default=0.0)
    close: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(16), default="alpaca")
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    # Corporate-action adjustment applied by the provider for this row. Stocks are
    # split-adjusted; crypto has no corporate actions ("none").
    adjustment_policy: Mapped[str] = mapped_column(String(16), default="raw")
    # Point-in-time revision tracking: how many times a refetch changed this row,
    # and when it last changed. First write leaves these at 0 / NULL.
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    revised_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WalkForwardRunORM(Base):
    __tablename__ = "walk_forward_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(16), default="complete", index=True)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    window_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    holdout_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    validation_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    prediction_count: Mapped[int] = mapped_column(Integer, default=0)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    verdict_json: Mapped[str] = mapped_column(Text, default="{}")
    coverage_json: Mapped[str] = mapped_column(Text, default="{}")
    # Run manifest for deterministic, versioned, auditable reruns.
    config_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    code_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    policy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    learned_artifacts_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    learned_artifacts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    universe_json: Mapped[str] = mapped_column(Text, default="[]")
    data_quality_json: Mapped[str] = mapped_column(Text, default="{}")


class WalkForwardPredictionORM(Base):
    """One stored historical walk-forward top-candidate prediction and its 1w resolution."""

    __tablename__ = "walk_forward_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, index=True)
    asset_type: Mapped[str] = mapped_column(String(16), default="stock", index=True)
    ticker: Mapped[str] = mapped_column(String(24), index=True)
    selection_rank: Mapped[int] = mapped_column(Integer, default=0)
    sample_source: Mapped[str] = mapped_column(String(32), default="historical", index=True)
    # Which DecisionPolicy produced this prediction (walk-forward evaluates
    # replayable policies; NULL means the pre-policy weekly path).
    policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    policy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    learned_artifacts_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    pattern_name: Mapped[str] = mapped_column(String(64), default="range_neutral")
    decision_signal: Mapped[str] = mapped_column(String(16), default="BUY")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    upside_probability_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    historical_hit_rate_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    entry_price: Mapped[float] = mapped_column(Float, default=0.0)
    projected_range_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    projected_range_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    invalidation_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_growing_signal: Mapped[str | None] = mapped_column(Text, nullable=True)
    horizon: Mapped[str] = mapped_column(String(8), default="1w")
    forward_days: Mapped[int] = mapped_column(Integer, default=7)
    expected_friction_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    resolve_due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    price_after_1w: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_after_1w: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_range: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    accuracy_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exit_window_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exit_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    invalidation_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    protected_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    hold_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_window_helped: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    exit_conflict: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
