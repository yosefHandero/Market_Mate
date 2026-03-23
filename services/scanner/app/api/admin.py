from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.auth import require_admin_access
from app.dependencies import (
    get_execution_service,
    get_journal_repository,
    get_risk_service,
    get_scheduler_service,
    get_scanner_service,
)
from app.schemas import (
    JournalEntryCreateRequest,
    JournalEntryResponse,
    JournalEntryUpdateRequest,
    OrderPlaceRequest,
    OrderPlaceResponse,
    OrderPreviewRequest,
    OrderPreviewResponse,
    ScanRun,
    TradeEligibilityResponse,
)
from app.services.execution import ExecutionService
from app.services.journal_repository import JournalRepository
from app.services.risk import RiskService
from app.services.scheduler import SchedulerService
from app.services.scanner import ScannerService

router = APIRouter(dependencies=[Depends(require_admin_access)])


@router.post("/scan/run", response_model=ScanRun)
async def run_scan(
    scanner_service: ScannerService = Depends(get_scanner_service),
) -> ScanRun:
    return await scanner_service.run_scan()


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
