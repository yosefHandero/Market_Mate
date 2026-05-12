from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import inspect
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.system import MaintenanceStateORM

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StartupMaintenanceRunResult:
    repaired_signal_outcome_returns: int | None
    relinked_execution_audits: int | None
    recovered_automation_intents: int | None
    ran_tasks: tuple[str, ...]
    skipped_tasks: tuple[str, ...]


@dataclass(frozen=True)
class _StartupMaintenanceTask:
    name: str
    timestamp_field: str
    result_field: str
    func: Callable[[], Any]


class StartupMaintenanceService:
    STATE_KEY = "default"
    DEFAULT_MIN_INTERVAL_MINUTES = 60

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        sync_signal_outcome_returns: Callable[[], Any] | None = None,
        backfill_execution_audit_signal_links: Callable[[], Any] | None = None,
        recover_due_intents: Callable[[], Any] | None = None,
        maintenance_logger: logging.Logger | None = None,
    ) -> None:
        if (
            sync_signal_outcome_returns is None
            or backfill_execution_audit_signal_links is None
            or recover_due_intents is None
        ):
            from app.dependencies import automation_service, scan_repository

            sync_signal_outcome_returns = sync_signal_outcome_returns or scan_repository.sync_signal_outcome_returns
            backfill_execution_audit_signal_links = (
                backfill_execution_audit_signal_links
                or scan_repository.backfill_execution_audit_signal_links
            )
            recover_due_intents = recover_due_intents or automation_service.recover_due_intents

        self._session_factory = session_factory
        self._sync_signal_outcome_returns = sync_signal_outcome_returns
        self._backfill_execution_audit_signal_links = backfill_execution_audit_signal_links
        self._recover_due_intents = recover_due_intents
        self._logger = maintenance_logger or logger

    async def run_if_due(
        self,
        now: datetime | None = None,
        min_interval_minutes: int = DEFAULT_MIN_INTERVAL_MINUTES,
    ) -> StartupMaintenanceRunResult:
        run_at = self._normalize_datetime(now or datetime.now(timezone.utc))
        min_interval = timedelta(minutes=min_interval_minutes)
        timestamps = self._load_timestamps()
        result_values: dict[str, int | None] = {
            "repaired_signal_outcome_returns": None,
            "relinked_execution_audits": None,
            "recovered_automation_intents": None,
        }
        ran_tasks: list[str] = []
        skipped_tasks: list[str] = []

        for task in self._tasks():
            last_run_at = timestamps[task.timestamp_field]
            if not self._is_due(last_run_at, now=run_at, min_interval=min_interval):
                skipped_tasks.append(task.name)
                continue

            try:
                task_result = await self._run_task(task)
                self._mark_task_complete(task.timestamp_field, run_at)
            except Exception:
                self._logger.exception(
                    "startup maintenance task failed",
                    extra={
                        "event": "startup_maintenance_task_failed",
                        "task": task.name,
                    },
                )
                raise

            result_values[task.result_field] = task_result
            ran_tasks.append(task.name)
            self._logger.info(
                "startup maintenance task completed",
                extra={
                    "event": "startup_maintenance_task_completed",
                    "task": task.name,
                    "result": task_result,
                },
            )

        return StartupMaintenanceRunResult(
            repaired_signal_outcome_returns=result_values["repaired_signal_outcome_returns"],
            relinked_execution_audits=result_values["relinked_execution_audits"],
            recovered_automation_intents=result_values["recovered_automation_intents"],
            ran_tasks=tuple(ran_tasks),
            skipped_tasks=tuple(skipped_tasks),
        )

    def _tasks(self) -> tuple[_StartupMaintenanceTask, ...]:
        return (
            _StartupMaintenanceTask(
                name="sync_signal_outcome_returns",
                timestamp_field="last_sync_signal_returns_at",
                result_field="repaired_signal_outcome_returns",
                func=self._sync_signal_outcome_returns,
            ),
            _StartupMaintenanceTask(
                name="backfill_execution_audit_signal_links",
                timestamp_field="last_backfill_audit_links_at",
                result_field="relinked_execution_audits",
                func=self._backfill_execution_audit_signal_links,
            ),
            _StartupMaintenanceTask(
                name="recover_due_intents",
                timestamp_field="last_recover_due_intents_at",
                result_field="recovered_automation_intents",
                func=self._recover_due_intents,
            ),
        )

    def _load_timestamps(self) -> dict[str, datetime | None]:
        with self._session_factory() as session:
            state = session.get(MaintenanceStateORM, self.STATE_KEY)
            if state is None:
                state = MaintenanceStateORM(key=self.STATE_KEY)
                session.add(state)
                try:
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
            return {
                "last_sync_signal_returns_at": self._normalize_optional_datetime(
                    state.last_sync_signal_returns_at
                ),
                "last_backfill_audit_links_at": self._normalize_optional_datetime(
                    state.last_backfill_audit_links_at
                ),
                "last_recover_due_intents_at": self._normalize_optional_datetime(
                    state.last_recover_due_intents_at
                ),
            }

    def _mark_task_complete(self, timestamp_field: str, completed_at: datetime) -> None:
        with self._session_factory() as session:
            state = session.get(MaintenanceStateORM, self.STATE_KEY)
            if state is None:
                state = MaintenanceStateORM(key=self.STATE_KEY)
                session.add(state)
            setattr(state, timestamp_field, completed_at)
            state.updated_at = completed_at
            try:
                session.commit()
            except Exception:
                session.rollback()
                raise

    async def _run_task(self, task: _StartupMaintenanceTask) -> int | None:
        result = task.func()
        if inspect.isawaitable(result):
            result = await result
        return result

    def _is_due(
        self,
        last_run_at: datetime | None,
        *,
        now: datetime,
        min_interval: timedelta,
    ) -> bool:
        if last_run_at is None:
            return True
        return now - last_run_at >= min_interval

    def _normalize_optional_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return self._normalize_datetime(value)

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
