from pathlib import Path
import tempfile
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.db import Base, REQUIRED_TABLE_COLUMNS
from app.models import journal, scan, system  # noqa: F401


def _upgrade_temp_database(database_path: Path):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")

    return create_engine(
        f"sqlite:///{database_path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )


class MigrationParityTests(unittest.TestCase):
    def test_alembic_head_satisfies_required_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = _upgrade_temp_database(database_path)
            try:
                inspector = inspect(engine)
                missing_items: list[str] = []
                for table_name, required_columns in REQUIRED_TABLE_COLUMNS.items():
                    if not inspector.has_table(table_name):
                        missing_items.append(f"{table_name}.__missing_table__")
                        continue
                    actual_columns = {
                        column["name"]
                        for column in inspector.get_columns(table_name)
                    }
                    missing_items.extend(
                        f"{table_name}.{column_name}"
                        for column_name in required_columns
                        if column_name not in actual_columns
                    )

                self.assertEqual([], missing_items)
            finally:
                engine.dispose()

    def test_alembic_head_satisfies_orm_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = _upgrade_temp_database(database_path)
            try:
                inspector = inspect(engine)
                missing_items: list[str] = []
                for table_name, table in Base.metadata.tables.items():
                    if not inspector.has_table(table_name):
                        missing_items.append(f"{table_name}.__missing_table__")
                        continue
                    actual_columns = {
                        column["name"]
                        for column in inspector.get_columns(table_name)
                    }
                    missing_items.extend(
                        f"{table_name}.{column.name}"
                        for column in table.columns
                        if column.name not in actual_columns
                    )

                self.assertEqual([], missing_items)
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
