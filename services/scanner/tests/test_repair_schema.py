from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import app.db as db_module
import scripts.repair_schema as repair_schema


def _sqlite_url(database_path: Path) -> str:
    return f"sqlite:///{database_path.resolve().as_posix()}"


def _run_repair_schema(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = repair_schema.main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _upgrade_to_head(database_path: Path) -> None:
    config = Config(str(repair_schema.SCANNER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(repair_schema.SCANNER_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", _sqlite_url(database_path))
    command.upgrade(config, "head")


def _schema_status(database_path: Path) -> db_module.SchemaStatus:
    engine = create_engine(
        _sqlite_url(database_path),
        future=True,
        connect_args={"check_same_thread": False},
    )
    previous_engine = db_module.engine
    db_module.engine = engine
    try:
        return db_module.get_schema_status()
    finally:
        db_module.engine = previous_engine
        engine.dispose()


class RepairSchemaScriptTests(unittest.TestCase):
    def test_repair_schema_dry_run_does_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                _sqlite_url(database_path),
                future=True,
                connect_args={"check_same_thread": False},
            )
            try:
                with engine.begin() as connection:
                    connection.execute(text("CREATE TABLE scan_runs (run_id VARCHAR(64) PRIMARY KEY)"))

                before_columns = {
                    column["name"]
                    for column in inspect(engine).get_columns("scan_runs")
                }
            finally:
                engine.dispose()

            exit_code, stdout, stderr = _run_repair_schema(["--database-url", _sqlite_url(database_path)])

            engine = create_engine(
                _sqlite_url(database_path),
                future=True,
                connect_args={"check_same_thread": False},
            )
            try:
                after_columns = {
                    column["name"]
                    for column in inspect(engine).get_columns("scan_runs")
                }
                table_names = set(inspect(engine).get_table_names())
            finally:
                engine.dispose()

            self.assertEqual(0, exit_code, stderr)
            self.assertIn("Mode: dry-run", stdout)
            self.assertIn("Alembic upgrade head run: no", stdout)
            self.assertEqual(before_columns, after_columns)
            self.assertNotIn("strategy_variant", after_columns)
            self.assertNotIn("alembic_version", table_names)
            self.assertEqual([], list(database_path.parent.glob("scanner.db.*.bak")))

    def test_repair_schema_apply_creates_backup_and_repairs_temp_db(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            _upgrade_to_head(database_path)

            engine = create_engine(
                _sqlite_url(database_path),
                future=True,
                connect_args={"check_same_thread": False},
            )
            try:
                with engine.begin() as connection:
                    connection.execute(text("DROP TABLE paper_loop_breaker"))
                self.assertFalse(inspect(engine).has_table("paper_loop_breaker"))
            finally:
                engine.dispose()

            exit_code, stdout, stderr = _run_repair_schema(
                ["--database-url", _sqlite_url(database_path), "--yes-repair"]
            )

            backups = list(database_path.parent.glob("scanner.db.*.bak"))
            status = _schema_status(database_path)

            self.assertEqual(0, exit_code, stderr)
            self.assertEqual(1, len(backups))
            self.assertTrue(status.ok, status.missing_items)
            self.assertIn("Alembic upgrade head run: yes", stdout)
            self.assertIn("paper_loop_breaker.__created_table__", stdout)
            self.assertIn("Schema after: OK", stdout)

    def test_repair_schema_refuses_non_sqlite_url(self) -> None:
        exit_code, stdout, stderr = _run_repair_schema(
            ["--database-url", "postgresql://example", "--yes-repair"]
        )

        self.assertNotEqual(0, exit_code)
        self.assertEqual("", stdout)
        self.assertIn("only sqlite:/// database URLs are supported", stderr)

    def test_repair_schema_refuses_production_without_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            database_path.touch()

            with patch.dict(os.environ, {"APP_ENV": "production"}, clear=False):
                exit_code, stdout, stderr = _run_repair_schema(
                    ["--database-url", _sqlite_url(database_path), "--yes-repair"]
                )

            self.assertNotEqual(0, exit_code)
            self.assertEqual("", stdout)
            self.assertIn("APP_ENV=production", stderr)
            self.assertEqual([], list(database_path.parent.glob("scanner.db.*.bak")))

    def test_repair_schema_restores_repair_env_var(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            _upgrade_to_head(database_path)

            with patch.dict(os.environ, {"SCANNER_SCHEMA_REPAIR_ALLOW": "preserve-me"}, clear=False):
                exit_code, _stdout, stderr = _run_repair_schema(
                    ["--database-url", _sqlite_url(database_path), "--apply"]
                )
                restored_value = os.environ.get("SCANNER_SCHEMA_REPAIR_ALLOW")

            self.assertEqual(0, exit_code, stderr)
            self.assertEqual("preserve-me", restored_value)


if __name__ == "__main__":
    unittest.main()
