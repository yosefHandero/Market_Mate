import asyncio
import inspect
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
import app.worker as worker_module
from app.db import Base
from app.models.system import MaintenanceStateORM
from app.services.startup_maintenance import StartupMaintenanceService


class StartupMaintenanceServiceTests(unittest.TestCase):
    def _build_session_local(self):
        temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(temp_dir.name) / "scanner.db"
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
        self.addCleanup(temp_dir.cleanup)
        self.addCleanup(engine.dispose)
        return SessionLocal

    def _service(self, SessionLocal, calls: list[str]) -> StartupMaintenanceService:
        def sync_signal_outcome_returns() -> int:
            calls.append("sync_signal_outcome_returns")
            return 1

        def backfill_execution_audit_signal_links() -> int:
            calls.append("backfill_execution_audit_signal_links")
            return 2

        async def recover_due_intents() -> int:
            calls.append("recover_due_intents")
            return 3

        return StartupMaintenanceService(
            session_factory=SessionLocal,
            sync_signal_outcome_returns=sync_signal_outcome_returns,
            backfill_execution_audit_signal_links=backfill_execution_audit_signal_links,
            recover_due_intents=recover_due_intents,
        )

    def _maintenance_state(self, SessionLocal) -> MaintenanceStateORM:
        with SessionLocal() as session:
            return session.get(MaintenanceStateORM, StartupMaintenanceService.STATE_KEY)

    def test_runs_when_due(self) -> None:
        SessionLocal = self._build_session_local()
        calls: list[str] = []
        now = datetime(2026, 5, 12, 12, 0, 0)

        result = asyncio.run(
            self._service(SessionLocal, calls).run_if_due(
                now=now,
                min_interval_minutes=60,
            )
        )

        self.assertEqual(
            [
                "sync_signal_outcome_returns",
                "backfill_execution_audit_signal_links",
                "recover_due_intents",
            ],
            calls,
        )
        self.assertEqual(
            (
                "sync_signal_outcome_returns",
                "backfill_execution_audit_signal_links",
                "recover_due_intents",
            ),
            result.ran_tasks,
        )
        state = self._maintenance_state(SessionLocal)
        self.assertEqual(now, state.last_sync_signal_returns_at)
        self.assertEqual(now, state.last_backfill_audit_links_at)
        self.assertEqual(now, state.last_recover_due_intents_at)
        self.assertEqual(now, state.updated_at)

    def test_skips_within_min_interval(self) -> None:
        SessionLocal = self._build_session_local()
        calls: list[str] = []
        now = datetime(2026, 5, 12, 12, 0, 0)
        recent = now - timedelta(minutes=10)
        with SessionLocal() as session:
            session.add(
                MaintenanceStateORM(
                    key=StartupMaintenanceService.STATE_KEY,
                    last_sync_signal_returns_at=recent,
                    last_backfill_audit_links_at=recent,
                    last_recover_due_intents_at=recent,
                    updated_at=recent,
                )
            )
            session.commit()

        result = asyncio.run(
            self._service(SessionLocal, calls).run_if_due(
                now=now,
                min_interval_minutes=60,
            )
        )

        self.assertEqual([], calls)
        self.assertEqual((), result.ran_tasks)
        state = self._maintenance_state(SessionLocal)
        self.assertEqual(recent, state.last_sync_signal_returns_at)
        self.assertEqual(recent, state.last_backfill_audit_links_at)
        self.assertEqual(recent, state.last_recover_due_intents_at)
        self.assertEqual(recent, state.updated_at)

    def test_runs_only_due_tasks(self) -> None:
        SessionLocal = self._build_session_local()
        calls: list[str] = []
        now = datetime(2026, 5, 12, 12, 0, 0)
        old = now - timedelta(minutes=61)
        recent = now - timedelta(minutes=10)
        with SessionLocal() as session:
            session.add(
                MaintenanceStateORM(
                    key=StartupMaintenanceService.STATE_KEY,
                    last_sync_signal_returns_at=old,
                    last_backfill_audit_links_at=recent,
                    last_recover_due_intents_at=recent,
                    updated_at=recent,
                )
            )
            session.commit()

        result = asyncio.run(
            self._service(SessionLocal, calls).run_if_due(
                now=now,
                min_interval_minutes=60,
            )
        )

        self.assertEqual(["sync_signal_outcome_returns"], calls)
        self.assertEqual(("sync_signal_outcome_returns",), result.ran_tasks)
        state = self._maintenance_state(SessionLocal)
        self.assertEqual(now, state.last_sync_signal_returns_at)
        self.assertEqual(recent, state.last_backfill_audit_links_at)
        self.assertEqual(recent, state.last_recover_due_intents_at)
        self.assertEqual(now, state.updated_at)

    def test_worker_process_skips_maintenance(self) -> None:
        source = inspect.getsource(worker_module)

        self.assertNotIn("StartupMaintenanceService", source)
        self.assertNotIn("startup_maintenance", source)
        self.assertNotIn("apply_required_schema_patches", source)

    def test_startup_maintenance_does_not_call_apply_required_schema_patches(self) -> None:
        SessionLocal = self._build_session_local()
        calls: list[str] = []
        forbidden_patch = Mock(side_effect=AssertionError("startup maintenance must not repair schema"))

        with patch.object(db_module, "apply_required_schema_patches", forbidden_patch):
            asyncio.run(
                self._service(SessionLocal, calls).run_if_due(
                    now=datetime(2026, 5, 12, 12, 0, 0),
                    min_interval_minutes=60,
                )
            )

        forbidden_patch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
