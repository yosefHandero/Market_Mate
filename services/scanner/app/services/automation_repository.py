from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import and_, desc, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models.scan import AutomationIntentORM, ExecutionAuditORM, PaperLoopBreakerORM, PaperPositionORM
from app.observability import metrics
from app.schemas import (
    AutomationBreakerSnapshot,
    AutomationBudgetSnapshot,
    AutomationIncidentClass,
    AutomationIntentSummary,
    AutomationStatusResponse,
)


_BREAKER_KEY = "default"


class AutomationRepository:
    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _as_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _ensure_breaker_row(self, session, *, now: datetime) -> PaperLoopBreakerORM:
        row = session.get(PaperLoopBreakerORM, _BREAKER_KEY)
        if row is None:
            row = PaperLoopBreakerORM(
                breaker_key=_BREAKER_KEY,
                phase="closed",
                updated_at=now,
            )
            session.add(row)
            session.flush()
        return row

    def create_intent(
        self,
        *,
        run_id: str,
        symbol: str,
        asset_type: str,
        side: str,
        qty: float,
        strategy_version: str | None,
        confidence: float | None,
        horizon: str | None,
        window_start: datetime | None,
        window_end: datetime | None,
        intent_key: str,
        intent_hash: str,
        status: str,
        status_reason: str | None,
        idempotency_key: str | None,
        incident_class: AutomationIncidentClass | None = None,
        decision_payload: dict | None,
        request_payload: dict | None,
        request_count_used: int = 0,
        request_count_avoided: int = 0,
        next_retry_at: datetime | None = None,
        cooldown_until: datetime | None = None,
    ) -> tuple[AutomationIntentORM, bool]:
        now = self._utc_now()
        with SessionLocal() as session:
            row = AutomationIntentORM(
                created_at=now,
                updated_at=now,
                run_id=run_id,
                symbol=symbol.upper(),
                asset_type=asset_type,
                side=side,
                qty=qty,
                strategy_version=strategy_version,
                confidence=confidence,
                horizon=horizon,
                window_start=window_start,
                window_end=window_end,
                intent_key=intent_key,
                intent_hash=intent_hash,
                status=status,
                status_reason=status_reason,
                idempotency_key=idempotency_key,
                incident_class=incident_class,
                decision_payload_json=json.dumps(decision_payload or {}),
                request_payload_json=json.dumps(request_payload or {}),
                request_count_used=request_count_used,
                request_count_avoided=request_count_avoided,
                next_retry_at=next_retry_at,
                cooldown_until=cooldown_until,
            )
            session.add(row)
            try:
                session.commit()
                session.refresh(row)
                return row, True
            except IntegrityError:
                session.rollback()
                existing = session.execute(
                    select(AutomationIntentORM)
                    .where(AutomationIntentORM.intent_key == intent_key)
                    .limit(1)
                ).scalar_one()
                return existing, False

    def get_intent(self, intent_id: int) -> AutomationIntentORM | None:
        with SessionLocal() as session:
            return session.get(AutomationIntentORM, intent_id)

    def claim_intent(
        self,
        *,
        intent_id: int,
        claimed_by: str,
        claim_expires_at: datetime,
        max_place_attempts: int,
    ) -> bool:
        now = self._utc_now()
        stale_claim = or_(
            AutomationIntentORM.claim_expires_at.is_(None),
            AutomationIntentORM.claim_expires_at <= now,
        )
        stmt = (
            update(AutomationIntentORM)
            .where(
                AutomationIntentORM.id == intent_id,
                AutomationIntentORM.attempt_count < max_place_attempts,
                or_(
                    AutomationIntentORM.status == "pending",
                    AutomationIntentORM.status.in_(
                        ("failed_retryable", "blocked_by_budget", "circuit_open")
                    ),
                    and_(
                        AutomationIntentORM.status.in_(("claimed", "placing")),
                        stale_claim,
                    ),
                ),
                or_(
                    AutomationIntentORM.next_retry_at.is_(None),
                    AutomationIntentORM.next_retry_at <= now,
                ),
            )
            .values(
                claimed_by=claimed_by,
                claim_expires_at=claim_expires_at,
                status="claimed",
                updated_at=now,
            )
        )
        with SessionLocal() as session:
            result = session.execute(stmt)
            session.commit()
            return result.rowcount == 1

    def mark_placing(self, intent_id: int) -> None:
        with SessionLocal() as session:
            row = session.get(AutomationIntentORM, intent_id)
            if row is None:
                return
            row.status = "placing"
            row.updated_at = self._utc_now()
            session.commit()

    def update_intent(
        self,
        *,
        intent_id: int,
        status: str,
        status_reason: str | None = None,
        execution_audit_id: int | None = None,
        incident_class: AutomationIncidentClass | None = None,
        request_count_used_increment: int = 0,
        request_count_avoided_increment: int = 0,
        attempt_increment: int = 0,
        last_attempt_at: datetime | None = None,
        next_retry_at: datetime | None = None,
        cooldown_until: datetime | None = None,
        request_payload: dict | None = None,
    ) -> None:
        with SessionLocal() as session:
            row = session.get(AutomationIntentORM, intent_id)
            if row is None:
                return
            row.updated_at = self._utc_now()
            row.status = status
            row.status_reason = status_reason
            if execution_audit_id is not None:
                row.execution_audit_id = execution_audit_id
            if incident_class is not None:
                row.incident_class = incident_class
            row.request_count_used = int(row.request_count_used or 0) + request_count_used_increment
            row.request_count_avoided = int(row.request_count_avoided or 0) + request_count_avoided_increment
            row.attempt_count = int(row.attempt_count or 0) + attempt_increment
            row.last_attempt_at = last_attempt_at or row.last_attempt_at
            row.next_retry_at = next_retry_at
            row.cooldown_until = cooldown_until
            if request_payload is not None:
                row.request_payload_json = json.dumps(request_payload)
            row.claimed_by = None
            row.claim_expires_at = None
            session.commit()

    def record_paper_position(
        self,
        *,
        intent_id: int,
        simulated_fill_price: float,
        filled_at: datetime | None = None,
    ) -> int | None:
        filled_time = filled_at or self._utc_now()
        with SessionLocal() as session:
            intent = session.get(AutomationIntentORM, intent_id)
            if intent is None:
                return None
            existing = session.execute(
                select(PaperPositionORM)
                .where(PaperPositionORM.intent_key == intent.intent_key)
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                return existing.id

            if intent.side == "sell":
                open_position = session.execute(
                    select(PaperPositionORM)
                    .where(
                        PaperPositionORM.ticker == intent.symbol,
                        PaperPositionORM.status == "open",
                        PaperPositionORM.side == "buy",
                    )
                    .order_by(desc(PaperPositionORM.opened_at), desc(PaperPositionORM.id))
                    .limit(1)
                ).scalar_one_or_none()
                if open_position is None:
                    return None
                quantity = float(open_position.quantity or 0.0)
                if quantity <= 0:
                    return None
                open_basis = float(open_position.cost_basis_usd or open_position.notional_usd or 0.0)
                proceeds = round(quantity * simulated_fill_price, 2)
                realized_pnl = round(proceeds - open_basis, 2)
                open_position.close_price = simulated_fill_price
                open_position.realized_pnl = realized_pnl
                open_position.closed_at = filled_time
                open_position.status = "closed"
                open_position.updated_at = filled_time
                session.commit()
                return open_position.id

            position = PaperPositionORM(
                created_at=filled_time,
                updated_at=filled_time,
                intent_key=intent.intent_key,
                execution_audit_id=intent.execution_audit_id,
                ticker=intent.symbol,
                asset_type=intent.asset_type,
                side=intent.side,
                quantity=float(intent.qty or 0.0),
                simulated_fill_price=simulated_fill_price,
                notional_usd=round(float(intent.qty or 0.0) * simulated_fill_price, 2),
                cost_basis_usd=round(float(intent.qty or 0.0) * simulated_fill_price, 2),
                close_price=None,
                realized_pnl=None,
                status="open",
                opened_at=filled_time,
                closed_at=None,
                strategy_version=intent.strategy_version,
                confidence=intent.confidence,
            )
            session.add(position)
            session.commit()
            session.refresh(position)
            return position.id

    def record_paper_position_from_audit(
        self,
        *,
        audit_id: int,
        simulated_fill_price: float,
        filled_at: datetime | None = None,
    ) -> int | None:
        if simulated_fill_price <= 0:
            return None
        filled_time = filled_at or self._utc_now()
        with SessionLocal() as session:
            audit = session.get(ExecutionAuditORM, audit_id)
            if audit is None or not audit.dry_run:
                return None

            intent_key = (audit.idempotency_key or "").strip() or f"manual-audit-{audit.id}"

            existing = session.execute(
                select(PaperPositionORM)
                .where(PaperPositionORM.intent_key == intent_key)
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                return existing.id

            side = audit.side
            qty = float(audit.qty or 0.0)
            if qty <= 0:
                return None

            if side == "sell":
                open_position = session.execute(
                    select(PaperPositionORM)
                    .where(
                        PaperPositionORM.ticker == audit.ticker,
                        PaperPositionORM.status == "open",
                        PaperPositionORM.side == "buy",
                    )
                    .order_by(desc(PaperPositionORM.opened_at), desc(PaperPositionORM.id))
                    .limit(1)
                ).scalar_one_or_none()
                if open_position is None:
                    return None
                open_quantity = float(open_position.quantity or 0.0)
                if open_quantity <= 0:
                    return None
                open_basis = float(open_position.cost_basis_usd or open_position.notional_usd or 0.0)
                proceeds = round(open_quantity * simulated_fill_price, 2)
                realized_pnl = round(proceeds - open_basis, 2)
                open_position.close_price = simulated_fill_price
                open_position.realized_pnl = realized_pnl
                open_position.closed_at = filled_time
                open_position.status = "closed"
                open_position.updated_at = filled_time
                session.commit()
                return open_position.id

            strategy_version = getattr(audit, "trade_gate_horizon", None)
            if audit.preview_payload:
                try:
                    preview_payload = json.loads(audit.preview_payload)
                except json.JSONDecodeError:
                    preview_payload = {}
                trade_gate = preview_payload.get("trade_gate") if isinstance(preview_payload, dict) else None
                if isinstance(trade_gate, dict):
                    strategy_version = trade_gate.get("strategy_version") or strategy_version

            position = PaperPositionORM(
                created_at=filled_time,
                updated_at=filled_time,
                intent_key=intent_key,
                execution_audit_id=audit.id,
                ticker=audit.ticker,
                asset_type=audit.asset_type,
                side=side,
                quantity=qty,
                simulated_fill_price=simulated_fill_price,
                notional_usd=round(qty * simulated_fill_price, 2),
                cost_basis_usd=round(qty * simulated_fill_price, 2),
                close_price=None,
                realized_pnl=None,
                status="open",
                opened_at=filled_time,
                closed_at=None,
                strategy_version=strategy_version,
                confidence=audit.confidence,
            )
            session.add(position)
            session.commit()
            session.refresh(position)
            return position.id

    def list_recoverable_intents(self, *, now: datetime, limit: int = 25) -> list[AutomationIntentORM]:
        recoverable_statuses = [
            "failed_retryable",
            "blocked_by_budget",
            "circuit_open",
            "claimed",
            "placing",
        ]
        with SessionLocal() as session:
            return (
                session.execute(
                    select(AutomationIntentORM)
                    .where(AutomationIntentORM.status.in_(recoverable_statuses))
                    .order_by(desc(AutomationIntentORM.updated_at))
                    .limit(limit)
                )
                .scalars()
                .all()
            )

    def get_latest_intent_for_symbol(self, symbol: str) -> AutomationIntentORM | None:
        with SessionLocal() as session:
            return (
                session.execute(
                    select(AutomationIntentORM)
                    .where(AutomationIntentORM.symbol == symbol.upper())
                    .order_by(desc(AutomationIntentORM.created_at), desc(AutomationIntentORM.id))
                    .limit(1)
                )
                .scalar_one_or_none()
            )

    def get_latest_completed_action_for_symbol(self, symbol: str) -> AutomationIntentORM | None:
        with SessionLocal() as session:
            return (
                session.execute(
                    select(AutomationIntentORM)
                    .where(
                        AutomationIntentORM.symbol == symbol.upper(),
                        AutomationIntentORM.status == "dry_run_complete",
                    )
                    .order_by(desc(AutomationIntentORM.created_at), desc(AutomationIntentORM.id))
                    .limit(1)
                )
                .scalar_one_or_none()
            )

    def find_execution_audit_by_idempotency_key(self, idempotency_key: str | None) -> ExecutionAuditORM | None:
        if not idempotency_key:
            return None
        with SessionLocal() as session:
            return (
                session.execute(
                    select(ExecutionAuditORM)
                    .where(ExecutionAuditORM.idempotency_key == idempotency_key)
                    .order_by(desc(ExecutionAuditORM.updated_at), desc(ExecutionAuditORM.id))
                    .limit(1)
                )
                .scalar_one_or_none()
            )

    def count_requests_since(
        self,
        *,
        since: datetime,
        symbol: str | None = None,
    ) -> int:
        with SessionLocal() as session:
            query = select(AutomationIntentORM).where(
                AutomationIntentORM.last_attempt_at.is_not(None),
                AutomationIntentORM.last_attempt_at >= since,
            )
            if symbol is not None:
                query = query.where(AutomationIntentORM.symbol == symbol.upper())
            rows = session.execute(query).scalars().all()
            return sum(int(row.request_count_used or 0) for row in rows)

    def list_recent_intents(self, limit: int = 25) -> list[AutomationIntentSummary]:
        with SessionLocal() as session:
            rows = (
                session.execute(
                    select(AutomationIntentORM)
                    .order_by(desc(AutomationIntentORM.created_at), desc(AutomationIntentORM.id))
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [self._map(row) for row in rows]

    def breaker_pre_execution_should_block(
        self, *, now: datetime, owner: str
    ) -> tuple[bool, datetime | None, str | None]:
        with SessionLocal() as session:
            row = session.get(PaperLoopBreakerORM, _BREAKER_KEY)
            if row is None:
                return False, None, None
            if row.phase == "open" and row.open_until and self._as_utc(row.open_until) > now:
                return True, self._as_utc(row.open_until), "Execution circuit breaker is open."
            if row.phase == "half_open":
                po, pe = row.probe_owner, row.probe_expires_at
                if po and po != owner and pe and self._as_utc(pe) > now:
                    return (
                        True,
                        self._as_utc(pe),
                        "Half-open probe held by another worker.",
                    )
            return False, None, None

    def breaker_prepare_for_place(
        self,
        *,
        owner: str,
        now: datetime,
        probe_ttl_seconds: int,
    ) -> tuple[bool, datetime | None, str | None, bool]:
        """Returns (allowed, next_retry_at, reason, use_half_open_failure_path)."""
        with SessionLocal() as session:
            with session.begin():
                row = self._ensure_breaker_row(session, now=now)
                if row.phase == "open":
                    ou = row.open_until
                    if ou is not None and self._as_utc(ou) > now:
                        return False, self._as_utc(ou), "open", False
                    row.phase = "half_open"
                    row.probe_owner = None
                    row.probe_expires_at = None
                    row.updated_at = now
                    metrics.increment("automation.breaker.transition_open_to_half_open")

                if row.phase == "half_open":
                    probe_free = (
                        row.probe_owner is None
                        or row.probe_expires_at is None
                        or self._as_utc(row.probe_expires_at) <= now
                    )
                    same_owner = row.probe_owner == owner
                    if not probe_free and not same_owner:
                        pe = row.probe_expires_at
                        return (
                            False,
                            self._as_utc(pe) if pe else now,
                            "half_open_busy",
                            False,
                        )
                    row.probe_owner = owner
                    row.probe_expires_at = now + timedelta(seconds=probe_ttl_seconds)
                    row.updated_at = now
                    return True, None, None, True

                if row.phase == "closed":
                    return True, None, None, False

                return False, now, f"unknown_phase:{row.phase}", False

    def breaker_on_place_success(self, *, now: datetime) -> None:
        with SessionLocal() as session:
            with session.begin():
                row = self._ensure_breaker_row(session, now=now)
                row.phase = "closed"
                row.open_until = None
                row.opened_at = None
                row.probe_owner = None
                row.probe_expires_at = None
                row.failures_in_window = 0
                row.failures_window_started_at = None
                row.last_error = None
                row.updated_at = now
        metrics.increment("automation.breaker.transition_to_closed")

    def breaker_on_place_failure(
        self,
        *,
        now: datetime,
        message: str,
        half_open_probe: bool,
        failures_to_open: int,
        failure_window_minutes: int,
        open_minutes: int,
    ) -> None:
        with SessionLocal() as session:
            with session.begin():
                row = self._ensure_breaker_row(session, now=now)
                row.last_error = message
                row.updated_at = now
                if half_open_probe:
                    row.phase = "open"
                    row.open_until = now + timedelta(minutes=open_minutes)
                    row.opened_at = now
                    row.probe_owner = None
                    row.probe_expires_at = None
                    metrics.increment("automation.breaker.transition_half_open_to_open")
                    return

                fw = timedelta(minutes=failure_window_minutes)
                if row.failures_window_started_at is None or (
                    now - self._as_utc(row.failures_window_started_at)
                ) > fw:
                    row.failures_in_window = 0
                    row.failures_window_started_at = now
                row.failures_in_window = int(row.failures_in_window or 0) + 1
                if row.failures_in_window >= failures_to_open:
                    row.phase = "open"
                    row.open_until = now + timedelta(minutes=open_minutes)
                    row.opened_at = now
                    row.failures_in_window = 0
                    row.failures_window_started_at = None
                    metrics.increment("automation.breaker.transition_closed_to_open")

    def breaker_snapshot_from_db(self) -> AutomationBreakerSnapshot:
        now = self._utc_now()
        with SessionLocal() as session:
            row = session.get(PaperLoopBreakerORM, _BREAKER_KEY)
            if row is None:
                return AutomationBreakerSnapshot()
            state: str = row.phase
            if state == "open" and row.open_until and self._as_utc(row.open_until) <= now:
                state = "half_open"
            return AutomationBreakerSnapshot(
                state=state,  # type: ignore[arg-type]
                opened_at=row.opened_at,
                open_until=row.open_until,
                consecutive_failures=int(row.failures_in_window or 0),
                last_error=row.last_error,
                probe_owner=row.probe_owner,
                probe_expires_at=row.probe_expires_at,
            )

    def build_status_response(
        self,
        *,
        enabled: bool,
        phase: str,
        kill_switch_enabled: bool,
        last_processed_run_id: str | None,
        last_processed_run_at: datetime | None,
        last_recovery_at: datetime | None,
        budget: AutomationBudgetSnapshot,
        metrics_snapshot: dict[str, dict],
        limit: int = 25,
    ) -> AutomationStatusResponse:
        recent_intents = self.list_recent_intents(limit=limit)
        status_counts = Counter(intent.status for intent in recent_intents)
        counters = metrics_snapshot.get("counters", {})
        considered = int(counters.get("automation.candidates.considered", 0))
        reached = int(counters.get("automation.candidates.reached_execution_call", 0))
        filter_pct: float | None = None
        if considered > 0:
            filter_pct = round((1.0 - (reached / considered)) * 100.0, 2)
        return AutomationStatusResponse(
            enabled=enabled,
            phase=phase,
            kill_switch_enabled=kill_switch_enabled,
            last_processed_run_id=last_processed_run_id,
            last_processed_run_at=last_processed_run_at,
            last_recovery_at=last_recovery_at,
            requests_made=int(counters.get("automation.execution.requests_made", 0)),
            requests_avoided=int(counters.get("automation.execution.requests_avoided", 0)),
            dedupe_hits=int(counters.get("automation.dedupe.hits", 0)),
            retries=int(counters.get("automation.retry.count", 0)),
            blocked_by_budget=int(counters.get("automation.blocked.budget", 0)),
            blocked_by_gate=int(counters.get("automation.blocked.gate", 0)),
            blocked_by_cooldown=int(counters.get("automation.blocked.cooldown", 0)),
            blocked_by_circuit=int(counters.get("automation.blocked.circuit_open", 0)),
            recent_status_counts=dict(status_counts),
            budget=budget,
            breaker=self.breaker_snapshot_from_db(),
            recent_intents=recent_intents,
            candidates_considered=considered,
            candidates_reached_execution_call=reached,
            filter_rate_pct=filter_pct,
        )

    def _map(self, row: AutomationIntentORM) -> AutomationIntentSummary:
        return AutomationIntentSummary(
            id=row.id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            run_id=row.run_id,
            symbol=row.symbol,
            asset_type=row.asset_type,
            side=row.side,
            qty=row.qty,
            strategy_version=row.strategy_version,
            confidence=row.confidence,
            horizon=row.horizon,
            status=row.status,
            status_reason=row.status_reason,
            idempotency_key=row.idempotency_key,
            execution_audit_id=row.execution_audit_id,
            attempt_count=row.attempt_count,
            request_count_used=row.request_count_used,
            request_count_avoided=row.request_count_avoided,
            last_attempt_at=row.last_attempt_at,
            next_retry_at=row.next_retry_at,
            cooldown_until=row.cooldown_until,
            incident_class=getattr(row, "incident_class", None),
        )
