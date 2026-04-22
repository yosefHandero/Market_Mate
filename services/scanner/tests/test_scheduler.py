import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.services.scheduler import SchedulerService


class SchedulerServiceLoopTests(unittest.TestCase):
    def test_run_forever_runs_due_scan_and_releases_lease(self) -> None:
        scanner_service = Mock()
        scanner_service.refresh_due_signal_outcomes = AsyncMock(return_value=2)
        scanner_service.run_scan = AsyncMock(return_value=None)

        repository = Mock()
        repository.acquire_lease.return_value = True
        repository.due_for_run.return_value = True

        service = SchedulerService(scanner_service=scanner_service, repository=repository)

        with patch(
            "app.services.scheduler.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(service.run_forever())

        instance_id = service.settings.app_instance_id
        repository.acquire_lease.assert_called_once_with(instance_id)
        repository.heartbeat.assert_called_once_with(instance_id)
        scanner_service.refresh_due_signal_outcomes.assert_awaited_once()
        repository.mark_run_started.assert_called_once_with(instance_id)
        scanner_service.run_scan.assert_awaited_once()
        repository.mark_run_finished.assert_called_once_with(instance_id)
        repository.release_lease.assert_called_once_with(instance_id)

    def test_run_forever_records_scan_errors_before_releasing_lease(self) -> None:
        scanner_service = Mock()
        scanner_service.refresh_due_signal_outcomes = AsyncMock(return_value=0)
        scanner_service.run_scan = AsyncMock(side_effect=RuntimeError("scan failed"))

        repository = Mock()
        repository.acquire_lease.return_value = True
        repository.due_for_run.return_value = True

        service = SchedulerService(scanner_service=scanner_service, repository=repository)

        with patch(
            "app.services.scheduler.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(service.run_forever())

        instance_id = service.settings.app_instance_id
        repository.mark_run_started.assert_called_once_with(instance_id)
        repository.mark_run_finished.assert_called_once_with(instance_id, error="scan failed")
        repository.release_lease.assert_called_once_with(instance_id)


if __name__ == "__main__":
    unittest.main()
