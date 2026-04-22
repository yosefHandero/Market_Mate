from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
import hashlib
import json
import random

from app.config import get_settings
from app.errors import AppError
from app.observability import metrics
from app.core.freshness import is_stale_signal
from app.schemas import (
    AutomationBudgetSnapshot,
    AutomationStatusResponse,
    OrderPlaceRequest,
    ScanResult,
    ScanRun,
)
from app.services.automation_repository import AutomationRepository
from app.services.execution import ExecutionService


class AutomationService:
    def __init__(
        self,
        *,
        repository: AutomationRepository | None = None,
        execution_service: ExecutionService | None = None,
    ) -> None:
        self.settings = get_settings()
        self.repository = repository or AutomationRepository()
        self.execution_service = execution_service or ExecutionService()
        self._singleflight: dict[str, asyncio.Task[bool]] = {}
        self._singleflight_lock = asyncio.Lock()
        self._last_processed_run_id: str | None = None
        self._last_processed_run_at: datetime | None = None
        self._last_recovery_at: datetime | None = None

    @property
    def phase(self) -> str:
        if not self.settings.paper_loop_enabled:
            return "disabled"
        return self.settings.paper_loop_phase

    @property
    def enabled(self) -> bool:
        return self.phase != "disabled"

    def status(self) -> AutomationStatusResponse:
        return self.repository.build_status_response(
            enabled=self.enabled,
            phase=self.phase,
            kill_switch_enabled=self.settings.paper_loop_kill_switch,
            last_processed_run_id=self._last_processed_run_id,
            last_processed_run_at=self._last_processed_run_at,
            last_recovery_at=self._last_recovery_at,
            budget=self._budget_snapshot(),
            metrics_snapshot=metrics.snapshot(),
        )

    async def process_completed_run(self, run: ScanRun) -> None:
        self._last_processed_run_id = run.run_id
        self._last_processed_run_at = run.created_at
        if not self.enabled:
            return
        await self.recover_due_intents()
        per_cycle_used = 0
        for result in run.results:
            if result.decision_signal not in {"BUY", "SELL"}:
                continue
            side = "buy" if result.decision_signal == "BUY" else "sell"
            qty = self._compute_qty(result)
            if qty <= 0:
                continue
            metrics.increment("automation.candidates.considered")
            window_start, window_end = self._intent_window_for(run.created_at)
            intent_key = self._intent_key(
                run_id=run.run_id,
                symbol=result.ticker,
                side=side,
                qty=qty,
                strategy_version=result.strategy_version,
                horizon=self.settings.trade_gate_horizon,
                window_start=window_start,
                window_end=window_end,
            )

            async def work() -> bool:
                return await self._process_candidate(
                    run=run,
                    result=result,
                    side=side,
                    qty=qty,
                    intent_key=intent_key,
                    window_start=window_start,
                    window_end=window_end,
                    per_cycle_budget_available=max(self.settings.paper_loop_max_actions_per_cycle - per_cycle_used, 0),
                )

            executed = await self._run_singleflight(intent_key, work)
            if executed:
                per_cycle_used += 1
                if per_cycle_used >= self.settings.paper_loop_max_actions_per_cycle:
                    break

    async def recover_due_intents(self) -> int:
        if not self.enabled or self.phase == "shadow":
            return 0
        now = self._utc_now()
        self._last_recovery_at = now
        recovered = 0
        max_a = self.settings.paper_loop_retry_max_attempts
        for row in self.repository.list_recoverable_intents(now=now):
            if int(row.attempt_count or 0) >= max_a:
                self.repository.update_intent(
                    intent_id=row.id,
                    status="failed_terminal",
                    status_reason="Retry cap exceeded (recovery skipped).",
                    incident_class="breaker_misbehavior",
                )
                continue
            next_retry_at = self._as_utc_optional(row.next_retry_at)
            claim_expires_at = self._as_utc_optional(row.claim_expires_at)
            if next_retry_at is not None and next_retry_at > now:
                continue
            if row.status in {"claimed", "placing"} and claim_expires_at is not None and claim_expires_at > now:
                continue
            if self._finalize_from_existing_audit(intent_id=row.id, idempotency_key=row.idempotency_key):
                recovered += 1
                continue
            try:
                request_payload = json.loads(row.request_payload_json or "{}")
            except json.JSONDecodeError:
                self.repository.update_intent(
                    intent_id=row.id,
                    status="failed_terminal",
                    status_reason="Stored request payload is invalid JSON.",
                    incident_class="reconciliation_mismatch",
                )
                continue
            if not request_payload:
                self.repository.update_intent(
                    intent_id=row.id,
                    status="failed_terminal",
                    status_reason="Stored request payload is empty.",
                    incident_class="reconciliation_mismatch",
                )
                continue
            if await self._execute_request_payload(
                intent_id=row.id,
                request_payload=request_payload,
                symbol=row.symbol,
            ):
                recovered += 1
        return recovered

    async def _process_candidate(
        self,
        *,
        run: ScanRun,
        result: ScanResult,
        side: str,
        qty: float,
        intent_key: str,
        window_start: datetime,
        window_end: datetime,
        per_cycle_budget_available: int,
    ) -> bool:
        now = self._utc_now()
        if not self._symbol_allowed(result.ticker):
            return False
        if result.execution_eligibility != "eligible":
            return False
        if (result.provider_status or "ok") != "ok":
            return False

        status, reason, next_retry_at, cooldown_until = self._pre_execution_decision(
            result=result,
            side=side,
            per_cycle_budget_available=per_cycle_budget_available,
            now=now,
        )
        incident_class = (
            "stale_signal"
            if status == "stale_signal"
            else "budget_bypass"
            if status == "blocked_by_budget"
            else "breaker_misbehavior"
            if status == "circuit_open"
            else None
        )
        idempotency_key = intent_key
        request_payload = self._request_payload(
            symbol=result.ticker,
            side=side,
            qty=qty,
            idempotency_key=idempotency_key,
        )
        row, created = self.repository.create_intent(
            run_id=run.run_id,
            symbol=result.ticker,
            asset_type=result.asset_type,
            side=side,
            qty=qty,
            strategy_version=result.strategy_version,
            confidence=result.calibrated_confidence,
            horizon=self.settings.trade_gate_horizon,
            window_start=window_start,
            window_end=window_end,
            intent_key=intent_key,
            intent_hash=self._sha256(intent_key),
            status=status,
            status_reason=reason,
            idempotency_key=idempotency_key,
            incident_class=incident_class,
            decision_payload=result.model_dump(mode="json"),
            request_payload=request_payload,
            request_count_avoided=1 if status != "pending" else 0,
            next_retry_at=next_retry_at,
            cooldown_until=cooldown_until,
        )
        if not created:
            metrics.increment("automation.dedupe.hits")
            return False

        metrics.increment("automation.intents.created")
        if status == "shadowed":
            metrics.increment("automation.intents.shadowed")
            metrics.increment("automation.execution.requests_avoided")
            return False
        if status == "blocked_by_budget":
            metrics.increment("automation.blocked.budget")
            metrics.increment("automation.execution.requests_avoided")
            return False
        if status == "blocked_by_cooldown":
            metrics.increment("automation.blocked.cooldown")
            metrics.increment("automation.execution.requests_avoided")
            return False
        if status == "circuit_open":
            metrics.increment("automation.blocked.circuit_open")
            metrics.increment("automation.execution.requests_avoided")
            return False
        if status == "stale_signal":
            metrics.increment("automation.execution.requests_avoided")
            return False
        if status in {"no_meaningful_delta", "no_open_position"}:
            metrics.increment("automation.execution.requests_avoided")
            return False

        return await self._execute_request_payload(
            intent_id=row.id,
            request_payload=request_payload,
            symbol=result.ticker,
        )

    async def _execute_request_payload(
        self,
        *,
        intent_id: int,
        request_payload: dict,
        symbol: str,
    ) -> bool:
        now = self._utc_now()
        max_a = self.settings.paper_loop_retry_max_attempts
        intent_row = self.repository.get_intent(intent_id)
        if intent_row is None:
            return False
        if int(intent_row.attempt_count or 0) >= max_a:
            self.repository.update_intent(
                intent_id=intent_id,
                status="failed_terminal",
                status_reason="Retry cap exceeded (no further place attempts).",
                    incident_class="breaker_misbehavior",
            )
            return False

        claim_expires_at = now + timedelta(seconds=self.settings.paper_loop_claim_ttl_seconds)
        if not self.repository.claim_intent(
            intent_id=intent_id,
            claimed_by=self.settings.app_instance_id,
            claim_expires_at=claim_expires_at,
            max_place_attempts=max_a,
        ):
            metrics.increment("automation.dedupe.hits")
            return False

        if self._finalize_from_existing_audit(
            intent_id=intent_id,
            idempotency_key=request_payload.get("idempotency_key"),
        ):
            self.repository.breaker_on_place_success(now=now)
            return False

        allowed, next_retry, reason, half_open_probe = self.repository.breaker_prepare_for_place(
            owner=self.settings.app_instance_id,
            now=now,
            probe_ttl_seconds=self.settings.paper_loop_claim_ttl_seconds,
        )
        if not allowed:
            self.repository.update_intent(
                intent_id=intent_id,
                status="circuit_open",
                status_reason=f"Circuit breaker: {reason or 'blocked'}",
                    incident_class="breaker_misbehavior",
                next_retry_at=next_retry,
            )
            metrics.increment("automation.blocked.circuit_open")
            metrics.increment("automation.execution.requests_avoided")
            return False

        self.repository.mark_placing(intent_id)
        request = OrderPlaceRequest(**request_payload)
        metrics.increment("automation.execution.attempted")
        metrics.increment("automation.execution.requests_made")
        metrics.increment("automation.candidates.reached_execution_call")
        try:
            response = await self.execution_service.place(request)
            cooldown_until = now + timedelta(minutes=self.settings.paper_loop_symbol_cooldown_minutes)
            if response.trade_gate and not response.trade_gate.allowed:
                metrics.increment("automation.blocked.gate")
                self.repository.update_intent(
                    intent_id=intent_id,
                    status="blocked_by_gate",
                    status_reason=response.message,
                    execution_audit_id=response.execution_audit_id,
                    incident_class="stale_signal" if "stale" in response.message.lower() else None,
                    request_count_used_increment=1,
                    attempt_increment=1,
                    last_attempt_at=now,
                    cooldown_until=cooldown_until,
                    request_payload=request_payload,
                )
                self.repository.breaker_on_place_success(now=now)
                return False
            self.repository.update_intent(
                intent_id=intent_id,
                status="dry_run_complete",
                status_reason=response.message,
                execution_audit_id=response.execution_audit_id,
                request_count_used_increment=1,
                attempt_increment=1,
                last_attempt_at=now,
                cooldown_until=cooldown_until,
                request_payload=request_payload,
            )
            if response.execution_audit_id is not None and response.raw:
                latest_price = float(response.raw.get("latest_price") or request_payload.get("limit_price") or 0.0)
            else:
                latest_price = float(request_payload.get("limit_price") or 0.0)
            if latest_price <= 0:
                audit = (
                    self.repository.find_execution_audit_by_idempotency_key(
                        request_payload.get("idempotency_key")
                    )
                    if request_payload.get("idempotency_key")
                    else None
                )
                latest_price = float(getattr(audit, "latest_price", 0.0) or 0.0)
            if latest_price > 0:
                self.repository.record_paper_position(
                    intent_id=intent_id,
                    simulated_fill_price=latest_price,
                    filled_at=now,
                )
            self.repository.breaker_on_place_success(now=now)
            return True
        except Exception as exc:
            retryable = self._is_retryable_exception(exc)
            request_payload_json = request_payload
            before_attempts = int(self.repository.get_intent(intent_id).attempt_count or 0)
            after_increment = before_attempts + 1
            if retryable and after_increment < max_a:
                metrics.increment("automation.retry.count")
                next_retry_at = now + self._retry_delay_for_attempt(after_increment)
                self.repository.update_intent(
                    intent_id=intent_id,
                    status="failed_retryable",
                    status_reason=str(exc),
                    incident_class="breaker_misbehavior",
                    request_count_used_increment=1,
                    attempt_increment=1,
                    last_attempt_at=now,
                    next_retry_at=next_retry_at,
                    request_payload=request_payload_json,
                )
                self.repository.breaker_on_place_failure(
                    now=now,
                    message=str(exc),
                    half_open_probe=half_open_probe,
                    failures_to_open=self.settings.paper_loop_breaker_failures_to_open,
                    failure_window_minutes=self.settings.paper_loop_breaker_failure_window_minutes,
                    open_minutes=self.settings.paper_loop_breaker_open_minutes,
                )
            else:
                self.repository.update_intent(
                    intent_id=intent_id,
                    status="failed_terminal",
                    status_reason=str(exc),
                    incident_class="breaker_misbehavior",
                    request_count_used_increment=1,
                    attempt_increment=1,
                    last_attempt_at=now,
                    request_payload=request_payload_json,
                )
                self.repository.breaker_on_place_failure(
                    now=now,
                    message=str(exc),
                    half_open_probe=half_open_probe,
                    failures_to_open=self.settings.paper_loop_breaker_failures_to_open,
                    failure_window_minutes=self.settings.paper_loop_breaker_failure_window_minutes,
                    open_minutes=self.settings.paper_loop_breaker_open_minutes,
                )
            return False

    def _pre_execution_decision(
        self,
        *,
        result: ScanResult,
        side: str,
        per_cycle_budget_available: int,
        now: datetime,
    ) -> tuple[str, str | None, datetime | None, datetime | None]:
        stale_after_minutes = max(self.settings.stale_signal_max_age_minutes, 1)
        is_stale, signal_age_minutes = is_stale_signal(
            observed_at=now,
            signal_created_at=result.created_at,
            stale_after_minutes=stale_after_minutes,
        )
        if is_stale:
            return "stale_signal", f"Signal is stale at {signal_age_minutes:.2f} minutes.", None, None
        if self.settings.paper_loop_kill_switch:
            return "circuit_open", "Automation kill switch is enabled.", now + timedelta(hours=1), None
        if self.phase == "shadow":
            return "shadowed", "Shadow mode only; request avoided.", None, None
        blocked, next_retry, msg = self.repository.breaker_pre_execution_should_block(
            now=now, owner=self.settings.app_instance_id
        )
        if blocked:
            return "circuit_open", msg or "Execution circuit breaker is blocking.", next_retry, None
        if per_cycle_budget_available <= 0:
            return (
                "blocked_by_budget",
                "Per-cycle action budget is exhausted.",
                now + timedelta(seconds=self.settings.scan_interval_seconds),
                None,
            )
        if self.repository.count_requests_since(since=now - timedelta(hours=1)) >= self.settings.paper_loop_max_requests_per_hour:
            return (
                "blocked_by_budget",
                "Hourly request budget is exhausted.",
                now + timedelta(hours=1),
                None,
            )
        if self.repository.count_requests_since(since=now - timedelta(days=1)) >= self.settings.paper_loop_max_requests_per_day:
            return (
                "blocked_by_budget",
                "Daily request budget is exhausted.",
                now + timedelta(days=1),
                None,
            )
        if (
            self.repository.count_requests_since(
                since=now - timedelta(seconds=self.settings.paper_loop_symbol_window_seconds),
                symbol=result.ticker,
            )
            >= self.settings.paper_loop_max_requests_per_symbol_window
        ):
            return (
                "blocked_by_budget",
                "Per-symbol request budget is exhausted.",
                now + timedelta(seconds=self.settings.paper_loop_symbol_window_seconds),
                None,
            )

        latest_completed = self.repository.get_latest_completed_action_for_symbol(result.ticker)
        latest_cooldown_until = (
            self._as_utc_optional(latest_completed.cooldown_until) if latest_completed else None
        )
        if latest_completed and latest_cooldown_until and latest_cooldown_until > now:
            return (
                "blocked_by_cooldown",
                f"Symbol cooldown active until {latest_cooldown_until.isoformat()}",
                latest_cooldown_until,
                latest_cooldown_until,
            )
        if side == "sell" and self.settings.paper_loop_opposite_side_requires_unwound:
            if latest_completed is None or latest_completed.side != "buy":
                return "no_open_position", "No open fake-money buy position is tracked for this symbol.", None, None

        latest_intent = self.repository.get_latest_intent_for_symbol(result.ticker)
        if (
            latest_intent
            and latest_intent.side == side
            and self.settings.paper_loop_same_side_repeat_requires_delta
            and latest_intent.strategy_version == result.strategy_version
        ):
            latest_confidence = float(latest_intent.confidence or 0.0)
            current_confidence = float(result.calibrated_confidence or 0.0)
            if current_confidence < latest_confidence + self.settings.paper_loop_min_confidence_delta:
                return "no_meaningful_delta", "Same-side signal did not clear the confidence-delta threshold.", None, None

        return "pending", None, None, None

    def _finalize_from_existing_audit(self, *, intent_id: int, idempotency_key: str | None) -> bool:
        audit = self.repository.find_execution_audit_by_idempotency_key(idempotency_key)
        if audit is None:
            return False
        intent_row = self.repository.get_intent(intent_id)
        max_a = self.settings.paper_loop_retry_max_attempts
        status = None
        if audit.lifecycle_status in {"dry_run", "submitted"}:
            status = "dry_run_complete"
        elif audit.lifecycle_status == "blocked":
            status = "blocked_by_gate"
        elif audit.lifecycle_status == "failed":
            if intent_row and int(intent_row.attempt_count or 0) >= max_a:
                status = "failed_terminal"
            else:
                status = "failed_retryable"
        if status is None:
            return False
        self.repository.update_intent(
            intent_id=intent_id,
            status=status,
            status_reason=audit.error_message or f"Recovered prior {audit.lifecycle_status} audit result.",
            execution_audit_id=audit.id,
            request_count_avoided_increment=1,
            next_retry_at=None,
        )
        metrics.increment("automation.execution.requests_avoided")
        return True

    def _compute_qty(self, result: ScanResult) -> float:
        price = float(result.price or 0.0)
        if price <= 0:
            return 0.0
        qty = self.settings.paper_loop_target_notional_usd / price
        qty = min(qty, self.settings.trade_gate_max_qty)
        return round(max(qty, 0.0), 6)

    def _request_payload(self, *, symbol: str, side: str, qty: float, idempotency_key: str) -> dict:
        return {
            "ticker": symbol.upper(),
            "side": side,
            "qty": qty,
            "order_type": "market",
            "dry_run": True,
            "idempotency_key": idempotency_key,
        }

    def _intent_window_for(self, observed_at: datetime) -> tuple[datetime, datetime]:
        end = self._as_utc(observed_at)
        start = end - timedelta(seconds=self.settings.scan_interval_seconds)
        return start, end

    def _intent_key(
        self,
        *,
        run_id: str,
        symbol: str,
        side: str,
        qty: float,
        strategy_version: str,
        horizon: str,
        window_start: datetime,
        window_end: datetime,
    ) -> str:
        qty_value = f"{qty:.6f}"
        return (
            f"paperloop:{run_id}:{symbol.upper()}:{side}:{qty_value}:{strategy_version}:{horizon}:"
            f"{window_start.isoformat()}:{window_end.isoformat()}"
        )

    def _symbol_allowed(self, symbol: str) -> bool:
        allowlist = self.settings.paper_loop_symbol_allowlist_items
        return not allowlist or symbol.upper() in allowlist

    def _budget_snapshot(self) -> AutomationBudgetSnapshot:
        now = self._utc_now()
        return AutomationBudgetSnapshot(
            hourly_limit=self.settings.paper_loop_max_requests_per_hour,
            hourly_used=self.repository.count_requests_since(since=now - timedelta(hours=1)),
            daily_limit=self.settings.paper_loop_max_requests_per_day,
            daily_used=self.repository.count_requests_since(since=now - timedelta(days=1)),
            per_symbol_window_limit=self.settings.paper_loop_max_requests_per_symbol_window,
            per_symbol_window_seconds=self.settings.paper_loop_symbol_window_seconds,
            per_cycle_limit=self.settings.paper_loop_max_actions_per_cycle,
        )

    def _retry_delay_for_attempt(self, attempt: int) -> timedelta:
        capped_attempt = max(min(attempt, self.settings.paper_loop_retry_max_attempts), 1)
        base_seconds = self.settings.paper_loop_retry_base_seconds * (2 ** (capped_attempt - 1))
        jitter = random.uniform(1 - self.settings.paper_loop_retry_jitter_ratio, 1 + self.settings.paper_loop_retry_jitter_ratio)
        return timedelta(seconds=base_seconds * jitter)

    def _is_retryable_exception(self, exc: Exception) -> bool:
        if isinstance(exc, AppError):
            return exc.status_code >= 500 or exc.code == "not_ready"
        return True

    async def _run_singleflight(
        self,
        key: str,
        work: Callable[[], Awaitable[bool]],
    ) -> bool:
        async with self._singleflight_lock:
            existing = self._singleflight.get(key)
            if existing is not None:
                metrics.increment("automation.dedupe.hits")
                return await existing
            task = asyncio.create_task(work())
            self._singleflight[key] = task
        try:
            return await task
        finally:
            async with self._singleflight_lock:
                if self._singleflight.get(key) is task:
                    self._singleflight.pop(key, None)

    def _sha256(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _as_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _as_utc_optional(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return self._as_utc(value)
