from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import math

import httpx
from sqlalchemy import desc, select

from app.clients.alpaca import AlpacaClient, MarketQuoteUnavailable, stock_iex_session_is_open
from app.clients.polygon import PolygonClient
from app.config import get_settings
from app.core.paper_action import paper_action_checks
from app.db import SessionLocal
from app.errors import AppError
from app.models.scan import ExecutionAuditORM, PaperPositionORM, PredictionSnapshotORM
from app.schemas import GateCheck, OrderPlaceRequest, OrderPlaceResponse, OrderPreviewRequest, OrderPreviewResponse, PaperTradeContract
from app.services.readiness import evaluate_operational_readiness
from app.services.repository import ScanRepository
from app.services.risk import RiskService


logger = logging.getLogger(__name__)


class ExecutionService:
    def __init__(self, scan_repository: ScanRepository | None = None) -> None:
        self.settings = get_settings()
        self.alpaca = AlpacaClient()
        self.polygon = PolygonClient()
        self._scan_repository = scan_repository or ScanRepository()
        self.risk = RiskService(scan_repository=self._scan_repository)

    @staticmethod
    def _idempotency_payload_hash(payload: dict) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _enforce_operational_readiness(self) -> None:
        if not self.settings.require_readyz_for_execution:
            return
        ok, reason = evaluate_operational_readiness(
            scan_repository=self._scan_repository,
            settings=self.settings,
        )
        if not ok:
            raise AppError(
                message=reason or "Scanner is not operationally ready.",
                status_code=503,
                code="not_ready",
            )

    def _enforce_kill_switch(self) -> None:
        if not self.settings.paper_loop_kill_switch:
            return
        raise AppError(
            message="Paper-loop kill switch is enabled; order paths are halted.",
            status_code=409,
            code="kill_switch_enabled",
        )

    def _asset_type_for_symbol(self, symbol: str) -> str:
        return "crypto" if "/" in symbol else "stock"

    def _paper_contract(self, *, ticker: str, trade_gate) -> PaperTradeContract:
        # Read the saved production decision, never today's configured policy.
        source_run_id = trade_gate.signal_run_id
        policy_id = policy_version = decision_fingerprint = None
        if source_run_id:
            with SessionLocal() as session:
                snapshot = session.execute(
                    select(PredictionSnapshotORM).where(
                        PredictionSnapshotORM.run_id == source_run_id,
                        PredictionSnapshotORM.ticker == ticker,
                        PredictionSnapshotORM.decision_role == "production",
                    ).order_by(desc(PredictionSnapshotORM.id)).limit(1)
                ).scalar_one_or_none()
                if snapshot is not None:
                    policy_id = snapshot.policy_id
                    policy_version = snapshot.policy_version
                    decision_fingerprint = snapshot.decision_fingerprint
        horizon = trade_gate.horizon
        return PaperTradeContract(
            source_run_id=source_run_id, policy_id=policy_id, policy_version=policy_version,
            decision_fingerprint=decision_fingerprint, holding_horizon=horizon,
            holding_duration_seconds={"15m": 900, "1h": 3600, "1d": 86400, "1w": 604800}[horizon],
        )

    def _validate_preview_agreement(self, request: OrderPreviewRequest, contract: PaperTradeContract) -> None:
        if request.paper_contract is None and request.preview_audit_id is None:
            return
        prior = self._get_audit(request.preview_audit_id)
        saved = json.loads(prior.preview_payload or "{}").get("paper_contract") if prior else None
        supplied = request.paper_contract.model_dump(mode="json") if request.paper_contract else saved
        if supplied != saved or (saved is not None and saved != contract.model_dump(mode="json")):
            raise AppError(
                message="The scan or paper holding contract changed. Create a fresh preview before placing.",
                status_code=409, code="paper_contract_changed",
            )

    def _get_audit(self, audit_id: int | None) -> ExecutionAuditORM | None:
        if audit_id is None:
            return None
        with SessionLocal() as session:
            row = session.get(ExecutionAuditORM, audit_id)
            return row

    def _find_existing_idempotent_result(self, idempotency_key: str | None) -> ExecutionAuditORM | None:
        if not idempotency_key:
            return None
        with SessionLocal() as session:
            return session.execute(
                select(ExecutionAuditORM)
                .where(ExecutionAuditORM.idempotency_key == idempotency_key)
                .order_by(desc(ExecutionAuditORM.updated_at))
                .limit(1)
            ).scalar_one_or_none()

    def _write_audit(
        self,
        *,
        request: OrderPreviewRequest,
        preview: OrderPreviewResponse,
        audit_id: int | None = None,
    ) -> int:
        now = datetime.now(timezone.utc)
        trade_gate = preview.trade_gate
        with SessionLocal() as session:
            row = session.get(ExecutionAuditORM, audit_id) if audit_id is not None else None
            if row is None:
                row = ExecutionAuditORM(
                    created_at=now,
                    updated_at=now,
                    ticker=preview.ticker,
                    asset_type=self._asset_type_for_symbol(preview.ticker),
                    side=preview.side,
                    order_type=preview.order_type,
                    qty=preview.qty,
                    dry_run=True,
                    idempotency_key=getattr(request, "idempotency_key", None),
                    idempotency_payload_hash=self._idempotency_payload_hash(
                        request.model_dump(mode="json")
                    ),
                    recommended_action_snapshot=request.recommended_action_snapshot,
                    lifecycle_status="previewed",
                    latest_price=preview.latest_price,
                    notional_estimate=preview.notional_estimate,
                    signal_outcome_id=trade_gate.signal_outcome_id if trade_gate else None,
                    signal_run_id=trade_gate.signal_run_id if trade_gate else None,
                    signal_generated_at=trade_gate.signal_generated_at if trade_gate else None,
                    latest_signal=trade_gate.latest_signal if trade_gate else None,
                    confidence=trade_gate.confidence if trade_gate else None,
                    trade_gate_horizon=trade_gate.horizon if trade_gate else None,
                    evidence_basis=getattr(trade_gate, "evidence_basis", None) if trade_gate else None,
                    trust_window_start=getattr(trade_gate, "trust_window_start", None) if trade_gate else None,
                    trust_window_end=getattr(trade_gate, "trust_window_end", None) if trade_gate else None,
                    trade_gate_allowed=trade_gate.allowed if trade_gate else None,
                    trade_gate_reason=trade_gate.reason if trade_gate else None,
                    submitted=False,
                    preview_payload=json.dumps(preview.model_dump(mode="json")),
                    request_payload=json.dumps(request.model_dump(mode="json")),
                )
                session.add(row)
            else:
                if row.lifecycle_status in {"submitted", "dry_run", "blocked"}:
                    raise AppError(
                        message="This preview already has a completed placement; reuse its original idempotency key.",
                        status_code=409,
                        code="preview_already_used",
                    )
                row.updated_at = now
                row.asset_type = self._asset_type_for_symbol(preview.ticker)
                row.side = preview.side
                row.order_type = preview.order_type
                row.qty = preview.qty
                row.dry_run = True
                row.idempotency_key = getattr(request, "idempotency_key", None)
                row.idempotency_payload_hash = self._idempotency_payload_hash(
                    request.model_dump(mode="json")
                )
                row.recommended_action_snapshot = request.recommended_action_snapshot
                row.lifecycle_status = "previewed"
                row.latest_price = preview.latest_price
                row.notional_estimate = preview.notional_estimate
                row.signal_outcome_id = trade_gate.signal_outcome_id if trade_gate else None
                row.signal_run_id = trade_gate.signal_run_id if trade_gate else None
                row.signal_generated_at = trade_gate.signal_generated_at if trade_gate else None
                row.latest_signal = trade_gate.latest_signal if trade_gate else None
                row.confidence = trade_gate.confidence if trade_gate else None
                row.trade_gate_horizon = trade_gate.horizon if trade_gate else None
                row.evidence_basis = getattr(trade_gate, "evidence_basis", None) if trade_gate else None
                row.trust_window_start = getattr(trade_gate, "trust_window_start", None) if trade_gate else None
                row.trust_window_end = getattr(trade_gate, "trust_window_end", None) if trade_gate else None
                row.trade_gate_allowed = trade_gate.allowed if trade_gate else None
                row.trade_gate_reason = trade_gate.reason if trade_gate else None
                row.preview_payload = json.dumps(preview.model_dump(mode="json"))
                row.request_payload = json.dumps(request.model_dump(mode="json"))
                row.error_message = None
            session.commit()
            session.refresh(row)
            return row.id

    def _update_audit(
        self,
        *,
        audit_id: int | None,
        submitted: bool,
        lifecycle_status: str,
        broker_status: str,
        broker_order_id: str | None = None,
        broker_payload: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        if audit_id is None:
            return
        with SessionLocal() as session:
            row = session.get(ExecutionAuditORM, audit_id)
            if row is None:
                return
            row.updated_at = datetime.now(timezone.utc)
            row.submitted = submitted
            row.lifecycle_status = lifecycle_status
            row.broker_status = broker_status
            row.broker_order_id = broker_order_id
            row.broker_payload = json.dumps(broker_payload or {})
            row.error_message = error_message
            session.commit()

    def _stamp_placement_identity(self, audit_id: int | None, request: OrderPlaceRequest) -> None:
        """Persist the placement request, not the earlier preview body.

        Preview and placement share an audit row. The idempotency hash has to
        describe the operation that was actually completed, or an identical
        placement retry is rejected as a different payload.
        """
        if audit_id is None:
            return
        payload = request.model_dump(mode="json")
        with SessionLocal() as session:
            row = session.get(ExecutionAuditORM, audit_id)
            if row is None:
                return
            row.updated_at = datetime.now(timezone.utc)
            row.idempotency_key = request.idempotency_key
            row.request_payload = json.dumps(payload)
            row.idempotency_payload_hash = self._idempotency_payload_hash(payload)
            session.commit()

    def _enforce_execution_safeguards(self) -> None:
        if self.settings.execution_enabled or self.settings.allow_live_trading:
            raise AppError(
                message=(
                    "Paper-only build forbids EXECUTION_ENABLED=true or ALLOW_LIVE_TRADING=true; "
                    "broker order submission cannot be enabled."
                ),
                status_code=409,
                code="paper_only_execution_forbidden",
            )

    def _enforce_paper_only_request(self, request: OrderPreviewRequest, *, placement: bool) -> None:
        if request.mode not in (None, "dry_run"):
            raise AppError(
                message='Only dry-run paper orders are accepted; mode must be omitted or "dry_run".',
                status_code=400,
                code="dry_run_required",
            )
        if placement and getattr(request, "dry_run", True) is not True:
            raise AppError(
                message="Only dry-run paper orders are accepted; dry_run=false is forbidden.",
                status_code=400,
                code="dry_run_required",
            )

    def _response_from_existing_audit(self, row: ExecutionAuditORM, *, ledger_id: int | None = None) -> OrderPlaceResponse:
        raw_payload = {}
        if row.broker_payload:
            try:
                raw_payload = json.loads(row.broker_payload)
            except json.JSONDecodeError:
                raw_payload = {}
        preview_payload = {}
        if row.preview_payload:
            try:
                preview_payload = json.loads(row.preview_payload)
            except json.JSONDecodeError:
                preview_payload = {}
        with SessionLocal() as session:
            saved_ledger_id = ledger_id or raw_payload.get("ledger_id")
            position = session.get(PaperPositionORM, saved_ledger_id) if saved_ledger_id else session.execute(
                select(PaperPositionORM)
                .where(PaperPositionORM.execution_audit_id == row.id)
                .limit(1)
            ).scalar_one_or_none()
        return OrderPlaceResponse(
            ok=row.lifecycle_status in {"submitted", "dry_run"},
            submitted=row.submitted,
            dry_run=bool(row.dry_run),
            message=row.error_message or f"Reused prior {row.lifecycle_status} result for idempotency key.",
            idempotency_key=row.idempotency_key,
            order_id=row.broker_order_id,
            status=row.broker_status,
            raw=raw_payload or preview_payload,
            execution_audit_id=row.id,
            trade_gate=preview_payload.get("trade_gate"),
            ledger_id=position.id if position is not None else None,
            fill_price=(raw_payload.get("fill_price") or row.latest_price) if row.side == "sell" and position else position.simulated_fill_price if position else None,
            filled_qty=row.qty if row.side == "sell" and position else position.quantity if position else None,
            slippage_assumption_bps=0.0 if position is not None else None,
            recommended_action_snapshot=row.recommended_action_snapshot,
            paper_contract=preview_payload.get("paper_contract"),
            filled_at=position.closed_at if row.side == "sell" and position else position.opened_at if position else None,
            exit_due_at=position.exit_due_at if position is not None else None,
        )

    @staticmethod
    def _estimate_pnl(
        *,
        side: str,
        qty: float,
        entry_price: float | None,
        target_price: float | None,
    ) -> float | None:
        if entry_price is None or target_price is None or qty <= 0:
            return None
        direction = -1 if side == "sell" else 1
        return round((target_price - entry_price) * qty * direction, 2)

    async def get_paper_quote(self, ticker: str) -> float:
        is_crypto = self._asset_type_for_symbol(ticker) == "crypto"
        fetch_price = self.alpaca.get_latest_crypto_price if is_crypto else self.alpaca.get_latest_price
        try:
            latest_price = await fetch_price(ticker)
        except (RuntimeError, httpx.HTTPError, TimeoutError) as exc:
            if (
                not is_crypto and self.settings.polygon_intraday_fallback_enabled and self.settings.polygon_api_key
                and (not isinstance(exc, MarketQuoteUnavailable) or stock_iex_session_is_open(datetime.now(timezone.utc)))
            ):
                try:
                    bars = await self.polygon.get_latest_bars(
                        [ticker], timeframe="1Min", bar_builder=self.alpaca._build_bars_by_symbol,
                    )
                    quote = self.alpaca.fresh_bar_quote(bars.get(ticker), datetime.now(timezone.utc))
                    if quote is not None:
                        return quote[0]
                except (RuntimeError, httpx.HTTPError, TimeoutError):
                    pass
            if isinstance(exc, MarketQuoteUnavailable):
                message = str(exc)
            elif isinstance(exc, (httpx.TimeoutException, TimeoutError)):
                message = "The market data request for a paper quote timed out."
            elif status := getattr(exc, "status_code", None):
                message = f"The market data provider returned HTTP {status} for the paper quote."
            else:
                message = "The market data provider could not retrieve a paper quote."
            raise AppError(message=message, status_code=503, code="paper_quote_unavailable") from exc
        if not math.isfinite(latest_price) or latest_price <= 0:
            raise AppError(message="No valid quote is available for a paper fill.", status_code=503, code="paper_quote_unavailable")
        return latest_price

    async def preview(self, request: OrderPreviewRequest) -> OrderPreviewResponse:
        self._enforce_paper_only_request(request, placement=False)
        self._enforce_execution_safeguards()
        self._enforce_operational_readiness()
        self._enforce_kill_switch()
        ticker = request.ticker.upper()
        latest_price = await self.get_paper_quote(ticker)
        price_for_estimate = latest_price
        if request.requested_notional_usd is not None:
            qty = self.risk.suggest_paper_quantity(
                requested_notional_usd=request.requested_notional_usd, latest_price=price_for_estimate,
            )
            if qty <= 0:
                raise AppError(message="The requested budget cannot produce a positive quantity within paper limits.", status_code=400, code="unable_to_size")
            request = request.model_copy(update={"qty": qty, "requested_notional_usd": None})
        warnings: list[str] = []
        warnings.append("Paper-only build: broker submission is permanently disabled.")
        warnings.append("Time-based closure starts at the simulated fill; stop, target and forecast ranges are advisory only. No protective orders are active.")
        trade_gate = self.risk.evaluate_trade(
            ticker=ticker,
            side=request.side,
            qty=request.qty,
            latest_price=price_for_estimate,
        )
        contract = self._paper_contract(ticker=ticker, trade_gate=trade_gate)
        self._validate_preview_agreement(request, contract)
        additional_reject_reason = None
        if request.side == "buy":
            latest_run = self._scan_repository.get_latest_run()
            result = next((row for row in latest_run.results if row.ticker == ticker), None) if latest_run else None
            if result is not None:
                action_checks = paper_action_checks(result)
            else:
                missing_detail = next((
                    missing.detail
                    for asset_coverage in (getattr(latest_run, "coverage", None) or [])
                    for missing in asset_coverage.missing_symbols
                    if missing.ticker == ticker and missing.reason != "benchmark_only"
                ), "No current scan row is available.")
                action_checks = [GateCheck(name="paper_latest_result", passed=False, detail=missing_detail)]
            trade_gate.gate_checks.extend(action_checks)
            failed_actions = [check for check in action_checks if not check.passed]
            if failed_actions:
                action_reason = "Paper action blocked: " + "; ".join(check.detail for check in failed_actions) + "."
                if trade_gate.allowed:
                    trade_gate.reason = action_reason
                else:
                    additional_reject_reason = action_reason
                trade_gate.allowed = False
                trade_gate.execution_eligibility = "blocked"
        if not trade_gate.allowed:
            warnings.append(trade_gate.reason)
        elif trade_gate.execution_eligibility == "review":
            warnings.append("Execution requires manual review because evidence or provider quality is not fully clean.")
        entry_price = request.entry_price or price_for_estimate
        estimated_pnl = self._estimate_pnl(
            side=request.side,
            qty=request.qty,
            entry_price=entry_price,
            target_price=request.target_price,
        )
        reject_reasons = [trade_gate.reason] if not trade_gate.allowed else []
        if additional_reject_reason:
            reject_reasons.append(additional_reject_reason)
        freshness = (
            "fresh"
            if getattr(trade_gate, "latest_scan_fresh", None) is True
            else "stale"
            if getattr(trade_gate, "latest_scan_fresh", None) is False
            else "unknown"
        )
        preview = OrderPreviewResponse(
            ticker=ticker,
            side=request.side,
            qty=request.qty,
            order_type=request.order_type,
            notional_estimate=round(price_for_estimate * request.qty, 2),
            latest_price=latest_price,
            time_in_force=self.settings.execution_default_time_in_force,
            warnings=warnings,
            trade_gate=trade_gate,
            entry_price=entry_price,
            stop_price=request.stop_price,
            target_price=request.target_price,
            position_size=request.qty,
            estimated_pnl_usd=estimated_pnl,
            gate_result="allowed" if trade_gate.allowed else "blocked",
            freshness=freshness,
            reject_reasons=reject_reasons,
            paper_contract=contract,
        )
        preview.execution_audit_id = self._write_audit(
            request=request,
            preview=preview,
            audit_id=request.preview_audit_id,
        )
        return preview

    async def place(self, request: OrderPlaceRequest) -> OrderPlaceResponse:
        self._enforce_paper_only_request(request, placement=True)
        self._enforce_kill_switch()
        self._enforce_execution_safeguards()
        existing = self._find_existing_idempotent_result(request.idempotency_key)
        if existing and existing.lifecycle_status in {"submitted", "dry_run", "blocked"}:
            want_hash = self._idempotency_payload_hash(request.model_dump(mode="json"))
            prior_hash = existing.idempotency_payload_hash
            if prior_hash is None and existing.request_payload:
                try:
                    prior_hash = self._idempotency_payload_hash(json.loads(existing.request_payload))
                except (json.JSONDecodeError, TypeError):
                    prior_hash = None
            if prior_hash is not None and want_hash != prior_hash:
                raise AppError(
                    message="Idempotency key already used with a different request body.",
                    status_code=409,
                    code="idempotency_payload_mismatch",
                )
            self._enforce_operational_readiness()
            return self._response_from_existing_audit(existing)
        if existing and existing.lifecycle_status == "previewed":
            if request.preview_audit_id is not None and request.preview_audit_id != existing.id:
                raise AppError(
                    message="Idempotency key is already bound to a different preview.",
                    status_code=409,
                    code="idempotency_preview_mismatch",
                )
            if request.preview_audit_id is None:
                request = request.model_copy(update={"preview_audit_id": existing.id})

        preview = await self.preview(request)
        self._stamp_placement_identity(preview.execution_audit_id, request)
        if preview.trade_gate and not preview.trade_gate.allowed:
            self._update_audit(
                audit_id=preview.execution_audit_id,
                submitted=False,
                lifecycle_status="blocked",
                broker_status="blocked",
                broker_payload=preview.model_dump(mode="json"),
                error_message=f"Order blocked by trade gate: {preview.trade_gate.reason}",
            )
            return OrderPlaceResponse(
                ok=False,
                submitted=False,
                dry_run=request.dry_run,
                message=f"Order blocked by trade gate: {preview.trade_gate.reason}",
                idempotency_key=request.idempotency_key,
                raw=preview.model_dump(),
                trade_gate=preview.trade_gate,
                execution_audit_id=preview.execution_audit_id,
                recommended_action_snapshot=request.recommended_action_snapshot,
            )
        filled_at = datetime.now(timezone.utc)
        if (
            preview.execution_audit_id is not None
            and preview.trade_gate is not None
            and preview.trade_gate.allowed
            and preview.latest_price > 0
        ):
            try:
                ledger_id = self._scan_repository.record_paper_position_from_audit(
                    audit_id=preview.execution_audit_id,
                    simulated_fill_price=float(preview.latest_price),
                    filled_at=filled_at,
                )
            except Exception as exc:
                logger.exception(
                    "Failed to persist manual dry-run paper position for audit %s.",
                    preview.execution_audit_id,
                )
                raise AppError(message="Paper fill could not be saved. No completed position is confirmed; retry this placement.", status_code=503, code="paper_position_persistence_failed") from exc
        else:
            ledger_id = None
        if ledger_id is None:
            self._update_audit(
                audit_id=preview.execution_audit_id, submitted=False, lifecycle_status="failed",
                broker_status="failed", error_message="No paper position was recorded.",
            )
            raise AppError(message="No paper position was recorded.", status_code=503, code="paper_position_persistence_failed")
        saved_audit = self._get_audit(preview.execution_audit_id)
        response = self._response_from_existing_audit(saved_audit, ledger_id=ledger_id)
        response = response.model_copy(update={
            "ok": True, "message": "Dry-run paper order recorded. No broker order request was made.",
            "raw": preview.model_dump(mode="json"), "trade_gate": preview.trade_gate,
            "paper_contract": preview.paper_contract, "status": "dry_run",
        })
        # Retain the actual fill receipt for safe reconciliation; a later repair
        # must not use its own wall clock as the original fill time.
        self._update_audit(
            audit_id=preview.execution_audit_id, submitted=False, lifecycle_status="dry_run",
            broker_status="dry_run", broker_payload={**preview.model_dump(mode="json"), **response.model_dump(mode="json", exclude={"raw"})},
        )
        return response
