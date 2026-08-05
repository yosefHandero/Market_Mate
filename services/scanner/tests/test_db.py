from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

import app.db as db_module
import app.services.repository as repository_module
from app.schemas import ScanResult, ScanRun
from app.services.repository import ScanRepository


def _scan_run(run_id: str) -> ScanRun:
    now = datetime.now(timezone.utc)
    return ScanRun(
        run_id=run_id,
        created_at=now,
        market_status="neutral",
        scan_count=1,
        watchlist_size=1,
        alerts_sent=0,
        results=[
            ScanResult(
                ticker="AAPL",
                asset_type="stock",
                score=61.0,
                raw_score=61.0,
                calibrated_confidence=61.0,
                decision_signal="BUY",
                explanation="Transient lock fixture",
                price=100.0,
                price_change_pct=1.0,
                relative_volume=1.0,
                sentiment_score=0.1,
                filing_flag=False,
                breakout_flag=True,
                market_status="neutral",
                sector_strength_score=0.5,
                relative_strength_pct=0.2,
                gate_passed=True,
                created_at=now,
            )
        ],
    )


class SchemaMigrationTests(unittest.TestCase):
    def test_alembic_upgrade_creates_expected_backend_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

            command.upgrade(config, "head")

            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            inspector = inspect(engine)
            self.assertTrue(inspector.has_table("scan_results"))
            self.assertTrue(inspector.has_table("execution_audits"))
            self.assertTrue(inspector.has_table("scheduler_state"))
            self.assertTrue(inspector.has_table("paper_loop_breaker"))

            scan_result_columns = {column["name"] for column in inspector.get_columns("scan_results")}
            execution_audit_columns = {column["name"] for column in inspector.get_columns("execution_audits")}

            self.assertIn("decision_signal", scan_result_columns)
            self.assertIn("provider_status", scan_result_columns)
            self.assertIn("idempotency_key", execution_audit_columns)
            self.assertIn("lifecycle_status", execution_audit_columns)
            engine.dispose()

    def test_sqlite_engine_enables_wal_and_busy_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = db_module.create_scanner_engine(
                f"sqlite:///{database_path.as_posix()}",
                busy_timeout_ms=1234,
            )
            try:
                with engine.connect() as connection:
                    journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
                    busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()

                self.assertEqual(str(journal_mode).lower(), "wal")
                self.assertEqual(busy_timeout, 1234)
            finally:
                engine.dispose()

    def test_scan_save_retries_after_real_transient_sqlite_write_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            # Short busy timeout so the first blocked write fails quickly and
            # save_run's retry loop is exercised instead of waiting on SQLite.
            engine = db_module.create_scanner_engine(
                f"sqlite:///{database_path.as_posix()}",
                busy_timeout_ms=25,
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            db_module.Base.metadata.create_all(engine)
            locker = engine.raw_connection()
            first_lock_failure = Event()
            result: dict[str, object] = {}
            try:
                locker.execute("BEGIN IMMEDIATE")

                def save_run() -> None:
                    try:
                        repo = ScanRepository()
                        with patch.object(repository_module, "SessionLocal", SessionLocal):
                            original_save_once = repo._save_run_once

                            def _tracked_save_once(run: ScanRun) -> None:
                                try:
                                    original_save_once(run)
                                except OperationalError as exc:
                                    # Publish only after a real lock failure so
                                    # the main thread cannot release early and
                                    # let the first attempt succeed (flaky under load).
                                    if repository_module._is_transient_sqlite_lock(exc):
                                        first_lock_failure.set()
                                    raise

                            with patch.object(
                                repo, "_save_run_once", side_effect=_tracked_save_once
                            ) as save_once:
                                repo.save_run(_scan_run("locked-run"))
                                result["attempts"] = save_once.call_count
                        result["ok"] = True
                    except Exception as exc:
                        result["error"] = exc

                thread = Thread(target=save_run)
                thread.start()
                self.assertTrue(
                    first_lock_failure.wait(timeout=2.0),
                    "save_run never hit a sqlite write lock while BEGIN IMMEDIATE was held",
                )
                locker.commit()
                thread.join(timeout=5)

                self.assertFalse(thread.is_alive())
                error = result.get("error")
                if isinstance(error, Exception):
                    raise error
                self.assertTrue(result.get("ok"))
                self.assertGreaterEqual(result.get("attempts", 0), 2)
                with SessionLocal() as session:
                    saved_count = session.execute(
                        text("SELECT COUNT(*) FROM scan_runs WHERE run_id = :run_id"),
                        {"run_id": "locked-run"},
                    ).scalar_one()
                self.assertEqual(saved_count, 1)
            finally:
                try:
                    locker.rollback()
                except Exception:
                    pass
                locker.close()
                engine.dispose()

    def test_scan_save_does_not_retry_non_lock_operational_error(self) -> None:
        repo = ScanRepository()
        error = OperationalError(
            "INSERT INTO scan_runs",
            {},
            Exception("disk I/O error"),
        )

        with (
            patch.object(repo, "_save_run_once", side_effect=error) as save_once,
            patch.object(repository_module.time, "sleep") as sleep,
        ):
            with self.assertRaises(OperationalError) as raised:
                repo.save_run(_scan_run("non-lock-error"))

        self.assertIs(raised.exception, error)
        self.assertEqual(save_once.call_count, 1)
        sleep.assert_not_called()

    def test_scan_save_retry_exhaustion_raises_final_lock_error(self) -> None:
        repo = ScanRepository()
        errors = [
            OperationalError("INSERT INTO scan_runs", {}, Exception("database is locked: first")),
            OperationalError("INSERT INTO scan_runs", {}, Exception("database is locked: second")),
            OperationalError("INSERT INTO scan_runs", {}, Exception("database is locked: final")),
        ]

        with (
            patch.object(repo, "_save_run_once", side_effect=errors) as save_once,
            patch.object(repository_module.time, "sleep") as sleep,
        ):
            with self.assertRaises(OperationalError) as raised:
                repo.save_run(_scan_run("exhausted-lock"))

        self.assertIs(raised.exception, errors[-1])
        self.assertEqual(save_once.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_apply_required_schema_patches_refuses_without_repair_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            try:
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop(db_module.SCANNER_SCHEMA_REPAIR_ALLOW_ENV, None)
                    with patch.object(db_module, "engine", engine):
                        with self.assertRaisesRegex(RuntimeError, "SCANNER_SCHEMA_REPAIR_ALLOW=1"):
                            db_module.apply_required_schema_patches()

                inspector = inspect(engine)
                self.assertFalse(inspector.has_table("scan_runs"))
            finally:
                engine.dispose()

    def test_get_schema_status_reports_missing_items_without_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text("CREATE TABLE scan_runs (run_id VARCHAR(64) PRIMARY KEY)")
                    )

                inspector = inspect(engine)
                before_columns = {
                    column["name"]
                    for column in inspector.get_columns("scan_runs")
                }

                with patch.object(db_module, "engine", engine):
                    status = db_module.get_schema_status()

                inspector = inspect(engine)
                after_columns = {
                    column["name"]
                    for column in inspector.get_columns("scan_runs")
                }

                self.assertFalse(status.ok)
                self.assertIn("scan_runs.strategy_variant", status.missing_items)
                self.assertIn("scan_results.__missing_table__", status.missing_items)
                self.assertEqual(before_columns, after_columns)
                self.assertNotIn("strategy_variant", after_columns)
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
