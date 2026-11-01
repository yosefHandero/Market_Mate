"""Isolated acceptance of prediction fairness without extra provider requests.

All outcomes below are synthetic fixtures. The real selector, resolver, expiry,
retry deferrals, exit mathematics and persistence run against disposable SQLite.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.scan import EvidenceCampaignORM, PredictionSnapshotORM
import app.services.repository as repository_module
from app.services.db_integrity import install_prediction_immutability_trigger, record_hash_for_snapshot
from app.services.scanner import ScannerService


class PredictionQueueFairnessTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="prediction-fairness-")
        self.addCleanup(directory.cleanup)
        self.engine = create_engine(f"sqlite:///{(Path(directory.name) / 'fixture.db').as_posix()}")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        install_prediction_immutability_trigger(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        for name, value in (("SessionLocal", self.factory), ("engine", self.engine)):
            item = patch.object(repository_module, name, value)
            item.start()
            self.addCleanup(item.stop)
        self.repo = repository_module.ScanRepository()
        self.now = datetime(2026, 10, 30, 20, tzinfo=timezone.utc)
        self.current_generated = self.now.replace(tzinfo=None) - timedelta(days=8)
        self.old_generated = self.now.replace(tzinfo=None) - timedelta(days=40)
        self.originals = {}
        self.active = "fixture-active"
        self.insert(EvidenceCampaignORM(campaign_id=self.active, started_at=self.current_generated, status="active"))

    def insert(self, *rows):
        with self.factory() as session:
            session.add_all(rows)
            session.commit()

    def prediction(self, name, *, lane="production", offset=0, **changes):
        values = dict(
            run_id=f"fixture-{name}", ticker=name, asset_type="stock", signal="BUY",
            entry_price=145.71, range_low=130.2257, range_high=152.339,
            horizon="1w", generated_at=(self.old_generated if lane == "older" else self.current_generated) + timedelta(seconds=offset),
            status="pending", estimated_exit_price=148.62, invalidation_level=144.25,
            exit_window_status="pending", campaign_id="fixture-old" if lane == "older" else self.active,
            policy_id="weekly_probability" if lane == "shadow" else "hybrid_legacy",
            policy_version="fixture-v1", decision_role="shadow" if lane == "shadow" else "production",
            decision_fingerprint=f"fixture-policy-{lane}", learned_artifacts_fingerprint="fixture-learned",
            config_fingerprint="fixture-config", selection_status="selected",
        )
        values.update(changes)
        values.setdefault("resolve_due_at", values["generated_at"] + timedelta(days=8))
        values["record_hash"] = record_hash_for_snapshot(values)
        row = PredictionSnapshotORM(**values)
        self.originals[name] = values
        return row

    def service(self, *, ambiguous_hours=0):
        service = ScannerService.__new__(ScannerService)
        service.repo = self.repo
        service._analyze_semaphore = asyncio.Semaphore(1)
        service.alpaca = Mock()
        service.alpaca.get_price_on_or_after_timestamp = AsyncMock(return_value=147.0)
        service.alpaca.get_crypto_price_on_or_after_timestamp = AsyncMock(return_value=147.0)

        async def bars(_ticker, *, timeframe, start, **_kwargs):
            if timeframe == "1Hour":
                return [{"t": (start + timedelta(hours=index)).isoformat(), "h": 149, "l": 143.5 if ambiguous_hours else 145}
                        for index in range(ambiguous_hours or 1)]
            return [{"h": 148.8, "l": 145}, {"h": 147, "l": 143.9}]

        service.alpaca.get_historical_stock_bars = AsyncMock(side_effect=bars)
        service.alpaca.get_historical_crypto_bars = AsyncMock(side_effect=bars)
        return service

    def refresh(self, service, *, limit=8):
        return asyncio.run(service._refresh_due_prediction_snapshots(self.now, limit=limit))

    def calls(self, service):
        return sum(getattr(service.alpaca, name).await_count for name in (
            "get_price_on_or_after_timestamp", "get_crypto_price_on_or_after_timestamp",
            "get_historical_stock_bars", "get_historical_crypto_bars",
        ))

    def rows(self):
        with self.factory() as session:
            return {row.ticker: row for row in session.scalars(select(PredictionSnapshotORM))}

    def lane(self, row):
        if row.campaign_id != self.active:
            return "older"
        return "shadow" if row.decision_role == "shadow" else "production"

    def assert_identity(self, row):
        original = self.originals[row.ticker]
        for column in ("campaign_id", "policy_id", "policy_version", "decision_role", "decision_fingerprint",
                       "learned_artifacts_fingerprint", "config_fingerprint", "record_hash", "resolve_due_at"):
            self.assertEqual(getattr(row, column), original[column], column)
        self.assertEqual(row.record_hash, record_hash_for_snapshot({column.name: getattr(row, column.name)
                                                                  for column in PredictionSnapshotORM.__table__.columns}))

    def test_sustained_backlog_gives_every_lane_price_outcomes_at_unchanged_request_ceiling(self):
        self.insert(*(self.prediction(f"O{index}", lane="older", offset=index) for index in range(40)),
                    *(self.prediction(f"P{index}", offset=index) for index in range(16)),
                    *(self.prediction(f"S{index}", lane="shadow", offset=index) for index in range(16)))
        service = self.service(ambiguous_hours=3)
        seen = set()
        for batch in range(4):
            # Add old work faster than the resolver can drain it. An oldest-first
            # global queue cannot reach current production or shadow in this run.
            self.insert(*(self.prediction(f"EXTRA{batch}-{index}", lane="older", offset=100 + batch*16 + index)
                          for index in range(16)))
            before_calls = self.calls(service)
            with patch.object(self.repo, "list_due_prediction_evaluations", wraps=self.repo.list_due_prediction_evaluations) as selected:
                self.assertEqual(self.refresh(service), 8)
            self.assertEqual(selected.call_args.kwargs["limit"], 8)
            resolved = {name: row for name, row in self.rows().items() if row.status == "resolved"}
            new = {name: row for name, row in resolved.items() if name not in seen}
            self.assertEqual(len(new), 8)
            self.assertEqual(set(map(self.lane, new.values())), {"production", "shadow", "older"})
            # Existing ceiling: 1 horizon + 1 hourly + at most 3 finer lookups.
            self.assertEqual(self.calls(service)-before_calls, 8*5)
            for row in new.values():
                self.assertEqual((row.price_at_horizon, row.accuracy_outcome), (147.0, "in_range"))
                self.assertEqual(row.exit_window_status, "resolved")
                self.assertIsNotNone(row.hold_return_pct)
                self.assertIsNotNone(row.protected_return_pct)
                self.assert_identity(row)
            seen.update(new)
        self.assertEqual(len(seen), 32)
        self.assertTrue(any(row.status == "pending" and self.lane(row) == "older" for row in self.rows().values()))

    def test_single_slot_batches_rotate_all_lanes_instead_of_starving_shadow_and_older(self):
        self.insert(*(self.prediction(f"P{index}", offset=index) for index in range(5)),
                    *(self.prediction(f"S{index}", lane="shadow", offset=index) for index in range(5)),
                    *(self.prediction(f"O{index}", lane="older", offset=index) for index in range(5)))
        service = self.service()
        seen = set()
        for _ in range(3):
            self.assertEqual(self.refresh(service, limit=1), 1)
            seen.update(self.lane(row) for row in self.rows().values() if row.status == "resolved")
        self.assertEqual(seen, {"production", "shadow", "older"})
        self.assertEqual(self.calls(service), 6)

    def test_failing_current_row_does_not_refill_or_block_healthy_lanes_and_retries_after_cooldown(self):
        failed = self.prediction("FAIL")
        self.insert(failed, self.prediction("PROD2", offset=1), self.prediction("SHADOW", lane="shadow"),
                    self.prediction("SHADOW2", lane="shadow", offset=1), self.prediction("OLD", lane="older"),
                    self.prediction("OLD2", lane="older", offset=1))
        service = self.service()

        async def price(ticker, *_args, **_kwargs):
            if ticker == "FAIL":
                raise TimeoutError("fixture retryable horizon response")
            return 147.0

        service.alpaca.get_price_on_or_after_timestamp.side_effect = price
        with patch("app.services.scanner.time.monotonic", return_value=100):
            self.assertEqual(self.refresh(service, limit=3), 2)
            self.assertEqual(service.alpaca.get_price_on_or_after_timestamp.await_count, 3)
            self.assertEqual(self.calls(service), 5)
            self.assertEqual(self.rows()["FAIL"].status, "pending")
            self.assertEqual(self.refresh(service, limit=3), 3)
            self.assertEqual(service.alpaca.get_price_on_or_after_timestamp.await_count, 6)
        with patch("app.services.scanner.time.monotonic", return_value=399):
            self.assertEqual(self.refresh(service, limit=3), 0)
        service.alpaca.get_price_on_or_after_timestamp.side_effect = None
        with patch("app.services.scanner.time.monotonic", return_value=401):
            self.assertEqual(self.refresh(service, limit=3), 1)
        for row in self.rows().values():
            self.assertEqual(row.status, "resolved")
            self.assert_identity(row)

    def test_missing_price_errors_and_unavailable_exit_path_keep_distinct_outcomes(self):
        self.insert(self.prediction("MISSING"), self.prediction("HORIZONERR", offset=1),
                    self.prediction("EMPTYEXIT", offset=2), self.prediction("PATHERR", offset=3),
                    self.prediction("EXPIRED", lane="older"), self.prediction("HEALTHY", lane="shadow"))
        service = self.service()

        async def price(ticker, *_args, **_kwargs):
            if ticker in {"MISSING", "EXPIRED"}:
                return None
            if ticker == "HORIZONERR":
                raise TimeoutError("fixture horizon timeout")
            return 147.0

        async def path(ticker, **_kwargs):
            if ticker == "EMPTYEXIT":
                return []
            if ticker == "PATHERR":
                raise TimeoutError("fixture exit path timeout")
            return [{"h": 149, "l": 145}]

        service.alpaca.get_price_on_or_after_timestamp.side_effect = price
        service.alpaca.get_historical_stock_bars.side_effect = path
        with patch("app.services.scanner.time.monotonic", return_value=100):
            self.assertEqual(self.refresh(service), 3)
            self.assertEqual(service.alpaca.get_price_on_or_after_timestamp.await_count, 6)
            self.assertEqual(self.calls(service), 9)
            rows = self.rows()
            self.assertEqual((rows["EXPIRED"].status, rows["EXPIRED"].accuracy_outcome, rows["EXPIRED"].price_at_horizon), ("missed", "missed", None))
            self.assertIsNone(rows["EXPIRED"].in_range)
            self.assertEqual(rows["EXPIRED"].exit_window_status, "missed")
            for name in ("MISSING", "HORIZONERR", "PATHERR"):
                self.assertEqual(rows[name].status, "pending")
                self.assertIsNone(rows[name].price_at_horizon)
                self.assertIsNone(rows[name].evaluated_at)
            self.assertEqual((rows["EMPTYEXIT"].status, rows["EMPTYEXIT"].price_at_horizon), ("resolved", 147.0))
            self.assertEqual(rows["EMPTYEXIT"].exit_window_status, "unresolved")
            self.assertIsNone(rows["EMPTYEXIT"].protected_return_pct)
            self.assertIsNone(rows["EMPTYEXIT"].hold_return_pct)
            self.assertEqual(self.refresh(service), 0)
            self.assertEqual(self.calls(service), 9)
        service.alpaca.get_price_on_or_after_timestamp.side_effect = None
        service.alpaca.get_historical_stock_bars.side_effect = None
        service.alpaca.get_historical_stock_bars.return_value = [{"h": 149, "l": 145}]
        with patch("app.services.scanner.time.monotonic", return_value=401):
            self.assertEqual(self.refresh(service), 3)
        for row in self.rows().values():
            self.assert_identity(row)

    def test_not_due_and_excluded_rows_never_spend_provider_requests(self):
        not_due = self.prediction("FUTURE", generated_at=self.now.replace(tzinfo=None)-timedelta(days=6))
        excluded = self.prediction("EXCLUDED")
        healthy = self.prediction("HEALTHY", lane="shadow")
        self.insert(not_due, excluded, healthy)
        service = self.service()
        service._defer_outcome("prediction", excluded.id)
        self.assertEqual(self.refresh(service), 1)
        self.assertEqual(self.calls(service), 2)
        self.assertEqual(service.alpaca.get_price_on_or_after_timestamp.await_args.args[0], "HEALTHY")
        self.assertEqual(self.rows()["FUTURE"].status, "pending")
        self.assertEqual(self.rows()["EXCLUDED"].status, "pending")

    def test_empty_lanes_lend_unused_capacity_without_exceeding_batch_limit(self):
        self.insert(*(self.prediction(f"P{index}", offset=index) for index in range(12)))
        service = self.service()
        self.assertEqual(self.refresh(service, limit=8), 8)
        self.assertEqual(self.calls(service), 16)
        self.assertEqual(sum(row.status == "resolved" for row in self.rows().values()), 8)
        self.assertEqual(sum(row.status == "pending" for row in self.rows().values()), 4)

    def test_no_active_campaign_keeps_legacy_fifo_compatible(self):
        with self.factory() as session:
            session.get(EvidenceCampaignORM, self.active).status = "closed"
            session.commit()
        self.insert(self.prediction("NEW"), self.prediction("LEGACY", lane="older", campaign_id=None, decision_role=None))
        service = self.service()
        self.assertEqual(self.refresh(service, limit=1), 1)
        self.assertEqual(service.alpaca.get_price_on_or_after_timestamp.await_args.args[0], "LEGACY")


if __name__ == "__main__":
    unittest.main()
