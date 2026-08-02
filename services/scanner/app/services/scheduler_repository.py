from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text, update

from app.config import get_settings
from app.db import SessionLocal
from app.models.system import SchedulerStateORM


@dataclass(frozen=True)
class SchedulerState:
    enabled: bool
    running: bool
    worker_alive: bool
    interval_seconds: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    worker_heartbeat_at: datetime | None
    next_run_at: datetime | None
    last_run_started_at: datetime | None
    last_run_finished_at: datetime | None
    last_error: str | None


class SchedulerRepository:
    _KEY = "scanner"

    def __init__(self) -> None:
        self.settings = get_settings()

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def _as_utc(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _as_comparable_utc(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def _has_unclean_prior_run(
        self,
        *,
        last_run_started_at: datetime | None,
        last_run_finished_at: datetime | None,
    ) -> bool:
        started_at = self._as_comparable_utc(last_run_started_at)
        finished_at = self._as_comparable_utc(last_run_finished_at)
        return bool(started_at is not None and (finished_at is None or finished_at < started_at))

    def _default_state(self) -> SchedulerStateORM:
        now = self._utc_now()
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
        now = self._utc_now()
        lease_expires_at = self._as_utc(row.lease_expires_at)
        next_run_at = self._as_utc(row.next_run_at)
        last_run_started_at = self._as_utc(row.last_run_started_at)
        last_run_finished_at = self._as_utc(row.last_run_finished_at)
        running = bool(
            row.enabled
            and row.lease_owner
            and row.lease_expires_at
            and self._as_comparable_utc(row.lease_expires_at) >= now
        )
        worker_heartbeat_at = self._as_utc(getattr(row, "worker_heartbeat_at", None))
        worker_heartbeat_comparable = self._as_comparable_utc(getattr(row, "worker_heartbeat_at", None))
        worker_alive = bool(
            worker_heartbeat_comparable is not None
            and (now - worker_heartbeat_comparable).total_seconds()
            <= self.settings.worker_heartbeat_stale_seconds
        )
        return SchedulerState(
            enabled=row.enabled,
            running=running,
            worker_alive=worker_alive,
            interval_seconds=row.interval_seconds,
            lease_owner=row.lease_owner,
            lease_expires_at=lease_expires_at,
            worker_heartbeat_at=worker_heartbeat_at,
            next_run_at=next_run_at,
            last_run_started_at=last_run_started_at,
            last_run_finished_at=last_run_finished_at,
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
                    worker_alive=False,
                    interval_seconds=default.interval_seconds,
                    lease_owner=None,
                    lease_expires_at=None,
                    worker_heartbeat_at=None,
                    next_run_at=None,
                    last_run_started_at=None,
                    last_run_finished_at=None,
                    last_error=None,
                )
            return self._serialize(row)

    def set_enabled(self, *, enabled: bool) -> bool:
        now = self._utc_now()
        with SessionLocal() as session:
            row = session.execute(
                text(
                    """
                    SELECT enabled, next_run_at
                    FROM scheduler_state
                    WHERE scheduler_key = :scheduler_key
                    """
                ),
                {"scheduler_key": self._KEY},
            ).mappings().first()

            if row is None:
                session.execute(
                    text(
                        """
                        INSERT INTO scheduler_state (
                            scheduler_key,
                            enabled,
                            interval_seconds,
                            lease_owner,
                            lease_expires_at,
                            next_run_at,
                            last_run_started_at,
                            last_run_finished_at,
                            last_error,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            :scheduler_key,
                            :enabled,
                            :interval_seconds,
                            NULL,
                            NULL,
                            :next_run_at,
                            NULL,
                            NULL,
                            NULL,
                            :now,
                            :now
                        )
                        """
                    ),
                    {
                        "scheduler_key": self._KEY,
                        "enabled": enabled,
                        "interval_seconds": self.settings.scan_interval_seconds,
                        "next_run_at": now,
                        "now": now,
                    },
                )
                session.commit()
                return enabled

            changed = bool(row["enabled"]) != enabled
            values = {
                "scheduler_key": self._KEY,
                "enabled": enabled,
                "interval_seconds": self.settings.scan_interval_seconds,
                "now": now,
            }
            set_columns = [
                "enabled = :enabled",
                "interval_seconds = :interval_seconds",
                "updated_at = :now",
            ]
            if enabled and row["next_run_at"] is None:
                set_columns.append("next_run_at = :now")
            if not enabled:
                set_columns.extend(["lease_owner = NULL", "lease_expires_at = NULL"])
            session.execute(
                text(
                    f"""
                    UPDATE scheduler_state
                    SET {", ".join(set_columns)}
                    WHERE scheduler_key = :scheduler_key
                    """
                ),
                values,
            )
            session.commit()
            return changed or enabled

    def acquire_lease(self, instance_id: str) -> bool:
        now = self._utc_now()
        lease_until = now + timedelta(seconds=self.settings.scheduler_lease_seconds)
        with SessionLocal() as session:
            row = self._get_or_create_row(session)
            if not row.enabled:
                session.commit()
                return False
            result = session.execute(
                update(SchedulerStateORM)
                .where(
                    SchedulerStateORM.scheduler_key == self._KEY,
                    SchedulerStateORM.enabled.is_(True),
                    or_(
                        SchedulerStateORM.lease_expires_at.is_(None),
                        SchedulerStateORM.lease_expires_at < now,
                        SchedulerStateORM.lease_owner == instance_id,
                    ),
                )
                .values(
                    lease_owner=instance_id,
                    lease_expires_at=lease_until,
                    updated_at=now,
                )
            )
            acquired = bool(result.rowcount)
            session.commit()
            return acquired

    def record_worker_heartbeat(self, instance_id: str) -> None:
        now = self._utc_now()
        with SessionLocal() as session:
            self._get_or_create_row(session)
            session.execute(
                update(SchedulerStateORM)
                .where(SchedulerStateORM.scheduler_key == self._KEY)
                .values(worker_heartbeat_at=now, updated_at=now)
            )
            session.commit()

    def recover_stale_run(self, *, max_stale_seconds: int = 7200) -> bool:
        now = self._utc_now()
        with SessionLocal() as session:
            row = session.get(SchedulerStateORM, self._KEY)
            if row is None:
                return False
            if not self._has_unclean_prior_run(
                last_run_started_at=row.last_run_started_at,
                last_run_finished_at=row.last_run_finished_at,
            ):
                session.commit()
                return False
            started_at = self._as_comparable_utc(row.last_run_started_at)
            lease_expires_at = self._as_comparable_utc(row.lease_expires_at)
            stale_by_time = bool(
                started_at is not None and (now - started_at).total_seconds() > max_stale_seconds
            )
            stale_by_lease = bool(lease_expires_at is not None and lease_expires_at < now)
            if not stale_by_time and not stale_by_lease:
                session.commit()
                return False
            row.last_run_finished_at = now
            row.last_error = row.last_error or "Recovered stale scheduler run"
            row.updated_at = now
            session.commit()
            return True

    def release_lease(self, instance_id: str) -> None:
        with SessionLocal() as session:
            row = self._get_or_create_row(session)
            if row.lease_owner == instance_id:
                row.lease_owner = None
                row.lease_expires_at = None
                row.updated_at = self._utc_now()
                session.commit()
            else:
                session.commit()

    def heartbeat(self, instance_id: str) -> None:
        with SessionLocal() as session:
            row = self._get_or_create_row(session)
            if row.lease_owner == instance_id and row.enabled:
                row.lease_expires_at = self._utc_now() + timedelta(
                    seconds=self.settings.scheduler_lease_seconds
                )
                row.updated_at = self._utc_now()
            session.commit()

    def clear_error(self, instance_id: str) -> None:
        with SessionLocal() as session:
            row = self._get_or_create_row(session)
            if row.lease_owner == instance_id and row.enabled and row.last_error is not None:
                row.last_error = None
                row.updated_at = self._utc_now()
            session.commit()

    def due_for_run(self) -> bool:
        now = self._utc_now()
        with SessionLocal() as session:
            row = session.get(SchedulerStateORM, self._KEY)
            if row is None:
                return False
            if self._has_unclean_prior_run(
                last_run_started_at=row.last_run_started_at,
                last_run_finished_at=row.last_run_finished_at,
            ):
                started_at = self._as_comparable_utc(row.last_run_started_at)
                lease_expires_at = self._as_comparable_utc(row.lease_expires_at)
                if (
                    started_at is not None
                    and (now - started_at).total_seconds() > self.settings.scheduler_lease_seconds * 4
                ) or (lease_expires_at is not None and lease_expires_at < now):
                    row.last_run_finished_at = now
                    row.last_error = row.last_error or "Recovered stale scheduler run"
                    row.updated_at = now
                    session.commit()
                else:
                    session.commit()
                    return False
            next_run_at = self._as_comparable_utc(row.next_run_at)
            return bool(row.enabled and (next_run_at is None or next_run_at <= now))

    def reset_missed_run_on_startup(
        self,
        *,
        interval_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        now_value = self._as_comparable_utc(now) if now is not None else self._utc_now()
        with SessionLocal() as session:
            row = session.get(SchedulerStateORM, self._KEY)
            if row is None or not row.enabled:
                return False
            if self._has_unclean_prior_run(
                last_run_started_at=row.last_run_started_at,
                last_run_finished_at=row.last_run_finished_at,
            ):
                return False
            last_run_finished_at = self._as_comparable_utc(row.last_run_finished_at)
            if last_run_finished_at is None:
                return False
            if now_value - last_run_finished_at < timedelta(seconds=interval_seconds):
                return False
            row.next_run_at = now_value
            row.updated_at = now_value
            session.commit()
            return True

    def mark_run_started(self, instance_id: str) -> None:
        now = self._utc_now()
        with SessionLocal() as session:
            row = self._get_or_create_row(session)
            row.lease_owner = instance_id
            row.lease_expires_at = now + timedelta(seconds=self.settings.scheduler_lease_seconds)
            row.last_run_started_at = now
            row.updated_at = now
            session.commit()

    def mark_run_finished(self, instance_id: str, *, error: str | None = None) -> None:
        now = self._utc_now()
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
