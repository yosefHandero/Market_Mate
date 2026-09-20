from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.auth import require_read_access
from app.config import get_settings
from app.db import check_database_connection, get_schema_status
from app.dependencies import (
    get_automation_service,
    get_coinbase_market_data_service,
    get_scan_repository,
    get_scheduler_service,
    get_scanner_service,
    get_walk_forward_repository,
)
from app.core.freshness_policy import (
    row_has_bad_freshness_flags,
    row_is_bar_stale,
    row_is_severely_stale,
    row_is_unusable_or_stale,
    unified_bar_freshness_max_age_minutes,
)
from app.core.evidence_contract import evidence_track_manifest
from app.core.strategy_contract import get_current_strategy_contract
from app.schemas import (
    AutomationStatusResponse,
    CryptoMarketSnapshotResponse,
    DecisionRow,
    EvidenceTrackDescriptor,
    ExecutionAuditSummary,
    HealthResponse,
    PaperLedgerSummaryResponse,
    PaperPositionSummary,
    ProofLoopMetrics,
    ProofSummaryResponse,
    ScanResult,
    ScanRun,
    StrategyContractResponse,
    StrategySignalContractResponse,
    SystemReadinessAutomation,
    SystemReadinessDiagnostics,
    SystemReadinessFreshnessSummary,
    SystemReadinessProviderSummary,
    SystemReadinessResponse,
)
from app.services.automation import AutomationService
from app.services.brain_runtime import BrainRuntime
from app.services.coinbase_market_data import CoinbaseMarketDataService
from app.services.readiness import compute_scan_freshness_fields, evaluate_operational_readiness
from app.services.repository import ScanRepository
from app.services.walk_forward_repository import WalkForwardRepository
from app.services.scheduler import SchedulerService
from app.services.scanner import ScannerService

router = APIRouter()


def require_schema_ready() -> None:
    """Return 503 (not 500) when the DB schema is behind the ORM models."""
    schema_status = get_schema_status()
    if not schema_status.ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": (
                    "Database schema is incomplete. Run: cd services/scanner && alembic upgrade head"
                ),
                "missing_schema_items": schema_status.missing_items,
            },
        )


protected_router = APIRouter(
    dependencies=[Depends(require_read_access), Depends(require_schema_ready)],
)


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
    if not schema_status.ok:
        return HealthResponse(
            ok=live,
            env=settings.app_env,
            app_version=settings.app_version,
            ready=False,
            live=live,
            schema_ok=False,
            missing_schema_items=schema_status.missing_items,
            scheduler_running=scheduler_state.running,
            worker_alive=scheduler_state.worker_alive,
            last_worker_heartbeat_at=scheduler_state.worker_heartbeat_at,
            scheduler_enabled=scheduler_state.enabled,
            scheduler_interval_seconds=settings.scan_interval_seconds,
            next_scan_due_at=scheduler_state.next_run_at,
            last_scheduler_run_started_at=scheduler_state.last_run_started_at,
            last_scheduler_run_finished_at=scheduler_state.last_run_finished_at,
            last_scheduler_error=scheduler_state.last_error,
            max_stale_minutes=settings.health_max_stale_minutes,
            request_id=getattr(request.state, "request_id", None),
        )
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
        worker_alive=scheduler_state.worker_alive,
        last_worker_heartbeat_at=scheduler_state.worker_heartbeat_at,
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
        pending_due_1w_count=trust_snapshot.pending_due_1w_count,
        request_id=getattr(request.state, "request_id", None),
    )


def _provider_rank(status_value: str | None) -> int:
    normalized = (status_value or "").strip().lower()
    if normalized in {"critical", "error"}:
        return 3
    if normalized == "degraded":
        return 2
    if normalized in {"ok", "healthy"}:
        return 0
    return 1


def _row_provider_critical(row: ScanResult) -> bool:
    return (row.provider_status or "").strip().lower() in {"critical", "error"}


def _row_has_bad_freshness_flags(row: ScanResult) -> bool:
    return row_has_bad_freshness_flags(row)


def _row_severely_stale(row: ScanResult, settings) -> bool:
    return row_is_severely_stale(row, settings)


def _row_unusable_or_stale(row: ScanResult, settings) -> bool:
    return row_is_unusable_or_stale(row, settings)


def _provider_summary(rows: list[ScanResult]) -> SystemReadinessProviderSummary:
    if not rows:
        return SystemReadinessProviderSummary()
    statuses = [row.provider_status or "unknown" for row in rows]
    worst_status = max(statuses, key=_provider_rank)
    return SystemReadinessProviderSummary(
        worst_status=(worst_status or "unknown").strip().lower(),
        total_count=len(rows),
        critical_count=sum(1 for row in rows if _row_provider_critical(row)),
        degraded_count=sum(1 for row in rows if (row.provider_status or "").strip().lower() == "degraded"),
    )


def _freshness_summary(
    *,
    latest_run: ScanRun | None,
    last_scan_age_minutes: float | None,
    scan_fresh: bool | None,
    max_stale_minutes: int,
) -> SystemReadinessFreshnessSummary:
    settings = get_settings()
    bar_max_age_minutes = unified_bar_freshness_max_age_minutes(settings)
    rows = latest_run.results if latest_run else []
    return SystemReadinessFreshnessSummary(
        last_scan_at=latest_run.created_at if latest_run else None,
        last_scan_age_minutes=last_scan_age_minutes,
        max_stale_minutes=max_stale_minutes,
        scan_fresh=scan_fresh,
        total_count=len(rows),
        stale_count=sum(
            1
            for row in rows
            if row_is_bar_stale(row, settings) or _row_has_bad_freshness_flags(row)
        ),
        severe_stale_count=sum(
            1 for row in rows if _row_severely_stale(row, settings)
        ),
    )

def _build_system_readiness_response(
    request: Request,
    *,
    scheduler_service: SchedulerService,
    scan_repository: ScanRepository,
    automation_service: AutomationService,
) -> SystemReadinessResponse:
    settings = get_settings()
    db_ok = check_database_connection()
    schema_status = get_schema_status()
    scheduler_state = scheduler_service.state()
    automation_status = automation_service.status()
    latest_run = scan_repository.get_latest_run() if db_ok and schema_status.ok else None
    rows = latest_run.results if latest_run else []
    last_scan_at = latest_run.created_at if latest_run else None
    last_scan_age_minutes, scan_fresh = compute_scan_freshness_fields(
        last_scan_at=last_scan_at,
        health_max_stale_minutes=settings.health_max_stale_minutes,
    )
    provider = _provider_summary(rows)
    freshness = _freshness_summary(
        latest_run=latest_run,
        last_scan_age_minutes=last_scan_age_minutes,
        scan_fresh=scan_fresh,
        max_stale_minutes=settings.health_max_stale_minutes,
    )
    breaker_state = automation_status.breaker.state if automation_status.breaker else "unknown"
    automation_ready = (
        automation_status.enabled
        and scheduler_state.enabled
        and (scheduler_state.running or scheduler_state.worker_alive)
        and not automation_status.kill_switch_enabled
        and breaker_state != "open"
    )
    automation_summary = SystemReadinessAutomation(
        scheduler_enabled=scheduler_state.enabled,
        scheduler_running=scheduler_state.running,
        worker_alive=scheduler_state.worker_alive,
        automation_enabled=automation_status.enabled,
        automation_phase=automation_status.phase,
        automation_ready=automation_ready,
        dry_run_only=automation_status.dry_run_only,
        kill_switch_enabled=automation_status.kill_switch_enabled,
        breaker_state=breaker_state,
    )

    reasons: list[str] = []
    safety_blockers: list[str] = []
    if not db_ok:
        reasons.append("Database unavailable")
        safety_blockers.append("Database unavailable")
    if not schema_status.ok:
        reasons.append("Schema check failed")
        safety_blockers.append("Schema check failed")
    if automation_status.kill_switch_enabled:
        reasons.append("Kill switch on")
        safety_blockers.append("Kill switch on")
    if breaker_state == "open":
        reasons.append("Circuit breaker open")
        safety_blockers.append("Circuit breaker open")
    if scan_fresh is False or (rows and all(_row_severely_stale(row, settings) for row in rows)):
        reasons.append("Severe global freshness failure")
    if rows and all(_row_provider_critical(row) and _row_unusable_or_stale(row, settings) for row in rows):
        reasons.append("Provider critical with unusable/stale data")

    top_rejection_reasons: list[dict[str, object]] = []
    pending_prediction_resolutions = 0
    if db_ok and schema_status.ok:
        try:
            top_rejection_reasons = scan_repository.get_top_rejection_reasons()
            pending_prediction_resolutions = scan_repository.get_pending_prediction_count()
        except Exception:
            top_rejection_reasons = []
            pending_prediction_resolutions = 0

    buy_count = sum(1 for row in rows if (row.decision_signal or "").upper() == "BUY")
    # Candidate shortage explains the available results without blocking paper use.
    candidate_shortage = bool(rows) and buy_count < 3

    if not reasons:
        reasons.append("Core safety and data checks pass")

    diagnostics = SystemReadinessDiagnostics(
        top_rejection_reasons=top_rejection_reasons,
        pending_prediction_resolutions=pending_prediction_resolutions,
        candidate_shortage=candidate_shortage,
    )

    return SystemReadinessResponse(
        status="FAIL" if safety_blockers or reasons != ["Core safety and data checks pass"] else "PASS",
        reasons=reasons,
        safety_blockers=safety_blockers,
        automation=automation_summary,
        provider=provider,
        freshness=freshness,
        diagnostics=diagnostics,
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
    response: Response,
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> HealthResponse:
    settings = get_settings()
    schema_status = get_schema_status()
    if not schema_status.ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            ok=False,
            env=settings.app_env,
            app_version=settings.app_version,
            ready=False,
            live=True,
            schema_ok=False,
            missing_schema_items=schema_status.missing_items,
            max_stale_minutes=settings.health_max_stale_minutes,
            request_id=getattr(request.state, "request_id", None),
        )
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
        worker_alive=scheduler_state.worker_alive,
        last_worker_heartbeat_at=scheduler_state.worker_heartbeat_at,
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
        pending_due_1w_count=trust_snapshot.pending_due_1w_count,
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
    response: Response,
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> HealthResponse:
    return await readyz(request, response, scheduler_service, scan_repository)


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


@protected_router.get("/system/readiness", response_model=SystemReadinessResponse)
async def get_system_readiness(
    request: Request,
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    scan_repository: ScanRepository = Depends(get_scan_repository),
    automation_service: AutomationService = Depends(get_automation_service),
) -> SystemReadinessResponse:
    return _build_system_readiness_response(
        request,
        scheduler_service=scheduler_service,
        scan_repository=scan_repository,
        automation_service=automation_service,
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
    latest = scan_repository.get_latest_run()
    mark_prices = {row.ticker: float(row.price) for row in (latest.results if latest else [])}
    return scan_repository.get_paper_ledger_summary(
        mark_prices=mark_prices or None,
    )


@protected_router.get("/proof/summary", response_model=ProofSummaryResponse)
async def get_proof_summary(
    scan_repository: ScanRepository = Depends(get_scan_repository),
    walk_forward_repository: WalkForwardRepository = Depends(get_walk_forward_repository),
) -> ProofSummaryResponse:
    settings = get_settings()
    latest = scan_repository.get_latest_run()
    mark_prices = {row.ticker: float(row.price) for row in (latest.results if latest else [])}
    ledger_data = scan_repository.get_paper_ledger_summary(mark_prices=mark_prices or None)
    ledger = (
        ledger_data
        if isinstance(ledger_data, PaperLedgerSummaryResponse)
        else PaperLedgerSummaryResponse.model_validate(ledger_data)
    )
    audits = scan_repository.list_execution_audits(limit=200)
    dry_runs = sum(1 for audit in audits if audit.lifecycle_status == "dry_run")
    previewed = sum(1 for audit in audits if audit.lifecycle_status == "previewed")
    blocked = sum(
        1
        for audit in audits
        if audit.trade_gate_allowed is False or audit.lifecycle_status == "blocked"
    )
    last_scan_at = scan_repository.get_latest_run_timestamp()
    _, scan_fresh = compute_scan_freshness_fields(
        last_scan_at=last_scan_at,
        health_max_stale_minutes=settings.health_max_stale_minutes,
    )
    policy_promotion = BrainRuntime(
        settings=settings,
        repository=scan_repository,
        walk_forward_repository=walk_forward_repository,
    ).promotion_report_response()
    return ProofSummaryResponse(
        generated_at=datetime.now(timezone.utc),
        ledger=ledger,
        loop_metrics=ProofLoopMetrics(
            recent_dry_runs=dry_runs,
            recent_previewed=previewed,
            recent_blocked=blocked,
            total_audits=len(audits),
        ),
        prediction_accuracy=scan_repository.get_prediction_accuracy_summary(),
        confidence_performance=scan_repository.get_confidence_performance(),
        exit_window_accuracy=scan_repository.get_exit_window_accuracy_summary(),
        weekly_evidence=scan_repository.get_weekly_evidence_progress(),
        walk_forward=walk_forward_repository.get_latest_run_summary(),
        live_forward=scan_repository.get_live_forward_progress(),
        evidence_contract=[
            EvidenceTrackDescriptor(**track) for track in evidence_track_manifest()
        ],
        last_scan_at=last_scan_at,
        scan_fresh=scan_fresh,
        mark_prices_source="latest_scan",
        note=(
            "Unrealized P/L uses latest scan prices. Horizon closes use live market prices."
            if ledger.open_positions
            else None
        ),
        ruler_version=policy_promotion.ruler_version,
        ruler_fingerprint=policy_promotion.ruler_fingerprint,
        policy_promotion=policy_promotion,
    )
