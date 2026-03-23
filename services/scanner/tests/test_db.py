from pathlib import Path
import tempfile
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


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

            scan_result_columns = {column["name"] for column in inspector.get_columns("scan_results")}
            execution_audit_columns = {column["name"] for column in inspector.get_columns("execution_audits")}

            self.assertIn("decision_signal", scan_result_columns)
            self.assertIn("provider_status", scan_result_columns)
            self.assertIn("idempotency_key", execution_audit_columns)
            self.assertIn("lifecycle_status", execution_audit_columns)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
