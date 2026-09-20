from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.auth import require_admin_access
from app.dependencies import (
    get_execution_service,
    get_promotion_service,
    get_replay_service,
    get_risk_service,
    get_scan_repository,
    get_scheduler_service,
    get_scanner_service,
    get_walk_forward_proof_service,
)
from app.errors import AppError
from app.schemas import (
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
    WalkForwardProofRequest,
    WalkForwardProofRunResponse,
    WalkForwardRunSummary,
)
from app.services.execution import ExecutionService
from app.services.promotion import PromotionService
from app.services.replay import ReplayService
from app.services.repository import ScanRepository
from app.services.risk import RiskService
from app.services.scheduler import SchedulerService
from app.services.scanner import ScannerService
from app.services.walk_forward_proof import WalkForwardProofService

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
    persist: bool = Query(default=True),
) -> ReplayResponse:
    if persist:
        return await replay_service.replay_and_persist(request)
    return await replay_service.replay(request)


@router.post("/proof/walkforward/run", response_model=WalkForwardProofRunResponse)
async def run_walkforward_proof(
    request: WalkForwardProofRequest,
    proof_service: WalkForwardProofService = Depends(get_walk_forward_proof_service),
    persist: bool = Query(default=True),
) -> WalkForwardProofRunResponse:
    run_id, summary = await proof_service.run(
        symbols=request.symbols,
        years=request.years,
        step_days=request.step_days,
        top_n_per_asset=request.top_n_per_asset,
        force_refresh=request.force_refresh,
        persist=persist,
    )
    return WalkForwardProofRunResponse(
        run_id=run_id,
        summary=WalkForwardRunSummary.model_validate(summary),
    )


@router.post("/scan/scheduler/start")
async def start_scheduler(
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
) -> dict[str, bool]:
    return {"started": scheduler_service.start()}


@router.post("/scan/scheduler/stop")
async def stop_scheduler(
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
) -> dict[str, bool]:
    scheduler_service.stop()
    return {"stopped": True}


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


@router.post("/paper/reconcile/repair", response_model=ReconciliationReportResponse)
async def repair_paper_reconciliation(
    scan_repository: ScanRepository = Depends(get_scan_repository),
) -> ReconciliationReportResponse:
    return scan_repository.repair_paper_reconcile_safe()


@router.post("/signals/outcomes/backfill")
async def backfill_signal_outcomes(
    scanner_service: ScannerService = Depends(get_scanner_service),
) -> dict[str, int | str]:
    refreshed = await scanner_service.refresh_due_signal_outcomes()
    closed = await scanner_service.close_open_positions_past_horizon()
    predictions = await scanner_service.refresh_due_prediction_snapshots()
    return {
        "refreshed_outcomes": refreshed,
        "refreshed_predictions": predictions,
        "closed_positions": closed,
        "status": "ok",
    }


async def _run_db_integrity_check() -> dict[str, object]:
    from app.db import SessionLocal, engine
    from app.services.db_integrity import run_db_integrity_check

    with SessionLocal() as session:
        report = run_db_integrity_check(session, engine=engine)
    return report.as_dict()


@router.get("/system/db/check")
async def check_database_integrity_get() -> dict[str, object]:
    """PRAGMA quick_check + immutable-record hash verification for the local DB."""
    return await _run_db_integrity_check()


@router.post("/system/db/check")
async def check_database_integrity_post() -> dict[str, object]:
    """Same integrity check as GET; POST is the canonical ops entrypoint."""
    return await _run_db_integrity_check()


def _campaigns_payload() -> dict[str, object]:
    from app.services.evidence_campaign import EvidenceCampaignService

    service = EvidenceCampaignService()
    active = service.get_active_campaign()
    return {
        "active": active.as_dict() if active else None,
        "campaigns": [campaign.as_dict() for campaign in service.list_campaigns()],
    }


@router.get("/evidence/campaigns")
async def list_evidence_campaigns() -> dict[str, object]:
    return _campaigns_payload()


@router.get("/proof/campaigns")
async def list_proof_campaigns() -> dict[str, object]:
    """Canonical path for evidence campaigns (alias of /evidence/campaigns)."""
    return _campaigns_payload()


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
    if request.mode not in (None, "dry_run") or request.dry_run is not True:
        raise AppError(
            message="Only dry-run paper orders are accepted by this endpoint.",
            status_code=400,
            code="dry_run_required",
        )
    if request.idempotency_key is None and x_idempotency_key:
        request.idempotency_key = x_idempotency_key
    return await execution_service.place(request)
