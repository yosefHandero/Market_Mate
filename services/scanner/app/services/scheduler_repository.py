from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text, update
from sqlalchemy.exc import IntegrityError

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

    def __init__(self, *, session_factory=None) -> None:
        self.settings = get_settings()
        self._session_factory = session_factory

    def _session(self):
        return (self._session_factory or SessionLocal)()

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
            row.lease_owner
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
        with self._session() as session:
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
        with self._session() as session:
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
            # Pausing future scans must not revoke a scan already doing work.
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

    def acquire_lease(self, instance_id: str, *, for_maintenance: bool = False) -> bool:
        now = self._utc_now()
        lease_until = now + timedelta(seconds=self.settings.scheduler_lease_seconds)
        # Bootstrap separately so concurrent first callers cannot both insert.
        try:
            with self._session() as session:
                self._get_or_create_row(session)
                session.commit()
        except IntegrityError:
            pass
        with self._session() as session:
            result = session.execute(
                update(SchedulerStateORM)
                .where(
                    SchedulerStateORM.scheduler_key == self._KEY,
                    or_(SchedulerStateORM.enabled.is_(True), for_maintenance),
                    or_(
                        SchedulerStateORM.lease_expires_at.is_(None),
                        SchedulerStateORM.lease_expires_at < now,
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
        with self._session() as session:
            self._get_or_create_row(session)
            session.execute(
                update(SchedulerStateORM)
                .where(SchedulerStateORM.scheduler_key == self._KEY)
                .values(worker_heartbeat_at=now, updated_at=now)
            )
            session.commit()

    def recover_stale_run(self, *, max_stale_seconds: int = 7200) -> bool:
        now = self._utc_now()
        with self._session() as session:
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
            if row.lease_owner and lease_expires_at is not None and lease_expires_at > now:
                return False
            stale_by_time = bool(
                started_at is not None and (now - started_at).total_seconds() > max_stale_seconds
            )
            stale_by_lease = bool(lease_expires_at is not None and lease_expires_at < now)
            if not stale_by_time and not stale_by_lease:
                session.commit()
                return False
            result = session.execute(
                update(SchedulerStateORM)
                .where(
                    SchedulerStateORM.scheduler_key == self._KEY,
                    SchedulerStateORM.lease_owner == row.lease_owner,
                    SchedulerStateORM.lease_expires_at == row.lease_expires_at,
                    SchedulerStateORM.last_run_started_at == row.last_run_started_at,
                    SchedulerStateORM.last_run_finished_at == row.last_run_finished_at,
                )
                .values(
                    last_run_finished_at=now,
                    last_error=row.last_error or "Recovered stale scheduler run",
                    updated_at=now,
                )
            )
            session.commit()
            return bool(result.rowcount)

    def release_lease(self, instance_id: str) -> None:
        with self._session() as session:
            session.execute(
                update(SchedulerStateORM)
                .where(
                    SchedulerStateORM.scheduler_key == self._KEY,
                    SchedulerStateORM.lease_owner == instance_id,
                )
                .values(lease_owner=None, lease_expires_at=None, updated_at=self._utc_now())
            )
            session.commit()

    def _owned_live_lease(self, instance_id: str, now: datetime):
        return (
            SchedulerStateORM.scheduler_key == self._KEY,
            SchedulerStateORM.lease_owner == instance_id,
            SchedulerStateORM.lease_expires_at > now,
        )

    def heartbeat(self, instance_id: str) -> bool:
        now = self._utc_now()
        with self._session() as session:
            result = session.execute(
                update(SchedulerStateORM)
                .where(*self._owned_live_lease(instance_id, now))
                .values(
                    lease_expires_at=now + timedelta(seconds=self.settings.scheduler_lease_seconds),
                    updated_at=now,
                )
            )
            session.commit()
            return bool(result.rowcount)

    def check_lease(self, instance_id: str, *, session=None) -> bool:
        now = self._utc_now()
        if session is not None:
            result = session.execute(
                update(SchedulerStateORM)
                .where(*self._owned_live_lease(instance_id, now))
                .values(updated_at=now)
            )
            return bool(result.rowcount)
        with self._session() as own_session:
            return own_session.execute(
                select(SchedulerStateORM.scheduler_key).where(*self._owned_live_lease(instance_id, now))
            ).scalar_one_or_none() is not None

    def clear_error(self, instance_id: str) -> None:
        now = self._utc_now()
        with self._session() as session:
            session.execute(
                update(SchedulerStateORM)
                .where(*self._owned_live_lease(instance_id, now), SchedulerStateORM.enabled.is_(True))
                .values(last_error=None, updated_at=now)
            )
            session.commit()

    def due_for_run(self) -> bool:
        self.recover_stale_run(max_stale_seconds=self.settings.scheduler_lease_seconds * 4)
        now = self._utc_now()
        with self._session() as session:
            row = session.get(SchedulerStateORM, self._KEY)
            if row is None:
                return False
            if self._has_unclean_prior_run(
                last_run_started_at=row.last_run_started_at,
                last_run_finished_at=row.last_run_finished_at,
            ):
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
        with self._session() as session:
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

    def mark_run_started(self, instance_id: str) -> bool:
        now = self._utc_now()
        with self._session() as session:
            result = session.execute(
                update(SchedulerStateORM)
                .where(*self._owned_live_lease(instance_id, now))
                .values(last_run_started_at=now, updated_at=now)
            )
            session.commit()
            return bool(result.rowcount)

    def mark_run_finished(self, instance_id: str, *, error: str | None = None) -> None:
        now = self._utc_now()
        with self._session() as session:
            session.execute(
                update(SchedulerStateORM)
                .where(*self._owned_live_lease(instance_id, now))
                .values(
                    last_run_finished_at=now,
                    last_error=error,
                    next_run_at=now + timedelta(seconds=self.settings.scan_interval_seconds),
                    updated_at=now,
                )
            )
            session.commit()
