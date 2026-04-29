from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import require_read_access
from app.config import get_settings
from app.db import check_database_connection, get_schema_status
from app.dependencies import (
    get_automation_service,
    get_coinbase_market_data_service,
    get_journal_repository,
    get_scan_repository,
    get_scheduler_service,
    get_scanner_service,
)
from app.core.strategy_contract import get_current_strategy_contract
from app.schemas import (
    AutomationStatusResponse,
    CryptoMarketSnapshotResponse,
    DecisionRow,
    ExecutionAuditSummary,
    ExecutionAlignmentResponse,
    HealthResponse,
    JournalAnalyticsResponse,
    JournalEntryResponse,
    PaperLedgerSummaryResponse,
    PaperPositionSummary,
    ProjectionResponse,
    ProjectionWeek,
    ScanRun,
    StrategyContractResponse,
    StrategySignalContractResponse,
    ThresholdSweepResponse,
    ValidationSummary,
)
from app.services.journal_repository import JournalRepository
from app.services.automation import AutomationService
from app.services.coinbase_market_data import CoinbaseMarketDataService
from app.services.readiness import compute_scan_freshness_fields, evaluate_operational_readiness
from app.services.repository import ScanRepository
from app.services.scheduler import SchedulerService
from app.services.scanner import ScannerService

router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(require_read_access)])


def _validate_time_window(
    *,
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    if start is not None and end is not None and end <= start:
        raise ValueError("end must be greater than start")
    return start, end


def _build_health_response(
    request: Request,
    *,
    live: bool,
    ready: bool,
    scheduler_service: SchedulerService,
    scan_repository: ScanRepository,
) -> HealthResponse:
    settings = get_settings()
    schema_status = get_schema_status()
    scheduler_state = scheduler_service.state()
    last_scan_at = scan_repository.get_latest_run_timestamp()
    trust_snapshot = scan_repository.get_trust_readiness_snapshot()
    gate_buckets = {bucket.key: bucket for bucket in trust_snapshot.summary.by_signal_and_gate}
    last_scan_age_minutes, scan_fresh = compute_scan_freshness_fields(
        last_scan_at=last_scan_at,
        health_max_stale_minutes=settings.health_max_stale_minutes,
    )
    return HealthResponse(
        ok=live if not ready else ready,
        env=settings.app_env,
        app_version=settings.app_version,
        ready=ready,
        live=live,
        schema_ok=schema_status.ok,
        missing_schema_items=schema_status.missing_items,
        scheduler_running=scheduler_state.running,
        last_scan_at=last_scan_at,
        last_scan_age_minutes=last_scan_age_minutes,
        max_stale_minutes=settings.health_max_stale_minutes,
        scan_fresh=scan_fresh,
        scheduler_enabled=scheduler_state.enabled,
        scheduler_interval_seconds=scheduler_state.interval_seconds,
        next_scan_due_at=scheduler_state.next_run_at,
        last_scheduler_run_started_at=scheduler_state.last_run_started_at,
        last_scheduler_run_finished_at=scheduler_state.last_run_finished_at,
        last_scheduler_error=scheduler_state.last_error,
        trust_window_start=trust_snapshot.window.start,
        trust_window_end=trust_snapshot.window.end,
        trust_recent_window_days=trust_snapshot.window.days,
        trust_total_signals=trust_snapshot.summary.total_signals,
        trust_evaluated_count=trust_snapshot.summary.evaluated_count,
        trust_pending_count=trust_snapshot.summary.pending_count,
        trust_buy_passed_evaluated_count=(gate_buckets.get("BUY:passed").evaluated_count if gate_buckets.get("BUY:passed") else 0),
        trust_sell_passed_evaluated_count=(gate_buckets.get("SELL:passed").evaluated_count if gate_buckets.get("SELL:passed") else 0),
        trust_threshold_evidence_status=trust_snapshot.threshold.recommendation.evidence_status,
        trust_threshold_source=trust_snapshot.threshold.recommendation.source,
        trust_threshold_warning_count=len(trust_snapshot.threshold.recommendation.warnings),
        trust_evidence_ready=trust_snapshot.threshold.recommendation.evidence_status == "ready",
        pending_due_15m_count=trust_snapshot.pending_due_15m_count,
        pending_due_1h_count=trust_snapshot.pending_due_1h_count,
        pending_due_1d_count=trust_snapshot.pending_due_1d_count,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/livez", response_model=HealthResponse)
async def livez(
    request: Request,
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> HealthResponse:
    return _build_health_response(
        request,
        live=True,
        ready=True,
        scheduler_service=scheduler_service,
        scan_repository=scan_repository,
    )


@router.get("/readyz", response_model=HealthResponse)
async def readyz(
    request: Request,
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> HealthResponse:
    settings = get_settings()
    schema_status = get_schema_status()
    scheduler_state = scheduler_service.state()
    last_scan_at = scan_repository.get_latest_run_timestamp()
    trust_snapshot = scan_repository.get_trust_readiness_snapshot()
    gate_buckets = {bucket.key: bucket for bucket in trust_snapshot.summary.by_signal_and_gate}
    last_scan_age_minutes, scan_fresh = compute_scan_freshness_fields(
        last_scan_at=last_scan_at,
        health_max_stale_minutes=settings.health_max_stale_minutes,
    )
    ready, _ = evaluate_operational_readiness(
        scan_repository=scan_repository,
        settings=settings,
    )
    return HealthResponse(
        ok=ready,
        env=settings.app_env,
        app_version=settings.app_version,
        ready=ready,
        live=True,
        schema_ok=schema_status.ok,
        missing_schema_items=schema_status.missing_items,
        scheduler_running=scheduler_state.running,
        last_scan_at=last_scan_at,
        last_scan_age_minutes=last_scan_age_minutes,
        max_stale_minutes=settings.health_max_stale_minutes,
        scan_fresh=scan_fresh,
        scheduler_enabled=scheduler_state.enabled,
        scheduler_interval_seconds=scheduler_state.interval_seconds,
        next_scan_due_at=scheduler_state.next_run_at,
        last_scheduler_run_started_at=scheduler_state.last_run_started_at,
        last_scheduler_run_finished_at=scheduler_state.last_run_finished_at,
        last_scheduler_error=scheduler_state.last_error,
        trust_window_start=trust_snapshot.window.start,
        trust_window_end=trust_snapshot.window.end,
        trust_recent_window_days=trust_snapshot.window.days,
        trust_total_signals=trust_snapshot.summary.total_signals,
        trust_evaluated_count=trust_snapshot.summary.evaluated_count,
        trust_pending_count=trust_snapshot.summary.pending_count,
        trust_buy_passed_evaluated_count=(gate_buckets.get("BUY:passed").evaluated_count if gate_buckets.get("BUY:passed") else 0),
        trust_sell_passed_evaluated_count=(gate_buckets.get("SELL:passed").evaluated_count if gate_buckets.get("SELL:passed") else 0),
        trust_threshold_evidence_status=trust_snapshot.threshold.recommendation.evidence_status,
        trust_threshold_source=trust_snapshot.threshold.recommendation.source,
        trust_threshold_warning_count=len(trust_snapshot.threshold.recommendation.warnings),
        trust_evidence_ready=trust_snapshot.threshold.recommendation.evidence_status == "ready",
        pending_due_15m_count=trust_snapshot.pending_due_15m_count,
        pending_due_1h_count=trust_snapshot.pending_due_1h_count,
        pending_due_1d_count=trust_snapshot.pending_due_1d_count,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/startupz", response_model=HealthResponse)
async def startupz(
    request: Request,
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> HealthResponse:
    db_ok = check_database_connection()
    return _build_health_response(
        request,
        live=True,
        ready=db_ok,
        scheduler_service=scheduler_service,
        scan_repository=scan_repository,
    )


@router.get("/health", response_model=HealthResponse)
async def health(
    request: Request,
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> HealthResponse:
    return await readyz(request, scheduler_service, scan_repository)


@router.get("/strategy/contract", response_model=StrategyContractResponse)
async def get_strategy_contract() -> StrategyContractResponse:
    contract = get_current_strategy_contract()
    return StrategyContractResponse(
        strategy_id=contract.strategy_id,
        strategy_version=contract.strategy_version,
        name=contract.name,
        primary_holding_horizon=contract.primary_holding_horizon,
        entry_assumption=contract.entry_assumption,
        exit_assumption=contract.exit_assumption,
        buy_definition=StrategySignalContractResponse(
            signal=contract.buy_definition.signal,
            intent=contract.buy_definition.intent,
            operational_meaning=contract.buy_definition.operational_meaning,
        ),
        sell_definition=StrategySignalContractResponse(
            signal=contract.sell_definition.signal,
            intent=contract.sell_definition.intent,
            operational_meaning=contract.sell_definition.operational_meaning,
        ),
        hold_definition=StrategySignalContractResponse(
            signal=contract.hold_definition.signal,
            intent=contract.hold_definition.intent,
            operational_meaning=contract.hold_definition.operational_meaning,
        ),
        evidence_inputs=list(contract.evidence_inputs),
        critical_provider_inputs=list(contract.critical_provider_inputs),
        supportive_provider_inputs=list(contract.supportive_provider_inputs),
        known_limitations=list(contract.known_limitations),
    )


@protected_router.get("/scan/latest", response_model=ScanRun | None)
async def get_latest_scan(
    scanner_service: ScannerService = Depends(get_scanner_service),
) -> ScanRun | None:
    return scanner_service.latest()


@protected_router.get("/scan/history", response_model=list[ScanRun])
async def get_scan_history(
    limit: int = Query(default=12, ge=1, le=100),
    scanner_service: ScannerService = Depends(get_scanner_service),
) -> list[ScanRun]:
    return scanner_service.history(limit=limit)


@protected_router.get("/market/crypto/latest", response_model=CryptoMarketSnapshotResponse)
async def get_latest_crypto_market_prices(
    market_data_service: CoinbaseMarketDataService = Depends(get_coinbase_market_data_service),
) -> CryptoMarketSnapshotResponse:
    return CryptoMarketSnapshotResponse(prices=market_data_service.list_snapshots())


@protected_router.get("/dashboard/decisions/latest", response_model=list[DecisionRow])
async def get_latest_decisions(
    limit: int = Query(default=20, ge=1, le=100),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> list[DecisionRow]:
    return scan_repository.get_latest_decisions(limit=limit)


@protected_router.get("/signals/validation/summary", response_model=ValidationSummary)
async def get_signal_validation_summary(
    asset_type: str | None = Query(default=None, pattern="^(stock|crypto)$"),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    regime: str | None = Query(default=None, pattern="^(bullish|neutral|bearish)$"),
    data_grade: str | None = Query(default=None, pattern="^(decision|research|degraded)$"),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> ValidationSummary:
    try:
        start, end = _validate_time_window(start=start, end=end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return scan_repository.get_signal_validation_summary(
        asset_type=asset_type,
        start=start,
        end=end,
        regime=regime,
        data_grade=data_grade,
    )


@protected_router.get(
    "/signals/validation/threshold-sweep",
    response_model=ThresholdSweepResponse,
)
async def get_validation_threshold_sweep(
    asset_type: str | None = Query(default=None, pattern="^(stock|crypto)$"),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> ThresholdSweepResponse:
    try:
        start, end = _validate_time_window(start=start, end=end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return scan_repository.get_validation_threshold_sweep(
        asset_type=asset_type,
        start=start,
        end=end,
    )


@protected_router.get(
    "/signals/validation/execution-alignment",
    response_model=ExecutionAlignmentResponse,
)
async def get_execution_alignment_summary(
    asset_type: str | None = Query(default=None, pattern="^(stock|crypto)$"),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    friction_scenario: str = Query(default="base", pattern="^(base|stressed|worst)$"),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> ExecutionAlignmentResponse:
    try:
        start, end = _validate_time_window(start=start, end=end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return scan_repository.get_execution_alignment_summary(
        asset_type=asset_type,
        start=start,
        end=end,
        friction_scenario=friction_scenario,
    )


@protected_router.get("/journal/entries", response_model=list[JournalEntryResponse])
async def list_journal_entries(
    limit: int = Query(default=50, ge=1, le=200),
    journal_repository: JournalRepository = Depends(get_journal_repository),
) -> list[JournalEntryResponse]:
    return journal_repository.list_entries(limit=limit)


@protected_router.get("/orders/audits", response_model=list[ExecutionAuditSummary])
async def list_execution_audits(
    limit: int = Query(default=50, ge=1, le=200),
    lifecycle_status: str | None = Query(default=None),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> list[ExecutionAuditSummary]:
    return scan_repository.list_execution_audits(
        limit=limit,
        lifecycle_status=lifecycle_status,
    )


@protected_router.get("/automation/status", response_model=AutomationStatusResponse)
async def get_automation_status(
    automation_service: AutomationService = Depends(get_automation_service),
) -> AutomationStatusResponse:
    return automation_service.status()


@protected_router.get("/paper/ledger", response_model=list[PaperPositionSummary])
async def get_paper_ledger(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, pattern="^(open|closed)$"),
    symbol: str | None = Query(default=None, min_length=1),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> list[PaperPositionSummary]:
    return scan_repository.list_paper_positions(
        limit=limit,
        offset=offset,
        status=status,
        symbol=symbol,
    )


@protected_router.get("/paper/ledger/summary", response_model=PaperLedgerSummaryResponse)
async def get_paper_ledger_summary(
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> PaperLedgerSummaryResponse:
    return scan_repository.get_paper_ledger_summary()


@protected_router.get("/journal/analytics", response_model=JournalAnalyticsResponse)
async def get_journal_analytics(
    journal_repository: JournalRepository = Depends(get_journal_repository),
) -> JournalAnalyticsResponse:
    return journal_repository.get_analytics()


VOLATILITY_DECAY_FACTOR = 0.85
TRADING_DAYS_PER_WEEK = 5
PROJECTION_WEEKS = 4
BASE_AMOUNT = 100.0


def _compute_confidence_grade(
    sample_count: int, *, in_band: bool, regime_data: bool
) -> str:
    if sample_count < 10:
        return "D"
    if not in_band:
        return "C"
    if sample_count >= 30 and regime_data:
        return "A"
    return "B"


def _project_weeks(
    *,
    median_pct: float,
    p25_pct: float,
    p75_pct: float,
) -> list[ProjectionWeek]:
    weeks: list[ProjectionWeek] = []
    med_val = BASE_AMOUNT
    opt_val = BASE_AMOUNT
    pes_val = BASE_AMOUNT

    for week in range(1, PROJECTION_WEEKS + 1):
        decay = VOLATILITY_DECAY_FACTOR ** (week - 1)
        med_daily = 1 + (median_pct / 100) * decay
        opt_daily = 1 + (p75_pct / 100) * decay
        pes_daily = 1 + (p25_pct / 100) * decay

        for _ in range(TRADING_DAYS_PER_WEEK):
            med_val *= med_daily
            opt_val *= opt_daily
            pes_val *= pes_daily

        weeks.append(
            ProjectionWeek(
                week=week,
                median=round(med_val, 2),
                optimistic_p75=round(opt_val, 2),
                pessimistic_p25=round(pes_val, 2),
            )
        )

    return weeks


@protected_router.get(
    "/scan/projection/{ticker:path}",
    response_model=ProjectionResponse,
)
async def get_signal_projection(
    ticker: str,
    signal: str = Query(default="BUY", pattern="^(BUY|SELL)$"),
    score_band: str = Query(default="0-59"),
    scan_repository: ScanRepository = Depends(get_scan_repository),
    scanner_service: ScannerService = Depends(get_scanner_service),
) -> ProjectionResponse:
    ticker_upper = ticker.strip().upper()
    if not ticker_upper:
        raise HTTPException(status_code=422, detail="ticker is required")

    latest = scanner_service.latest()
    current_regime = latest.market_status if latest else None

    stats = scan_repository.get_projection_outcome_stats(
        signal=signal,
        score_band=score_band,
        current_regime=current_regime,
    )

    in_band = not stats.low_sample_size
    grade = _compute_confidence_grade(
        stats.sample_count, in_band=in_band, regime_data=stats.regime_data_available
    )

    if grade == "D" or stats.median_daily_return_pct is None:
        return ProjectionResponse(
            base_amount=BASE_AMOUNT,
            ticker=ticker_upper,
            signal=signal,
            score_band=score_band,
            sample_count=stats.sample_count,
            low_sample_size=stats.low_sample_size,
            regime=current_regime,
            regime_adjusted=False,
            projections=[],
            confidence_grade="D",
        )

    med = stats.median_daily_return_pct
    p25 = stats.p25_daily_return_pct or med
    p75 = stats.p75_daily_return_pct or med

    if stats.regime_shift_pct is not None:
        med += stats.regime_shift_pct
        p25 += stats.regime_shift_pct
        p75 += stats.regime_shift_pct

    return ProjectionResponse(
        base_amount=BASE_AMOUNT,
        ticker=ticker_upper,
        signal=signal,
        score_band=score_band,
        sample_count=stats.sample_count,
        low_sample_size=stats.low_sample_size,
        regime=current_regime,
        regime_adjusted=stats.regime_data_available,
        projections=_project_weeks(median_pct=med, p25_pct=p25, p75_pct=p75),
        confidence_grade=grade,
    )
