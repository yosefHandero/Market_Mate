"""Tests for the expected scan-window ledger."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.scan import ScanWindowORM
from app.services.scan_windows import ScanWindowService, expected_windows_for_day


class ScanWindowLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        database_path = Path(self._temp_dir.name) / "windows.db"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            future=True,
        )
        Base.metadata.create_all(self.engine)
        self.service = ScanWindowService(session_factory=self.SessionLocal)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_ensure_upcoming_windows_creates_rows(self) -> None:
        created = self.service.ensure_upcoming_windows(lookback_days=2, lookahead_days=1)
        self.assertGreater(created, 0)
        rows = self.service.list_recent(limit=50)
        self.assertGreaterEqual(len(rows), created)
        again = self.service.ensure_upcoming_windows(lookback_days=2, lookahead_days=1)
        self.assertEqual(again, 0)

    def test_sweep_marks_past_pending_as_missed(self) -> None:
        past_start = datetime.now(timezone.utc) - timedelta(days=2)
        past_end = past_start + timedelta(hours=1)
        with self.SessionLocal() as session:
            session.add(
                ScanWindowORM(
                    window_name="weekday_market",
                    expected_start=past_start.replace(tzinfo=None),
                    expected_end=past_end.replace(tzinfo=None),
                    status="pending",
                    created_at=past_start.replace(tzinfo=None),
                    updated_at=past_start.replace(tzinfo=None),
                )
            )
            session.commit()
        marked = self.service.sweep_missed(grace_minutes=0)
        self.assertEqual(marked, 1)
        self.assertEqual(self.service.missed_count(lookback_days=14), 1)

    def test_mark_executed_updates_current_window(self) -> None:
        now = datetime.now(timezone.utc)
        with self.SessionLocal() as session:
            session.add(
                ScanWindowORM(
                    window_name="weekday_market",
                    expected_start=(now - timedelta(minutes=30)).replace(tzinfo=None),
                    expected_end=(now + timedelta(minutes=30)).replace(tzinfo=None),
                    status="pending",
                    created_at=now.replace(tzinfo=None),
                    updated_at=now.replace(tzinfo=None),
                )
            )
            session.commit()
        updated = self.service.mark_executed(scan_run_id="run-123", at=now)
        self.assertEqual(updated, 1)
        recent = self.service.list_recent(limit=1)
        self.assertEqual(recent[0].status, "executed")
        self.assertEqual(recent[0].scan_run_id, "run-123")

    def test_expected_windows_for_weekday(self) -> None:
        monday = datetime(2026, 7, 27).date()
        specs = expected_windows_for_day(monday)
        names = {spec.name for spec, _, _ in specs}
        self.assertIn("weekday_market", names)
        self.assertIn("daily_overnight", names)
        self.assertNotIn("weekend_crypto", names)


if __name__ == "__main__":
    unittest.main()
