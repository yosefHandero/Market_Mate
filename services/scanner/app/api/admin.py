from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.auth import require_admin_access
from app.dependencies import (
    get_execution_service,
    get_journal_repository,
    get_promotion_service,
    get_replay_service,
    get_risk_service,
    get_scan_repository,
    get_scheduler_service,
    get_scanner_service,
)
from app.errors import AppError
from app.schemas import (
    JournalEntryCreateRequest,
    JournalEntryResponse,
    JournalEntryUpdateRequest,
    OrderPlaceRequest,
    OrderPlaceResponse,
    OrderPreviewRequest,
    OrderPreviewResponse,
    PromotionReadinessResponse,
    ReconciliationReportResponse,
    ReplayRequest,
    ReplayResponse,
    ScanRun,
    SignalOutcomePerformanceReportResponse,
    TradeEligibilityResponse,
)
from app.services.execution import ExecutionService
from app.services.journal_repository import JournalRepository
from app.services.promotion import PromotionService
from app.services.replay import ReplayService
from app.services.repository import ScanRepository
from app.services.risk import RiskService
from app.services.scheduler import SchedulerService
from app.services.scanner import ScannerService

router = APIRouter(dependencies=[Depends(require_admin_access)])


@router.post("/scan/run", response_model=ScanRun)
async def run_scan(
    scanner_service: ScannerService = Depends(get_scanner_service),
) -> ScanRun:
    return await scanner_service.run_scan()


@router.post("/strategy/replay", response_model=ReplayResponse)
async def replay_strategy(
    request: ReplayRequest,
    replay_service: ReplayService = Depends(get_replay_service),
) -> ReplayResponse:
    return await replay_service.replay(request)


@router.post("/scan/scheduler/start")
async def start_scheduler(
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
) -> dict[str, bool]:
    return {"started": scheduler_service.start()}


@router.post("/scan/scheduler/stop")
async def stop_scheduler(
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
) -> dict[str, bool]:
    return {"stopped": scheduler_service.stop()}


@router.get(
    "/signals/outcomes/performance-report",
    response_model=SignalOutcomePerformanceReportResponse,
)
async def get_signal_outcome_performance_report(
    start: datetime = Query(),
    end: datetime = Query(),
    asset_type: str | None = Query(default=None, pattern="^(stock|crypto)$"),
    regime: str | None = Query(default=None, pattern="^(bullish|neutral|bearish)$"),
    friction_scenario: str = Query(default="base", pattern="^(base|stressed|worst)$"),
    strict_walkforward: bool = Query(default=False),
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> SignalOutcomePerformanceReportResponse:
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be greater than start")
    return scan_repository.get_signal_outcome_performance_report(
        start=start,
        end=end,
        asset_type=asset_type,
        regime=regime,
        friction_scenario=friction_scenario,
        strict_walkforward=strict_walkforward,
    )


@router.get("/paper/promotion-check", response_model=PromotionReadinessResponse)
async def get_promotion_check(
    current_phase: str = Query(default="disabled", pattern="^(disabled|shadow|limited|broad)$"),
    promotion_service: PromotionService = Depends(get_promotion_service),
) -> PromotionReadinessResponse:
    return promotion_service.evaluate_promotion_readiness(current_phase=current_phase)


@router.get("/paper/reconcile", response_model=ReconciliationReportResponse)
async def get_paper_reconciliation(
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> ReconciliationReportResponse:
    return scan_repository.reconcile_paper_loop()


@router.get("/risk/trade-eligibility", response_model=TradeEligibilityResponse)
async def get_trade_eligibility(
    ticker: str = Query(min_length=1),
    side: str = Query(pattern="^(buy|sell)$"),
    qty: float = Query(default=1, gt=0),
    execution_service: ExecutionService = Depends(get_execution_service),
    risk_service: RiskService = Depends(get_risk_service),
) -> TradeEligibilityResponse:
    symbol = ticker.upper()
    try:
        if "/" in symbol:
            latest_price = await execution_service.alpaca.get_latest_crypto_price(symbol)
        else:
            latest_price = await execution_service.alpaca.get_latest_price(symbol)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Unable to fetch latest price for {symbol}: {exc}",
        ) from exc
    eligibility = risk_service.evaluate_trade(
        ticker=symbol,
        side=side,
        qty=qty,
        latest_price=latest_price,
    )
    return TradeEligibilityResponse(eligibility=eligibility)


@router.post("/orders/preview", response_model=OrderPreviewResponse)
async def preview_order(
    request: OrderPreviewRequest,
    execution_service: ExecutionService = Depends(get_execution_service),
) -> OrderPreviewResponse:
    return await execution_service.preview(request)


@router.post("/orders/place", response_model=OrderPlaceResponse)
async def place_order(
    request: OrderPlaceRequest,
    x_idempotency_key: str | None = Header(default=None),
    execution_service: ExecutionService = Depends(get_execution_service),
) -> OrderPlaceResponse:
    if request.mode != "dry_run" and not request.dry_run:
        raise AppError(
            message="Only dry-run paper orders are accepted by this endpoint.",
            status_code=400,
            code="dry_run_required",
        )
    request.dry_run = True
    if request.idempotency_key is None and x_idempotency_key:
        request.idempotency_key = x_idempotency_key
    return await execution_service.place(request)


@router.post("/journal/entries", response_model=JournalEntryResponse)
async def create_journal_entry(
    request: JournalEntryCreateRequest,
    journal_repository: JournalRepository = Depends(get_journal_repository),
) -> JournalEntryResponse:
    return journal_repository.create_entry(request)


@router.patch("/journal/entries/{entry_id}", response_model=JournalEntryResponse)
async def update_journal_entry(
    entry_id: int,
    request: JournalEntryUpdateRequest,
    journal_repository: JournalRepository = Depends(get_journal_repository),
) -> JournalEntryResponse:
    updated = journal_repository.update_entry(entry_id, request)
    if not updated:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return updated
