import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.errors import AppError
from app.models.scan import ScanRunORM
from app.models.system import SchedulerStateORM
from app.schemas import ScanRun
from app.services.repository import ScanRepository
from app.services.scan_lease import ScanLeaseLost, run_with_scan_lease, shared_scan_lease
from app.services.scanner import ScannerService
from app.services.scheduler import SchedulerService
from app.services.scheduler_repository import SchedulerRepository
import app.services.repository as repository_module
import app.services.scheduler_repository as scheduler_repository_module


class ScanLeaseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "lease.db"
        self.engines = [
            create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
            for _ in range(2)
        ]
        for engine in self.engines:
            self.addCleanup(engine.dispose)
        Base.metadata.create_all(self.engines[0])
        self.factories = [sessionmaker(bind=engine, expire_on_commit=False) for engine in self.engines]
        self.repos = [SchedulerRepository(session_factory=factory) for factory in self.factories]
        self.patch = patch.object(scheduler_repository_module, "SessionLocal", self.factories[0])
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_independent_connections_compete_atomically_even_on_first_use(self):
        barrier = Barrier(2)

        def acquire(index):
            barrier.wait()
            return self.repos[index].acquire_lease(f"owner-{index}", for_maintenance=True)

        with ThreadPoolExecutor(max_workers=2) as pool:
            acquired = list(pool.map(acquire, range(2)))
        self.assertEqual(sum(acquired), 1)
        winner = acquired.index(True)
        loser = 1 - winner
        self.assertFalse(self.repos[loser].mark_run_started(f"owner-{loser}"))
        self.repos[loser].release_lease(f"owner-{loser}")
        self.assertEqual(self.repos[loser].get_state().lease_owner, f"owner-{winner}")
        self.repos[winner].release_lease(f"owner-{winner}")
        self.assertTrue(self.repos[loser].acquire_lease("next-operation", for_maintenance=True))

    def test_expired_owner_cannot_renew_finish_or_release_successor(self):
        first, second = self.repos
        now = datetime(2026, 9, 27)
        with patch.object(first, "_utc_now", return_value=now):
            self.assertTrue(first.acquire_lease("crashed", for_maintenance=True))
            self.assertTrue(first.mark_run_started("crashed"))
        later = now + timedelta(seconds=first.settings.scheduler_lease_seconds + 1)
        with patch.object(first, "_utc_now", return_value=later), patch.object(second, "_utc_now", return_value=later):
            self.assertTrue(second.recover_stale_run())
            self.assertTrue(second.acquire_lease("successor", for_maintenance=True))
            self.assertTrue(second.mark_run_started("successor"))
            self.assertFalse(first.heartbeat("crashed"))
            first.mark_run_finished("crashed", error="late error")
            first.release_lease("crashed")
            self.assertEqual(second.get_state().lease_owner, "successor")
            self.assertNotEqual(second.get_state().last_error, "late error")
            self.assertFalse(second.recover_stale_run(max_stale_seconds=-1))

    def test_pausing_scheduler_keeps_active_manual_lease(self):
        first, second = self.repos
        self.assertTrue(first.acquire_lease("manual", for_maintenance=True))
        first.set_enabled(enabled=False)
        self.assertTrue(first.get_state().running)
        self.assertFalse(second.acquire_lease("scheduled", for_maintenance=True))

    def test_verification_mode_blocks_manual_scan_and_scheduler_start(self):
        scanner = ScannerService.__new__(ScannerService)
        scanner.settings = self.repos[0].settings.model_copy(update={"runtime_verification_mode": True})
        scanner._run_scan = AsyncMock()
        scheduler = SchedulerService(scanner_service=scanner, repository=self.repos[0])
        scheduler.settings = scanner.settings
        for operation in (scanner.run_scan, scheduler.run_manual_scan):
            with self.assertRaises(AppError) as caught:
                asyncio.run(operation())
            self.assertEqual(caught.exception.status_code, 503)
            self.assertEqual(caught.exception.code, "runtime_verification_mode")
        with self.assertRaises(AppError):
            scheduler.start()
        scanner._run_scan.assert_not_awaited()
        self.assertFalse(self.repos[0].get_state().enabled)
        self.assertIsNone(self.repos[0].get_state().lease_owner)

    def test_manual_and_scheduled_contention_without_any_previous_run(self):
        service = ScannerService.__new__(ScannerService)
        service._run_scan = AsyncMock(return_value="new-result")
        scheduler = SchedulerService(scanner_service=service, repository=self.repos[1])
        started = asyncio.Event()
        release = asyncio.Event()

        async def held_scan():
            started.set()
            await release.wait()
            return "fresh-result"

        service._run_scan = AsyncMock(side_effect=held_scan)

        async def scenario():
            active = asyncio.create_task(service.run_scan())
            await started.wait()
            with self.assertRaises(AppError) as caught:
                await scheduler.run_manual_scan()
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(caught.exception.code, "scan_already_running")
            service._run_scan.assert_awaited_once()
            release.set()
            self.assertEqual(await active, "fresh-result")

        asyncio.run(scenario())
        self.assertIsNone(self.repos[0].get_state().lease_owner)

    def test_api_contention_returns_409_instead_of_previous_or_missing_run(self):
        from fastapi.testclient import TestClient
        from app.auth import require_admin_access
        from app.dependencies import get_scanner_service
        from app.main import app

        scanner = ScannerService.__new__(ScannerService)
        scanner._run_scan = AsyncMock()
        self.assertTrue(self.repos[1].acquire_lease("scheduled", for_maintenance=True))
        with patch.dict(app.dependency_overrides, {
            require_admin_access: lambda: None,
            get_scanner_service: lambda: scanner,
        }):
            response = TestClient(app).post("/scan/run")
        self.assertEqual(response.status_code, 409)
        self.assertIn("scan_already_running", response.text)
        self.assertNotIn("run_id", response.json())
        scanner._run_scan.assert_not_awaited()

    def test_long_work_renews_and_cancellation_releases(self):
        first, second = self.repos
        first.settings = first.settings.model_copy(update={"scheduler_lease_seconds": 0.3})
        cancelled = []

        async def scenario():
            async def work():
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(True)

            active = asyncio.create_task(run_with_scan_lease(work, first, source="manual"))
            await asyncio.sleep(0.65)
            self.assertFalse(second.acquire_lease("contender", for_maintenance=True))
            active.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await active

        asyncio.run(scenario())
        self.assertEqual(cancelled, [True])
        self.assertIsNone(first.get_state().lease_owner)

    def test_failed_heartbeat_cancels_provider_work(self):
        first = self.repos[0]
        first.settings = first.settings.model_copy(update={"scheduler_lease_seconds": 0.03})
        cancelled = []

        async def work():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

        with patch.object(first, "heartbeat", return_value=False):
            with self.assertRaises(ScanLeaseLost):
                asyncio.run(run_with_scan_lease(work, first, source="manual"))
        self.assertEqual(cancelled, [True])
        self.assertIsNone(first.get_state().lease_owner)

    def test_save_transaction_fences_owner_lost_after_campaign_lookup(self):
        first, second = self.repos
        repository = ScanRepository()
        run = ScanRun(run_id="must-not-save", created_at=datetime.now(timezone.utc), market_status="neutral",
                      scan_count=0, watchlist_size=0, results=[])

        def replace_owner(**kwargs):
            with self.factories[1].begin() as session:
                session.execute(update(SchedulerStateORM).values(
                    lease_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
                ))
            self.assertTrue(second.acquire_lease("successor", for_maintenance=True))
            return None

        async def scenario():
            async with shared_scan_lease(first, source="manual"):
                repository.save_run(run)

        with patch.object(repository, "_campaign_provenance", side_effect=replace_owner), \
             patch.object(repository_module, "SessionLocal", self.factories[0]):
            with self.assertRaises(ScanLeaseLost):
                asyncio.run(scenario())
        with self.factories[0]() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ScanRunORM)), 0)
        self.assertEqual(second.get_state().lease_owner, "successor")


if __name__ == "__main__":
    unittest.main()
