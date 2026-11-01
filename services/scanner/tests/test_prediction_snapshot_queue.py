"""Isolated reproduction of the prediction queue captured on 2026-10-08.

The ORCL fields match the oldest selected live row; identity pins are fixtures.
Provider responses are mocked. No personal database or provider is contacted.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.scan import PredictionSnapshotORM
import app.services.repository as repository_module
from app.services.db_integrity import (
    install_prediction_immutability_trigger,
    record_hash_for_snapshot,
)
from app.services.scanner import ScannerService


class PredictionSnapshotQueueTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="prediction-snapshot-fixture-")
        self.addCleanup(directory.cleanup)
        database = (Path(directory.name) / "fixture.db").as_posix()
        # Schema probes need separate connections from the outcome transaction.
        self.engine = create_engine(f"sqlite:///{database}")
        Base.metadata.create_all(self.engine)
        install_prediction_immutability_trigger(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.addCleanup(self.engine.dispose)
        patcher = patch.object(repository_module, "SessionLocal", self.factory)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = repository_module.ScanRepository()
        self.now = datetime(2026, 10, 8, 22, 45, 13, 604202, tzinfo=timezone.utc)
        self.generated = datetime(2026, 9, 2, 21, 32, 23, 185801)

    def prediction(self, **changes):
        values = dict(
            run_id="isolated-prediction-queue", ticker="ORCL", asset_type="stock",
            signal="BUY", entry_price=145.71, range_low=130.2257, range_high=152.339,
            horizon="1w", generated_at=self.generated, status="pending",
            estimated_exit_price=148.62, invalidation_level=144.25,
            exit_window_status="pending", campaign_id="camp-5797d121289c6541",
            policy_id="hybrid_legacy", policy_version="fixture-policy-version",
            decision_role="production", decision_fingerprint="fixture-decision-pin",
            learned_artifacts_fingerprint="fixture-artifact-pin",
            config_fingerprint="fixture-config-pin", selection_status="selected",
        )
        values.update(changes)
        values.setdefault("resolve_due_at", values["generated_at"] + timedelta(days=8))
        values["record_hash"] = record_hash_for_snapshot(values)
        return PredictionSnapshotORM(**values)

    def insert(self, *rows):
        with self.factory() as session:
            session.add_all(rows)
            session.commit()

    def service(self, *, price=147.0):
        service = ScannerService.__new__(ScannerService)
        service.repo = self.repo
        service._analyze_semaphore = asyncio.Semaphore(1)
        service.alpaca = Mock()
        service.alpaca.get_price_on_or_after_timestamp = AsyncMock(return_value=price)
        service.alpaca.get_crypto_price_on_or_after_timestamp = AsyncMock(return_value=price)
        bars = [{"t": self.generated.isoformat(), "h": 149, "l": 145}]
        service.alpaca.get_historical_stock_bars = AsyncMock(return_value=bars)
        service.alpaca.get_historical_crypto_bars = AsyncMock(return_value=bars)
        return service

    def refresh(self, service, *, limit=1, observed_at=None):
        return asyncio.run(service._refresh_due_prediction_snapshots(
            observed_at or self.now, limit=limit,
        ))

    def assert_identity(self, stored, original):
        for column in (
            "campaign_id", "policy_id", "policy_version", "decision_role",
            "decision_fingerprint", "learned_artifacts_fingerprint",
            "config_fingerprint", "record_hash", "selection_status", "resolve_due_at",
        ):
            self.assertEqual(getattr(stored, column), getattr(original, column), column)
        self.assertEqual(
            stored.record_hash,
            record_hash_for_snapshot({column.name: getattr(stored, column.name)
                                      for column in PredictionSnapshotORM.__table__.columns}),
        )

    def test_captured_orcl_resolves_through_lookup_exit_disambiguation_and_persistence(self):
        row = self.prediction(id=9294)
        self.insert(row)
        selected = self.repo.list_due_prediction_evaluations(observed_at=self.now, limit=8)
        self.assertEqual([item.snapshot_id for item in selected], [9294])
        self.assertEqual(selected[0].target_at, self.generated + timedelta(days=7))
        self.assertEqual(selected[0].expires_at, self.generated + timedelta(days=21))
        service = self.service()
        hour = self.generated + timedelta(hours=1)
        async def bars(_ticker, *, timeframe, **_kwargs):
            if timeframe == "1Hour":
                return [{"t": hour.isoformat(), "h": 149, "l": 143.5}]
            return [{"h": 148.8, "l": 145}, {"h": 147, "l": 143.9}]
        service.alpaca.get_historical_stock_bars.side_effect = bars
        self.assertEqual(self.refresh(service), 1)
        service.alpaca.get_price_on_or_after_timestamp.assert_awaited_once_with(
            "ORCL", self.generated + timedelta(days=7),
            max_search_minutes=14 * 24 * 60, timeframe="1Day",
        )
        path_calls = service.alpaca.get_historical_stock_bars.await_args_list
        self.assertEqual(path_calls[0].kwargs, {
            "start": self.generated, "end": self.generated + timedelta(days=7),
            "timeframe": "1Hour", "limit": 5000,
        })
        self.assertEqual(path_calls[1].kwargs, {
            "start": hour, "end": hour + timedelta(hours=1),
            "timeframe": "1Min", "limit": 5000,
        })
        with self.factory() as session:
            stored = session.get(PredictionSnapshotORM, row.id)
            self.assertEqual(stored.status, "resolved")
            self.assertEqual(stored.price_at_horizon, 147)
            self.assertEqual((stored.accuracy_outcome, stored.in_range), ("in_range", True))
            self.assertEqual(stored.exit_window_status, "resolved")
            self.assertEqual((stored.exit_hit, stored.invalidation_hit), (True, False))
            self.assertEqual(stored.hold_return_pct, 0.8853)
            self.assertEqual(stored.protected_return_pct, 1.9971)
            self.assertTrue(stored.exit_window_helped)
            self.assertTrue(stored.resolved_late)
            self.assert_identity(stored, row)

    def test_older_campaign_batches_reduce_current_position_without_mixing_roles(self):
        old = [self.prediction(ticker=f"OLD{index}", generated_at=self.generated + timedelta(seconds=index))
               for index in range(4)]
        current = self.prediction(ticker="CURRENT", campaign_id="fixture-current-campaign",
                                  generated_at=datetime(2026, 9, 20))
        shadow = self.prediction(ticker="SHADOW", campaign_id=current.campaign_id,
                                 generated_at=current.generated_at, decision_role="shadow",
                                 policy_id="weekly_probability")
        self.insert(*old, current, shadow)
        service = self.service()
        positions = []
        for _ in range(3):
            due = self.repo.list_due_prediction_evaluations(observed_at=self.now, limit=20)
            positions.append([item.snapshot_id for item in due].index(current.id) + 1)
            if positions[-1] > 1:
                self.assertEqual(self.refresh(service, limit=2), 2)
        self.assertEqual(positions, [5, 3, 1])
        with self.factory() as session:
            self.assertTrue(all(session.get(PredictionSnapshotORM, row.id).status == "resolved" for row in old))
            self.assertEqual(session.get(PredictionSnapshotORM, current.id).status, "pending")
        self.assertEqual(self.refresh(service), 1)
        with self.factory() as session:
            self.assert_identity(session.get(PredictionSnapshotORM, current.id), current)
            stored_shadow = session.get(PredictionSnapshotORM, shadow.id)
            self.assertEqual(stored_shadow.status, "pending")
            self.assert_identity(stored_shadow, shadow)
        self.assertEqual(self.refresh(service), 1)
        with self.factory() as session:
            stored_shadow = session.get(PredictionSnapshotORM, shadow.id)
            self.assertEqual(stored_shadow.status, "resolved")
            self.assert_identity(stored_shadow, shadow)

    def test_valid_primary_with_empty_path_keeps_exit_outcome_unresolved(self):
        row = self.prediction()
        self.insert(row)
        service = self.service()
        service.alpaca.get_historical_stock_bars.return_value = []
        self.assertEqual(self.refresh(service), 1)
        with self.factory() as session:
            stored = session.get(PredictionSnapshotORM, row.id)
            self.assertEqual((stored.status, stored.price_at_horizon), ("resolved", 147))
            self.assertEqual(stored.exit_window_status, "unresolved")
            self.assertIsNone(stored.protected_return_pct)
            self.assertIsNone(stored.hold_return_pct)
            self.assertIsNone(stored.exit_window_helped)
            self.assert_identity(stored, row)

    def test_missing_price_is_missed_only_after_expiry_and_otherwise_retried(self):
        expired = self.prediction()
        recent = self.prediction(ticker="RECENT", generated_at=self.now.replace(tzinfo=None) - timedelta(days=8))
        self.insert(expired, recent)
        selected = self.repo.list_due_prediction_evaluations(observed_at=self.now, limit=2)
        self.assertLessEqual(recent.resolve_due_at, self.now.replace(tzinfo=None))
        self.assertLess(self.now.replace(tzinfo=None), selected[1].expires_at)
        service = self.service(price=None)
        with patch("app.services.scanner.time.monotonic", return_value=100):
            self.assertEqual(self.refresh(service, limit=2), 1)
            self.assertEqual(self.refresh(service, limit=2), 0)
        self.assertEqual(service.alpaca.get_price_on_or_after_timestamp.await_count, 2)
        service.alpaca.get_historical_stock_bars.assert_not_awaited()
        with self.factory() as session:
            stored_expired = session.get(PredictionSnapshotORM, expired.id)
            self.assertEqual((stored_expired.status, stored_expired.accuracy_outcome), ("missed", "missed"))
            self.assertIsNone(stored_expired.price_at_horizon)
            self.assertIsNone(stored_expired.in_range)
            self.assertEqual(stored_expired.exit_window_status, "missed")
            self.assertEqual(session.get(PredictionSnapshotORM, recent.id).status, "pending")
        with patch("app.services.scanner.time.monotonic", return_value=401):
            self.assertEqual(self.refresh(service), 0)
        self.assertEqual(service.alpaca.get_price_on_or_after_timestamp.await_count, 3)

    def check_failure_then_next_row_and_retry(self, stage):
        failed = self.prediction()
        next_row = self.prediction(ticker="NEXT", generated_at=self.generated + timedelta(seconds=1),
                                   decision_role="shadow", policy_id="weekly_probability")
        self.insert(failed, next_row)
        service = self.service()
        primary = service.alpaca.get_price_on_or_after_timestamp
        path = service.alpaca.get_historical_stock_bars
        if stage == "horizon":
            primary.side_effect = TimeoutError("isolated horizon unavailable")
        else:
            async def failing_path(_ticker, *, timeframe, **_kwargs):
                if stage == "hourly" or timeframe == "1Min":
                    raise TimeoutError("isolated path unavailable")
                return [{"t": self.generated.isoformat(), "h": 149, "l": 143.5}]
            path.side_effect = failing_path
        with patch("app.services.scanner.time.monotonic", return_value=100):
            self.assertEqual(self.refresh(service), 0)
            primary.side_effect = None
            path.side_effect = None
            self.assertEqual(self.refresh(service), 1)
        with self.factory() as session:
            stored_failed = session.get(PredictionSnapshotORM, failed.id)
            self.assertEqual(stored_failed.status, "pending")
            self.assertIsNone(stored_failed.price_at_horizon)
            self.assertEqual(stored_failed.exit_window_status, "pending")
            self.assert_identity(stored_failed, failed)
            stored_next = session.get(PredictionSnapshotORM, next_row.id)
            self.assertEqual(stored_next.status, "resolved")
            self.assert_identity(stored_next, next_row)
        with patch("app.services.scanner.time.monotonic", return_value=399):
            self.assertEqual(self.refresh(service), 0)
        with patch("app.services.scanner.time.monotonic", return_value=401):
            self.assertEqual(self.refresh(service), 1)
        with self.factory() as session:
            stored_failed = session.get(PredictionSnapshotORM, failed.id)
            self.assertEqual(stored_failed.status, "resolved")
            self.assert_identity(stored_failed, failed)

    def test_horizon_exception_defers_row_allows_next_and_retries_after_cooldown(self):
        self.check_failure_then_next_row_and_retry("horizon")

    def test_hourly_path_exception_defers_row_allows_next_and_retries_after_cooldown(self):
        self.check_failure_then_next_row_and_retry("hourly")

    def test_finer_path_exception_defers_row_allows_next_and_retries_after_cooldown(self):
        self.check_failure_then_next_row_and_retry("finer")

    def test_report_deadline_is_separate_from_selection_horizon_and_expiry(self):
        row = self.prediction()
        self.insert(row)
        target = self.generated + timedelta(days=7)
        self.assertLess(target, row.resolve_due_at)
        selected = self.repo.list_due_prediction_evaluations(observed_at=target, limit=1)
        self.assertEqual([item.snapshot_id for item in selected], [row.id])
        self.assertEqual(selected[0].target_at, target)
        self.assertEqual(row.resolve_due_at, self.generated + timedelta(days=8))
        self.assertEqual(selected[0].expires_at, self.generated + timedelta(days=21))


if __name__ == "__main__":
    unittest.main()
