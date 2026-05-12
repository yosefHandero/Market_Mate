from contextlib import contextmanager
from datetime import datetime, timedelta
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.scheduler_repository as scheduler_repository_module
from app.db import Base
from app.models.system import SchedulerStateORM
from app.services.scheduler_repository import SchedulerRepository


class SchedulerRepositoryTests(unittest.TestCase):
    @contextmanager
    def _repository_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            repo = SchedulerRepository()
            try:
                with patch.object(scheduler_repository_module, "SessionLocal", SessionLocal):
                    yield repo, SessionLocal
            finally:
                engine.dispose()

    def _insert_scheduler_state(
        self,
        SessionLocal,
        *,
        enabled: bool = True,
        now: datetime,
        next_run_at: datetime | None,
        last_run_started_at: datetime | None = None,
        last_run_finished_at: datetime | None = None,
    ) -> None:
        with SessionLocal() as session:
            session.add(
                SchedulerStateORM(
                    scheduler_key="scanner",
                    enabled=enabled,
                    interval_seconds=300,
                    lease_owner=None,
                    lease_expires_at=None,
                    next_run_at=next_run_at,
                    last_run_started_at=last_run_started_at,
                    last_run_finished_at=last_run_finished_at,
                    last_error=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

    def test_due_for_run_handles_sqlite_naive_datetimes_without_timezone_errors(self) -> None:
        with self._repository_context() as (repo, _SessionLocal):
            self.assertTrue(repo.set_enabled(enabled=True))
            self.assertTrue(repo.acquire_lease("scanner-test"))
            repo.heartbeat("scanner-test")
            self.assertTrue(repo.due_for_run())
            state = repo.get_state()

        self.assertTrue(state.running)
        self.assertIsNotNone(state.next_run_at)

    def test_due_for_run_requires_clean_prior_run_finished(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0)
        with self._repository_context() as (repo, SessionLocal):
            self._insert_scheduler_state(
                SessionLocal,
                now=now,
                next_run_at=now - timedelta(seconds=1),
                last_run_started_at=now - timedelta(minutes=5),
                last_run_finished_at=None,
            )
            with patch.object(repo, "_utc_now", return_value=now):
                self.assertFalse(repo.due_for_run())

    def test_due_for_run_blocks_when_finished_before_started(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0)
        with self._repository_context() as (repo, SessionLocal):
            self._insert_scheduler_state(
                SessionLocal,
                now=now,
                next_run_at=now - timedelta(seconds=1),
                last_run_started_at=now - timedelta(minutes=5),
                last_run_finished_at=now - timedelta(minutes=6),
            )
            with patch.object(repo, "_utc_now", return_value=now):
                self.assertFalse(repo.due_for_run())

    def test_due_for_run_allows_clean_finished_prior_run(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0)
        with self._repository_context() as (repo, SessionLocal):
            self._insert_scheduler_state(
                SessionLocal,
                now=now,
                next_run_at=now - timedelta(seconds=1),
                last_run_started_at=now - timedelta(minutes=5),
                last_run_finished_at=now - timedelta(minutes=4),
            )
            with patch.object(repo, "_utc_now", return_value=now):
                self.assertTrue(repo.due_for_run())

    def test_scheduler_run_missed_on_startup_resets_next_run_at(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0)
        interval_seconds = 300
        with self._repository_context() as (repo, SessionLocal):
            self._insert_scheduler_state(
                SessionLocal,
                now=now - timedelta(hours=1),
                next_run_at=now + timedelta(hours=1),
                last_run_started_at=now - timedelta(minutes=15),
                last_run_finished_at=now - timedelta(seconds=interval_seconds + 1),
            )

            reset = repo.reset_missed_run_on_startup(
                interval_seconds=interval_seconds,
                now=now,
            )

            with SessionLocal() as session:
                row = session.get(SchedulerStateORM, "scanner")

        self.assertTrue(reset)
        self.assertIsNotNone(row)
        self.assertEqual(row.next_run_at, now)


if __name__ == "__main__":
    unittest.main()
