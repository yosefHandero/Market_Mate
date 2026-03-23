from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models.system import SchedulerStateORM


@dataclass(frozen=True)
class SchedulerState:
    enabled: bool
    running: bool
    interval_seconds: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    next_run_at: datetime | None
    last_run_started_at: datetime | None
    last_run_finished_at: datetime | None
    last_error: str | None


class SchedulerRepository:
    _KEY = "scanner"

    def __init__(self) -> None:
        self.settings = get_settings()

    def _default_state(self) -> SchedulerStateORM:
        now = datetime.now(timezone.utc)
        return SchedulerStateORM(
            scheduler_key=self._KEY,
            enabled=False,
            interval_seconds=self.settings.scan_interval_seconds,
            lease_owner=None,
            lease_expires_at=None,
            next_run_at=now,
            last_run_started_at=None,
            last_run_finished_at=None,
            last_error=None,
            created_at=now,
            updated_at=now,
        )

    def _serialize(self, row: SchedulerStateORM) -> SchedulerState:
        now = datetime.now(timezone.utc)
        running = bool(
            row.enabled
            and row.lease_owner
            and row.lease_expires_at
            and row.lease_expires_at >= now
        )
        return SchedulerState(
            enabled=row.enabled,
            running=running,
            interval_seconds=row.interval_seconds,
            lease_owner=row.lease_owner,
            lease_expires_at=row.lease_expires_at,
            next_run_at=row.next_run_at,
            last_run_started_at=row.last_run_started_at,
            last_run_finished_at=row.last_run_finished_at,
            last_error=row.last_error,
        )

    def _get_or_create_row(self, session) -> SchedulerStateORM:
        row = session.get(SchedulerStateORM, self._KEY)
        if row is None:
            row = self._default_state()
            session.add(row)
            session.flush()
        return row

    def get_state(self) -> SchedulerState:
        with SessionLocal() as session:
            row = session.get(SchedulerStateORM, self._KEY)
            if row is None:
                default = self._default_state()
                return SchedulerState(
                    enabled=False,
                    running=False,
                    interval_seconds=default.interval_seconds,
                    lease_owner=None,
                    lease_expires_at=None,
                    next_run_at=None,
                    last_run_started_at=None,
                    last_run_finished_at=None,
                    last_error=None,
                )
            return self._serialize(row)

    def set_enabled(self, *, enabled: bool) -> bool:
        now = datetime.now(timezone.utc)
        with SessionLocal() as session:
            row = self._get_or_create_row(session)
            changed = row.enabled != enabled
            row.enabled = enabled
            row.interval_seconds = self.settings.scan_interval_seconds
            row.updated_at = now
            if enabled and row.next_run_at is None:
                row.next_run_at = now
            if not enabled:
                row.lease_owner = None
                row.lease_expires_at = None
            session.commit()
            return changed or enabled

    def acquire_lease(self, instance_id: str) -> bool:
        now = datetime.now(timezone.utc)
        with SessionLocal() as session:
            row = self._get_or_create_row(session)
            if not row.enabled:
                session.commit()
                return False
            lease_expired = row.lease_expires_at is None or row.lease_expires_at < now
            owned_by_self = row.lease_owner == instance_id
            if not lease_expired and not owned_by_self:
                session.commit()
                return False
            row.lease_owner = instance_id
            row.lease_expires_at = now + timedelta(seconds=self.settings.scheduler_lease_seconds)
            row.updated_at = now
            session.commit()
            return True

    def release_lease(self, instance_id: str) -> None:
        with SessionLocal() as session:
            row = self._get_or_create_row(session)
            if row.lease_owner == instance_id:
                row.lease_owner = None
                row.lease_expires_at = None
                row.updated_at = datetime.now(timezone.utc)
                session.commit()
            else:
                session.commit()

    def heartbeat(self, instance_id: str) -> None:
        with SessionLocal() as session:
            row = self._get_or_create_row(session)
            if row.lease_owner == instance_id and row.enabled:
                row.lease_expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=self.settings.scheduler_lease_seconds
                )
                row.updated_at = datetime.now(timezone.utc)
            session.commit()

    def due_for_run(self) -> bool:
        now = datetime.now(timezone.utc)
        with SessionLocal() as session:
            row = session.get(SchedulerStateORM, self._KEY)
            if row is None:
                return False
            return bool(row.enabled and (row.next_run_at is None or row.next_run_at <= now))

    def mark_run_started(self, instance_id: str) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as session:
            row = self._get_or_create_row(session)
            row.lease_owner = instance_id
            row.lease_expires_at = now + timedelta(seconds=self.settings.scheduler_lease_seconds)
            row.last_run_started_at = now
            row.updated_at = now
            session.commit()

    def mark_run_finished(self, instance_id: str, *, error: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as session:
            row = self._get_or_create_row(session)
            if row.lease_owner not in {None, instance_id}:
                session.commit()
                return
            row.last_run_finished_at = now
            row.last_error = error
            row.next_run_at = now + timedelta(seconds=self.settings.scan_interval_seconds)
            row.updated_at = now
            row.lease_owner = instance_id
            row.lease_expires_at = now + timedelta(seconds=self.settings.scheduler_lease_seconds)
            session.commit()
