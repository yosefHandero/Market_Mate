from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging

from sqlalchemy import desc, select

from app.clients.alpaca import AlpacaClient
from app.config import get_settings
from app.db import SessionLocal
from app.errors import AppError
from app.models.scan import ExecutionAuditORM
from app.schemas import OrderPlaceRequest, OrderPlaceResponse, OrderPreviewRequest, OrderPreviewResponse
from app.services.readiness import evaluate_operational_readiness
from app.services.repository import ScanRepository
from app.services.risk import RiskService


logger = logging.getLogger(__name__)


class ExecutionService:
    def __init__(self, scan_repository: ScanRepository | None = None) -> None:
        self.settings = get_settings()
        self.alpaca = AlpacaClient()
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

    def _asset_type_for_symbol(self, symbol: str) -> str:
        return "crypto" if "/" in symbol else "stock"

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
                    dry_run=getattr(request, "dry_run", False),
                    idempotency_key=getattr(request, "idempotency_key", None),
                    idempotency_payload_hash=self._idempotency_payload_hash(
                        request.model_dump(mode="json")
                    ),
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
                row.updated_at = now
                row.asset_type = self._asset_type_for_symbol(preview.ticker)
                row.side = preview.side
                row.order_type = preview.order_type
                row.qty = preview.qty
                row.dry_run = getattr(request, "dry_run", False)
                row.idempotency_key = getattr(request, "idempotency_key", None)
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

    def _enforce_execution_safeguards(self) -> None:
        if (
            self.settings.execution_enabled
            and "paper-api" not in self.settings.alpaca_base_url
            and not self.settings.allow_live_trading
        ):
            raise AppError(
                message="Live trading is disabled. Set ALLOW_LIVE_TRADING=true to use a non-paper broker URL.",
                status_code=409,
                code="live_trading_disabled",
            )

    def _enforce_live_rollout_caps(self, *, request: OrderPlaceRequest, preview: OrderPreviewResponse) -> None:
        is_live_route = "paper-api" not in self.settings.alpaca_base_url
        if not is_live_route:
            return
        if request.qty > self.settings.live_trading_max_qty:
            raise AppError(
                message=(
                    f"Live rollout qty {request.qty} exceeds conservative max qty "
                    f"{self.settings.live_trading_max_qty}."
                ),
                status_code=409,
                code="live_rollout_qty_exceeded",
            )
        if preview.notional_estimate > self.settings.live_trading_max_notional:
            raise AppError(
                message=(
                    f"Live rollout notional ${preview.notional_estimate:.2f} exceeds conservative max "
                    f"${self.settings.live_trading_max_notional:.2f}."
                ),
                status_code=409,
                code="live_rollout_notional_exceeded",
            )
        if preview.trade_gate and preview.trade_gate.execution_eligibility != "eligible":
            raise AppError(
                message=(
                    "Live rollout only allows trades with explicit execution eligibility "
                    f"'eligible'; got {preview.trade_gate.execution_eligibility}."
                ),
                status_code=409,
                code="live_rollout_requires_explicit_eligibility",
            )

    def _response_from_existing_audit(self, row: ExecutionAuditORM) -> OrderPlaceResponse:
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

    async def preview(self, request: OrderPreviewRequest) -> OrderPreviewResponse:
        self._enforce_operational_readiness()
        ticker = request.ticker.upper()
        if self._asset_type_for_symbol(ticker) == "crypto":
            latest_price = await self.alpaca.get_latest_crypto_price(ticker)
        else:
            latest_price = await self.alpaca.get_latest_price(ticker)
        price_for_estimate = request.limit_price or latest_price
        warnings: list[str] = []
        if not self.settings.execution_enabled:
            warnings.append("Execution is disabled. Preview only until EXECUTION_ENABLED=true.")
        trade_gate = self.risk.evaluate_trade(
            ticker=ticker,
            side=request.side,
            qty=request.qty,
            latest_price=price_for_estimate,
        )
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
            latest_price=round(latest_price, 4),
            time_in_force=self.settings.execution_default_time_in_force,
            warnings=warnings,
            trade_gate=trade_gate,
            entry_price=round(entry_price, 4),
            stop_price=request.stop_price,
            target_price=request.target_price,
            position_size=request.qty,
            estimated_pnl_usd=estimated_pnl,
            gate_result="allowed" if trade_gate.allowed else "blocked",
            freshness=freshness,
            reject_reasons=reject_reasons,
        )
        preview.execution_audit_id = self._write_audit(
            request=request,
            preview=preview,
            audit_id=request.preview_audit_id,
        )
        return preview

    async def place(self, request: OrderPlaceRequest) -> OrderPlaceResponse:
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
            return self._response_from_existing_audit(existing)

        preview = await self.preview(request)
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
        if request.dry_run or not self.settings.execution_enabled:
            self._update_audit(
                audit_id=preview.execution_audit_id,
                submitted=False,
                lifecycle_status="dry_run",
                broker_status="dry_run",
                broker_payload=preview.model_dump(mode="json"),
            )
            if (
                request.dry_run
                and preview.execution_audit_id is not None
                and preview.trade_gate is not None
                and preview.trade_gate.allowed
                and preview.latest_price > 0
            ):
                try:
                    ledger_id = self._scan_repository.record_paper_position_from_audit(
                        audit_id=preview.execution_audit_id,
                        simulated_fill_price=float(preview.latest_price),
                    )
                except Exception:
                    ledger_id = None
                    logger.exception(
                        "Failed to persist manual dry-run paper position for audit %s.",
                        preview.execution_audit_id,
                    )
            else:
                ledger_id = None
            return OrderPlaceResponse(
                ok=True,
                submitted=False,
                dry_run=True,
                message="Dry run only. Order was not sent to Alpaca.",
                idempotency_key=request.idempotency_key,
                raw=preview.model_dump(),
                trade_gate=preview.trade_gate,
                execution_audit_id=preview.execution_audit_id,
                ledger_id=ledger_id,
                fill_price=preview.latest_price,
                filled_qty=preview.qty,
                slippage_assumption_bps=0.0,
                recommended_action_snapshot=request.recommended_action_snapshot,
            )

        self._enforce_live_rollout_caps(request=request, preview=preview)

        try:
            raw = await self.alpaca.submit_order(
                symbol=request.ticker.upper(),
                side=request.side,
                qty=request.qty,
                order_type=request.order_type,
                limit_price=request.limit_price,
                idempotency_key=request.idempotency_key,
            )
        except Exception as exc:
            self._update_audit(
                audit_id=preview.execution_audit_id,
                submitted=False,
                lifecycle_status="failed",
                broker_status="failed",
                broker_payload={},
                error_message=str(exc),
            )
            raise
        self._update_audit(
            audit_id=preview.execution_audit_id,
            submitted=True,
            lifecycle_status="submitted",
            broker_status=str(raw.get("status") or "submitted"),
            broker_order_id=raw.get("id"),
            broker_payload=raw,
        )
        return OrderPlaceResponse(
            ok=True,
            submitted=True,
            dry_run=False,
            message="Order submitted to Alpaca.",
            idempotency_key=request.idempotency_key,
            order_id=raw.get("id"),
            status=raw.get("status"),
            raw=raw,
            trade_gate=preview.trade_gate,
            execution_audit_id=preview.execution_audit_id,
        )
