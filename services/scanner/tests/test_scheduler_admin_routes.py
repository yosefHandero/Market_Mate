import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

if "yahooquery" not in sys.modules:
    yahooquery_stub = types.ModuleType("yahooquery")
    yahooquery_stub.Ticker = object
    sys.modules["yahooquery"] = yahooquery_stub

import app.main as main_module
import app.services.scheduler_repository as scheduler_repository_module
from app.dependencies import scheduler_service as global_scheduler_service


class SchedulerAdminRouteTests(unittest.TestCase):
    @contextmanager
    def _legacy_scheduler_table(self):
        with TemporaryDirectory() as temp_dir:
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
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        CREATE TABLE scheduler_state (
                            scheduler_key VARCHAR(32) PRIMARY KEY,
                            enabled BOOLEAN DEFAULT 0 NOT NULL,
                            interval_seconds INTEGER DEFAULT 300 NOT NULL,
                            lease_owner VARCHAR(64),
                            lease_expires_at DATETIME,
                            next_run_at DATETIME,
                            last_run_started_at DATETIME,
                            last_run_finished_at DATETIME,
                            last_error TEXT,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                )
            try:
                with patch.object(scheduler_repository_module, "SessionLocal", SessionLocal):
                    yield SessionLocal
            finally:
                engine.dispose()

    def setUp(self) -> None:
        self.original_admin_token = main_module.settings.admin_api_token
        main_module.settings.admin_api_token = "secret-token"
        self.client = TestClient(main_module.app)

    def tearDown(self) -> None:
        main_module.settings.admin_api_token = self.original_admin_token

    def test_start_scheduler_route_calls_scheduler_service(self) -> None:
        with patch.object(global_scheduler_service, "start", Mock(return_value=True)) as start_mock:
            response = self.client.post(
                "/scan/scheduler/start",
                headers={"Authorization": "Bearer secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"started": True})
        start_mock.assert_called_once_with()

    def test_stop_scheduler_route_reports_success_after_service_call(self) -> None:
        with patch.object(global_scheduler_service, "stop", Mock(return_value=False)) as stop_mock:
            response = self.client.post(
                "/scan/scheduler/stop",
                headers={"Authorization": "Bearer secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"stopped": True})
        stop_mock.assert_called_once_with()

    def test_start_and_stop_scheduler_routes_work_with_legacy_scheduler_table(self) -> None:
        with self._legacy_scheduler_table() as SessionLocal:
            start_response = self.client.post(
                "/scan/scheduler/start",
                headers={"Authorization": "Bearer secret-token"},
            )
            stop_response = self.client.post(
                "/scan/scheduler/stop",
                headers={"Authorization": "Bearer secret-token"},
            )

            with SessionLocal() as session:
                row = session.execute(
                    text(
                        """
                        SELECT enabled, lease_owner, lease_expires_at
                        FROM scheduler_state
                        WHERE scheduler_key = 'scanner'
                        """
                    )
                ).mappings().one()

        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(start_response.json(), {"started": True})
        self.assertEqual(stop_response.status_code, 200)
        self.assertEqual(stop_response.json(), {"stopped": True})
        self.assertFalse(row["enabled"])
        self.assertIsNone(row["lease_owner"])
        self.assertIsNone(row["lease_expires_at"])


if __name__ == "__main__":
    unittest.main()
