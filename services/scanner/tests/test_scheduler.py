import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, call, patch

from app.config import get_settings
from app.services.scheduler import SchedulerService


class SchedulerServiceLoopTests(unittest.TestCase):
    def test_run_forever_runs_due_scan_and_releases_lease(self) -> None:
        scanner_service = Mock()
        scanner_service.refresh_due_signal_outcomes = AsyncMock(return_value=2)
        scanner_service.refresh_due_prediction_snapshots = AsyncMock(return_value=0)
        scanner_service.close_open_positions_past_horizon = AsyncMock(return_value=0)
        scanner_service.run_scan = AsyncMock(return_value=None)

        repository = Mock()
        repository.settings = get_settings()
        repository.acquire_lease.return_value = True
        repository.due_for_run.return_value = True

        service = SchedulerService(scanner_service=scanner_service, repository=repository)

        with patch(
            "app.services.scheduler.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(service.run_forever())

        instance_id = repository.acquire_lease.call_args.args[0]
        self.assertTrue(instance_id.startswith("scheduled-"))
        repository.acquire_lease.assert_called_once_with(instance_id, for_maintenance=True)
        scanner_service.refresh_due_signal_outcomes.assert_awaited_once()
        scanner_service.close_open_positions_past_horizon.assert_awaited_once()
        repository.mark_run_started.assert_called_once_with(instance_id)
        scanner_service.run_scan.assert_awaited_once()
        repository.mark_run_finished.assert_called_once_with(instance_id)
        repository.release_lease.assert_called_once_with(instance_id)

    def test_run_forever_records_scan_errors_before_releasing_lease(self) -> None:
        scanner_service = Mock()
        scanner_service.refresh_due_signal_outcomes = AsyncMock(return_value=0)
        scanner_service.refresh_due_prediction_snapshots = AsyncMock(return_value=0)
        scanner_service.close_open_positions_past_horizon = AsyncMock(return_value=0)
        scanner_service.run_scan = AsyncMock(side_effect=RuntimeError("scan failed"))

        repository = Mock()
        repository.settings = get_settings()
        repository.acquire_lease.return_value = True
        repository.due_for_run.return_value = True

        service = SchedulerService(scanner_service=scanner_service, repository=repository)

        with patch(
            "app.services.scheduler.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(service.run_forever())

        instance_id = repository.acquire_lease.call_args.args[0]
        repository.mark_run_started.assert_called_once_with(instance_id)
        repository.mark_run_finished.assert_called_once_with(instance_id, error="scan failed")
        repository.release_lease.assert_called_once_with(instance_id)

    def test_run_forever_does_not_double_trigger_after_crashed_run(self) -> None:
        scanner_service = Mock()
        scanner_service.refresh_due_signal_outcomes = AsyncMock(return_value=0)
        scanner_service.refresh_due_prediction_snapshots = AsyncMock(return_value=0)
        scanner_service.close_open_positions_past_horizon = AsyncMock(return_value=0)
        scanner_service.run_scan = AsyncMock(return_value=None)

        repository = Mock()
        repository.settings = get_settings()
        repository.reset_missed_run_on_startup.return_value = False
        repository.acquire_lease.return_value = True
        repository.due_for_run.return_value = False

        service = SchedulerService(scanner_service=scanner_service, repository=repository)

        with patch(
            "app.services.scheduler.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(service.run_forever())

        instance_id = repository.acquire_lease.call_args.args[0]
        repository.reset_missed_run_on_startup.assert_called_once_with(
            interval_seconds=service.settings.scan_interval_seconds
        )
        repository.acquire_lease.assert_called_once_with(instance_id, for_maintenance=True)
        repository.due_for_run.assert_called_once_with()
        repository.mark_run_started.assert_not_called()
        scanner_service.run_scan.assert_not_awaited()
        repository.release_lease.assert_called_once_with(instance_id)

    def test_run_forever_missed_startup_uses_existing_claim_flow(self) -> None:
        scanner_service = Mock()
        scanner_service.refresh_due_signal_outcomes = AsyncMock(return_value=0)
        scanner_service.refresh_due_prediction_snapshots = AsyncMock(return_value=0)
        scanner_service.close_open_positions_past_horizon = AsyncMock(return_value=0)
        scanner_service.run_scan = AsyncMock(return_value=None)

        repository = Mock()
        repository.settings = get_settings()
        repository.reset_missed_run_on_startup.return_value = True
        repository.acquire_lease.return_value = True
        repository.due_for_run.return_value = True

        service = SchedulerService(scanner_service=scanner_service, repository=repository)

        with patch(
            "app.services.scheduler.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(service.run_forever())

        instance_id = repository.acquire_lease.call_args.args[0]
        repository.reset_missed_run_on_startup.assert_called_once_with(
            interval_seconds=service.settings.scan_interval_seconds
        )
        repository.recover_stale_run.assert_called_once_with()
        repository.acquire_lease.assert_called_once_with(instance_id, for_maintenance=True)
        repository.mark_run_started.assert_called_once_with(instance_id)
        repository.mark_run_finished.assert_called_once_with(instance_id)
        repository.release_lease.assert_called_once_with(instance_id)
        scanner_service.run_scan.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
