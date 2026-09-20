import asyncio
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.scan import PredictionSnapshotORM, SignalOutcomeORM
import app.services.repository as repository_module
import app.services.scheduler_repository as scheduler_repository_module
from app.services.scanner import ScannerService
from app.services.scheduler import SchedulerService
from app.services.scheduler_repository import SchedulerRepository


class OutcomeProcessingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.addCleanup(self.engine.dispose)
        for module in (repository_module, scheduler_repository_module):
            patcher = patch.object(module, "SessionLocal", self.factory)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.now = datetime(2026, 9, 19, tzinfo=timezone.utc)
        self.repo = repository_module.ScanRepository()

    def signal(self, **changes):
        values = dict(
            run_id="isolated-fixture", ticker="AAPL", signal="BUY", confidence=70,
            entry_price=100, generated_at=self.now - timedelta(days=30),
        )
        values.update(changes)
        return SignalOutcomeORM(**values)

    def prediction(self, **changes):
        values = dict(
            run_id="isolated-fixture", ticker="AAPL", signal="BUY", entry_price=100,
            range_low=99, range_high=101, generated_at=self.now - timedelta(days=30),
            horizon="1h", decision_role="production", policy_id="hybrid_legacy",
            policy_version="unchanged-version", decision_fingerprint="unchanged-decision",
            learned_artifacts_fingerprint="unchanged-pin", campaign_id="unchanged-campaign",
            record_hash="unchanged-record",
        )
        values.update(changes)
        return PredictionSnapshotORM(**values)

    def service(self, *, price=102, error=None):
        service = ScannerService.__new__(ScannerService)
        service.repo = self.repo
        service._analyze_semaphore = asyncio.Semaphore(1)
        service.alpaca = Mock()
        service.alpaca.get_price_on_or_after_timestamp = AsyncMock(return_value=price, side_effect=error)
        service.alpaca.get_crypto_price_on_or_after_timestamp = AsyncMock(return_value=price, side_effect=error)
        return service

    def test_terminal_missed_signal_rows_cannot_starve_pending_batch(self):
        with self.factory() as session:
            session.add(self.signal(status_15m="missed", status_1h="missed", status_1d="missed", status_1w="missed"))
            pending = self.signal(ticker="MSFT", generated_at=self.now - timedelta(days=28))
            session.add(pending)
            session.commit()
        due = self.repo.list_due_signal_outcome_evaluations(observed_at=self.now, limit=1)
        self.assertEqual({item.outcome_id for item in due}, {pending.id})
        self.assertEqual({item.horizon for item in due}, {"15m", "1h", "1d", "1w"})

    def test_unripe_weekly_prediction_cannot_starve_due_hourly_batch(self):
        with self.factory() as session:
            session.add(self.prediction(horizon="1w", generated_at=self.now - timedelta(days=2)))
            pending = self.prediction(ticker="MSFT", generated_at=self.now - timedelta(hours=2))
            session.add(pending)
            session.commit()
        due = self.repo.list_due_prediction_evaluations(observed_at=self.now, limit=1)
        self.assertEqual([item.snapshot_id for item in due], [pending.id])

    def test_terminal_and_unripe_signals_do_not_inflate_backlog_counts(self):
        with self.factory() as session:
            session.add(self.signal(status_15m="missed", status_1h="missed", status_1d="missed", status_1w="missed"))
            session.add(self.signal(generated_at=self.now - timedelta(minutes=20)))
            session.commit()
        self.assertEqual(self.repo.get_due_outcome_counts(observed_at=self.now), {"15m": 1, "1h": 0, "1d": 0, "1w": 0})

    def test_backlog_count_is_not_truncated_to_processing_batch(self):
        with self.factory() as session:
            session.add_all([self.signal() for _ in range(5001)])
            session.commit()
        self.assertEqual(
            self.repo.get_due_outcome_counts(observed_at=self.now),
            {"15m": 5001, "1h": 5001, "1d": 5001, "1w": 5001},
        )

    def test_signal_provider_error_keeps_expired_evidence_pending_and_retries_later(self):
        with self.factory() as session:
            row = self.signal()
            session.add(row)
            session.commit()
        service = self.service(error=TimeoutError("unavailable"))
        with patch("app.services.scanner.time.monotonic", return_value=100):
            self.assertEqual(asyncio.run(service._refresh_due_signal_outcomes(self.now, limit=1)), 0)
            self.assertEqual(asyncio.run(service._refresh_due_signal_outcomes(self.now, limit=1)), 0)
        self.assertEqual(service.alpaca.get_price_on_or_after_timestamp.await_count, 4)
        with self.factory() as session:
            stored = session.get(SignalOutcomeORM, row.id)
            self.assertEqual(stored.status_1h, "pending")
            self.assertIsNone(stored.price_after_1h)
        service.alpaca.get_price_on_or_after_timestamp.side_effect = None
        with patch("app.services.scanner.time.monotonic", return_value=401):
            self.assertEqual(asyncio.run(service._refresh_due_signal_outcomes(self.now, limit=1)), 4)

    def test_deferred_old_prediction_allows_next_row_to_progress_without_relabeling_roles(self):
        with self.factory() as session:
            production = self.prediction()
            shadow = self.prediction(ticker="MSFT", decision_role="shadow", policy_id="weekly_probability")
            session.add_all([production, shadow])
            session.commit()
        service = self.service(error=TimeoutError("unavailable"))
        self.assertEqual(asyncio.run(service._refresh_due_prediction_snapshots(self.now, limit=1)), 0)
        service.alpaca.get_price_on_or_after_timestamp.side_effect = None
        self.assertEqual(asyncio.run(service._refresh_due_prediction_snapshots(self.now, limit=1)), 1)
        with self.factory() as session:
            stored_production = session.get(PredictionSnapshotORM, production.id)
            stored_shadow = session.get(PredictionSnapshotORM, shadow.id)
            self.assertEqual(stored_production.status, "pending")
            self.assertIsNone(stored_production.price_at_horizon)
            self.assertEqual(stored_shadow.status, "resolved")
            self.assertEqual(stored_shadow.price_at_horizon, 102)
            for stored, role, policy in ((stored_production, "production", "hybrid_legacy"), (stored_shadow, "shadow", "weekly_probability")):
                self.assertEqual(stored.decision_role, role)
                self.assertEqual(stored.policy_id, policy)
                self.assertEqual(stored.decision_fingerprint, "unchanged-decision")
                self.assertEqual(stored.learned_artifacts_fingerprint, "unchanged-pin")
                self.assertEqual(stored.campaign_id, "unchanged-campaign")
                self.assertEqual(stored.record_hash, "unchanged-record")

    def test_successful_empty_response_retains_existing_expiry_behavior(self):
        with self.factory() as session:
            expired = self.prediction()
            recent = self.prediction(generated_at=self.now - timedelta(hours=2))
            session.add_all([expired, recent])
            session.commit()
        service = self.service(price=None)
        self.assertEqual(asyncio.run(service._refresh_due_prediction_snapshots(self.now, limit=2)), 1)
        with self.factory() as session:
            self.assertEqual(session.get(PredictionSnapshotORM, expired.id).status, "missed")
            self.assertEqual(session.get(PredictionSnapshotORM, recent.id).status, "pending")

    def test_path_provider_error_does_not_finalize_incomplete_exit_outcome(self):
        with self.factory() as session:
            row = self.prediction(estimated_exit_price=105, invalidation_level=95)
            session.add(row)
            session.commit()
        service = self.service()
        service.alpaca.get_historical_stock_bars = AsyncMock(side_effect=TimeoutError("unavailable"))
        self.assertEqual(asyncio.run(service._refresh_due_prediction_snapshots(self.now, limit=1)), 0)
        with self.factory() as session:
            stored = session.get(PredictionSnapshotORM, row.id)
            self.assertEqual(stored.status, "pending")
            self.assertIsNone(stored.price_at_horizon)
            self.assertIsNone(stored.exit_window_status)

    def test_disabled_scan_scheduler_still_exclusively_leases_maintenance(self):
        repo = SchedulerRepository()
        repo._utc_now = Mock(return_value=self.now.replace(tzinfo=None))
        repo.set_enabled(enabled=False)
        self.assertFalse(repo.acquire_lease("worker-a"))
        self.assertTrue(repo.acquire_lease("worker-a", for_maintenance=True))
        self.assertFalse(repo.acquire_lease("worker-b", for_maintenance=True))
        before = repo.get_state().lease_expires_at
        with patch.object(repo, "_utc_now", return_value=self.now.replace(tzinfo=None) + timedelta(seconds=30)):
            repo.heartbeat("worker-a")
        self.assertGreater(repo.get_state().lease_expires_at, before)
        self.assertFalse(repo.get_state().enabled)
        self.assertFalse(repo.due_for_run())
        repo.release_lease("worker-a")
        self.assertTrue(repo.acquire_lease("worker-b", for_maintenance=True))


class ManualMaintenanceLoopTests(unittest.TestCase):
    def test_maintenance_is_bounded_paced_and_runs_with_scanning_disabled(self):
        scanner = Mock()
        scanner.refresh_due_signal_outcomes = AsyncMock(return_value=0)
        scanner.refresh_due_prediction_snapshots = AsyncMock(return_value=0)
        scanner.close_open_positions_past_horizon = AsyncMock(return_value=0)
        scanner.run_scan = AsyncMock()
        repository = Mock()
        repository.acquire_lease.return_value = True
        repository.due_for_run.return_value = False
        service = SchedulerService(scanner_service=scanner, repository=repository)
        service.settings = service.settings.model_copy(update={"scheduler_enabled": False})
        with patch("app.services.scheduler.time.monotonic", return_value=100), patch(
            "app.services.scheduler.asyncio.sleep", new=AsyncMock(side_effect=[None, asyncio.CancelledError])
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(service.run_forever())
        scanner.refresh_due_signal_outcomes.assert_awaited_once()
        scanner.refresh_due_prediction_snapshots.assert_awaited_once()
        self.assertEqual(scanner.refresh_due_signal_outcomes.await_args.kwargs["limit"], 8)
        self.assertEqual(scanner.refresh_due_prediction_snapshots.await_args.kwargs["limit"], 8)
        scanner.run_scan.assert_not_awaited()
        repository.set_enabled.assert_not_called()
        self.assertEqual(repository.release_lease.call_count, 2)


if __name__ == "__main__":
    unittest.main()
