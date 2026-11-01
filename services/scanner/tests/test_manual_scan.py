import asyncio
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.errors import AppError
from app.schemas import ScanRun
from app.services.scanner import ScannerService
from app.services.scheduler import SchedulerService
from app.services.scheduler_repository import SchedulerRepository
import app.services.scheduler_repository as scheduler_repository_module


class ManualScanTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        session_patch = patch.object(scheduler_repository_module, "SessionLocal", factory)
        session_patch.start()
        self.addCleanup(session_patch.stop)
        self.repo = SchedulerRepository()

    def test_scan_deadline_cancels_work_then_allows_retry(self):
        service = ScannerService.__new__(ScannerService)
        service._SCAN_TIMEOUT_SECONDS = 0.01
        cancelled = []

        async def blocked():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

        service._run_scan = blocked
        with self.assertRaises(AppError) as caught:
            asyncio.run(service.run_scan())
        self.assertEqual(caught.exception.status_code, 504)
        self.assertEqual(cancelled, [True])
        expected = ScanRun(run_id="retry", created_at=datetime.now(timezone.utc),
                           market_status="neutral", scan_count=0, watchlist_size=0, results=[])
        service._run_scan = AsyncMock(return_value=expected)
        self.assertIs(asyncio.run(service.run_scan()), expected)

    def test_manual_scan_cannot_overlap_worker_and_releases_lease_after_failure(self):
        scanner = AsyncMock()
        scheduler = SchedulerService(scanner_service=scanner, repository=self.repo)
        self.assertTrue(self.repo.acquire_lease("worker-fixture", for_maintenance=True))
        with self.assertRaises(AppError) as caught:
            asyncio.run(scheduler.run_manual_scan())
        self.assertEqual(caught.exception.status_code, 409)
        scanner.run_scan.assert_not_awaited()
        self.repo.release_lease("worker-fixture")
        scanner.run_scan.side_effect = RuntimeError("fixture failure")
        with self.assertRaises(RuntimeError):
            asyncio.run(scheduler.run_manual_scan())
        state = self.repo.get_state()
        self.assertIsNone(state.lease_owner)
        self.assertIsNotNone(state.last_run_finished_at)
        self.assertFalse(state.enabled)
        scanner.run_scan.side_effect = None
        scanner.run_scan.return_value = "retry-success"
        self.assertEqual(asyncio.run(scheduler.run_manual_scan()), "retry-success")
        self.assertIsNone(self.repo.get_state().lease_owner)
