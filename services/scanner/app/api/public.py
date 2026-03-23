from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_read_access
from app.config import get_settings
from app.db import check_database_connection, get_schema_status
from app.dependencies import (
    get_journal_repository,
    get_scan_repository,
    get_scheduler_service,
    get_scanner_service,
)
from app.observability import metrics
from app.schemas import (
    DecisionRow,
    ExecutionAlignmentResponse,
    HealthResponse,
    JournalAnalyticsResponse,
    JournalEntryResponse,
    MetricsResponse,
    ScanRun,
    SignalOutcome,
    SignalOutcomeSummary,
    ThresholdSweepResponse,
    ValidationSummary,
)
from app.services.journal_repository import JournalRepository
from app.services.repository import ScanRepository
from app.services.scheduler import SchedulerService
from app.services.scanner import ScannerService

router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(require_read_access)])


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
    return HealthResponse(
        ok=live if not ready else ready,
        env=settings.app_env,
        app_version=settings.app_version,
        ready=ready,
        live=live,
        schema_ok=schema_status.ok,
        missing_schema_items=schema_status.missing_items,
        scheduler_running=scheduler_service.running(),
        last_scan_at=scan_repository.get_latest_run_timestamp(),
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
    db_ok = check_database_connection()
    schema_status = get_schema_status()
    return HealthResponse(
        ok=db_ok and schema_status.ok,
        env=get_settings().app_env,
        app_version=get_settings().app_version,
        ready=db_ok and schema_status.ok,
        live=True,
        schema_ok=schema_status.ok,
        missing_schema_items=schema_status.missing_items,
        scheduler_running=scheduler_service.running(),
        last_scan_at=scan_repository.get_latest_run_timestamp(),
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


@protected_router.get("/dashboard/decisions/latest", response_model=list[DecisionRow])
async def get_latest_decisions(
    limit: int = Query(default=20, ge=1, le=100),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> list[DecisionRow]:
    return scan_repository.get_latest_decisions(limit=limit)


@protected_router.get("/signals/outcomes", response_model=list[SignalOutcome])
async def list_signal_outcomes(
    limit: int = Query(default=50, ge=1, le=200),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> list[SignalOutcome]:
    return scan_repository.list_signal_outcomes(limit=limit)


@protected_router.get("/signals/outcomes/summary", response_model=SignalOutcomeSummary)
async def get_signal_outcome_summary(
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> SignalOutcomeSummary:
    return scan_repository.get_signal_outcome_summary()


@protected_router.get("/signals/validation/summary", response_model=ValidationSummary)
async def get_signal_validation_summary(
    asset_type: str | None = Query(default=None, pattern="^(stock|crypto)$"),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> ValidationSummary:
    return scan_repository.get_signal_validation_summary(asset_type=asset_type)


@protected_router.get(
    "/signals/validation/threshold-sweep",
    response_model=ThresholdSweepResponse,
)
async def get_validation_threshold_sweep(
    asset_type: str | None = Query(default=None, pattern="^(stock|crypto)$"),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> ThresholdSweepResponse:
    return scan_repository.get_validation_threshold_sweep(asset_type=asset_type)


@protected_router.get(
    "/signals/validation/execution-alignment",
    response_model=ExecutionAlignmentResponse,
)
async def get_execution_alignment_summary(
    asset_type: str | None = Query(default=None, pattern="^(stock|crypto)$"),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> ExecutionAlignmentResponse:
    return scan_repository.get_execution_alignment_summary(asset_type=asset_type)


@protected_router.get("/journal/entries", response_model=list[JournalEntryResponse])
async def list_journal_entries(
    limit: int = Query(default=50, ge=1, le=200),
    journal_repository: JournalRepository = Depends(get_journal_repository),
) -> list[JournalEntryResponse]:
    return journal_repository.list_entries(limit=limit)


@protected_router.get("/journal/analytics", response_model=JournalAnalyticsResponse)
async def get_journal_analytics(
    journal_repository: JournalRepository = Depends(get_journal_repository),
) -> JournalAnalyticsResponse:
    return journal_repository.get_analytics()


@protected_router.get("/metrics", response_model=MetricsResponse)
async def get_metrics() -> MetricsResponse:
    snapshot = metrics.snapshot()
    return MetricsResponse(
        counters=snapshot["counters"],
        durations=snapshot["durations"],
    )
