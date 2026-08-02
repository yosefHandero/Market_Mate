from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.services.historical_bar_store as bar_store_module
from app.config import Settings
from app.db import Base
from app.models.scan import DailyBarHistoryORM
from app.services.historical_bar_store import HistoricalBarStore


def _bar(day: datetime, close: float) -> dict:
    return {
        "t": day.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
        "o": round(close - 0.2, 4),
        "h": round(close + 0.6, 4),
        "l": round(close - 0.6, 4),
        "c": round(close, 4),
        "v": 1000,
    }


class HistoricalBarStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        database_path = Path(self._tmp.name) / "bars.db"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        self._patch = patch.object(bar_store_module, "SessionLocal", self.SessionLocal)
        self._patch.start()
        self.store = HistoricalBarStore(settings=Settings())

    def tearDown(self) -> None:
        self._patch.stop()
        self.engine.dispose()
        self._tmp.cleanup()

    def test_adjustment_policy_recorded_per_asset(self) -> None:
        self.assertEqual(HistoricalBarStore.adjustment_policy_for("stock"), "split")
        self.assertEqual(HistoricalBarStore.adjustment_policy_for("crypto"), "none")

    def test_first_write_is_append_only_with_policy(self) -> None:
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = [_bar(base + timedelta(days=i), 100 + i) for i in range(5)]
        inserted, revised = self.store._persist_bars("AAA", "stock", bars, source="alpaca")
        self.assertEqual((inserted, revised), (5, 0))
        with self.SessionLocal() as session:
            rows = session.execute(select(DailyBarHistoryORM)).scalars().all()
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r.adjustment_policy == "split" for r in rows))
        self.assertTrue(all(r.revision_count == 0 for r in rows))
        self.assertTrue(all(r.revised_at is None for r in rows))

    def test_refetch_revises_drifted_bar(self) -> None:
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = [_bar(base + timedelta(days=i), 100 + i) for i in range(3)]
        self.store._persist_bars("AAA", "stock", bars, source="alpaca")

        # Simulate a split-adjusted refetch that halves prices on one date.
        drifted = list(bars)
        drifted[1] = _bar(base + timedelta(days=1), 50.5)
        inserted, revised = self.store._persist_bars("AAA", "stock", drifted, source="polygon")
        self.assertEqual(inserted, 0)
        self.assertEqual(revised, 1)
        with self.SessionLocal() as session:
            row = session.execute(
                select(DailyBarHistoryORM).where(
                    DailyBarHistoryORM.bar_date == (base + timedelta(days=1)).date().isoformat()
                )
            ).scalars().one()
        self.assertEqual(row.revision_count, 1)
        self.assertIsNotNone(row.revised_at)
        self.assertEqual(row.source, "polygon")

    def test_quality_check_flags_zero_price_and_gap(self) -> None:
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # A gap of 10 days for a stock plus a zero-price bar.
        bars = [
            _bar(base, 100),
            _bar(base + timedelta(days=1), 101),
            _bar(base + timedelta(days=11), 102),
        ]
        bars.append({"t": (base + timedelta(days=12)).isoformat(), "o": 0, "h": 0, "l": 0, "c": 0, "v": 0})
        self.store._persist_bars("AAA", "stock", bars, source="alpaca")
        issues = self.store.quality_check("AAA", asset_type="stock")
        joined = " ".join(issues)
        self.assertIn("session gap", joined)
        self.assertIn("non-positive", joined)


if __name__ == "__main__":
    unittest.main()
