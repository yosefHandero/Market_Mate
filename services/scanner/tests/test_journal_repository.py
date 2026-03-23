from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.journal import JournalEntryORM
from app.schemas import JournalEntryUpdateRequest
from app.services.journal_repository import JournalRepository
import app.services.journal_repository as journal_module


class JournalRepositoryUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "journal.db"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.session_local = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            future=True,
        )
        self.session_patcher = patch.object(
            journal_module,
            "SessionLocal",
            self.session_local,
        )
        self.session_patcher.start()
        self.repo = JournalRepository()

    def tearDown(self) -> None:
        self.session_patcher.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _create_entry(self) -> int:
        with self.session_local() as session:
            row = JournalEntryORM(
                ticker="AAPL",
                run_id="run-1",
                decision="took",
                entry_price=100.0,
                exit_price=105.0,
                pnl_pct=5.0,
                signal_label="strong",
                score=88.0,
                news_source="marketaux",
                notes="Initial note",
                created_at=datetime.now(timezone.utc),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id

    def test_partial_update_preserves_pnl_when_omitted(self) -> None:
        entry_id = self._create_entry()

        updated = self.repo.update_entry(
            entry_id,
            JournalEntryUpdateRequest(notes="Updated note only"),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.pnl_pct, 5.0)
        self.assertEqual(updated.notes, "Updated note only")

    def test_partial_update_can_clear_exit_and_pnl_explicitly(self) -> None:
        entry_id = self._create_entry()

        updated = self.repo.update_entry(
            entry_id,
            JournalEntryUpdateRequest(exit_price=None, pnl_pct=None),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertIsNone(updated.exit_price)
        self.assertIsNone(updated.pnl_pct)


if __name__ == "__main__":
    unittest.main()
