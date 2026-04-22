import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.scheduler_repository as scheduler_repository_module
from app.db import Base
from app.services.scheduler_repository import SchedulerRepository


class SchedulerRepositoryTests(unittest.TestCase):
    def test_due_for_run_handles_sqlite_naive_datetimes_without_timezone_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                repo = SchedulerRepository()
                with patch.object(scheduler_repository_module, "SessionLocal", SessionLocal):
                    self.assertTrue(repo.set_enabled(enabled=True))
                    self.assertTrue(repo.acquire_lease("scanner-test"))
                    repo.heartbeat("scanner-test")
                    self.assertTrue(repo.due_for_run())
                    state = repo.get_state()
            finally:
                engine.dispose()

        self.assertTrue(state.running)
        self.assertIsNotNone(state.next_run_at)


if __name__ == "__main__":
    unittest.main()
