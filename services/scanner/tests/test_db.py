from pathlib import Path
import os
import tempfile
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from unittest.mock import patch

import app.db as db_module


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
