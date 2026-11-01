from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
import time

from app.config import get_settings
from app.errors import AppError
from app.services.scanner import ScannerService
from app.services.scan_lease import run_with_scan_lease, shared_scan_lease
from app.services.scheduler_repository import SchedulerRepository

logger = logging.getLogger(__name__)


class SchedulerService:
    _MAINTENANCE_BATCH_LIMIT = 8
    _MAINTENANCE_INTERVAL_SECONDS = 60
    def __init__(
        self,
        *,
        scanner_service: ScannerService | None = None,
        repository: SchedulerRepository | None = None,
    ) -> None:
        self.settings = get_settings()
        self.scanner_service = scanner_service or ScannerService()
        self.repository = repository or SchedulerRepository()
        self._next_maintenance_at = 0.0

    def start(self) -> bool:
        self._require_scans_allowed()
        return self.repository.set_enabled(enabled=True)

    def stop(self) -> bool:
        return self.repository.set_enabled(enabled=False)

    def running(self) -> bool:
        return self.repository.get_state().running

    def state(self):
        return self.repository.get_state()

    def _reset_missed_run_on_startup(self) -> None:
        if not self.settings.scheduler_run_missed_on_startup:
            return
        self.repository.reset_missed_run_on_startup(
            interval_seconds=self.settings.scan_interval_seconds
        )

    async def run_manual_scan(self):
        self._require_scans_allowed()
        return await run_with_scan_lease(
            self.scanner_service.run_scan, self.repository, source="manual"
        )

    def _require_scans_allowed(self) -> None:
        if self.settings.runtime_verification_mode:
            raise AppError(
                message="Scans are paused during local runtime verification.",
                status_code=503,
                code="runtime_verification_mode",
            )

    def _apply_configured_enable_state(self) -> None:
        """Allow explicitly configured automatic scans during this worker session."""
        if not self.settings.scheduler_enabled:
            return
        if self.repository.get_state().enabled:
            return
        self.repository.set_enabled(enabled=True)
        logger.info(
            "scheduler auto-enabled from SCHEDULER_ENABLED config",
            extra={"event": "scheduler_auto_enabled"},
        )

    async def run_forever(self) -> None:
        self._apply_configured_enable_state()
        self._reset_missed_run_on_startup()
        while True:
            self.repository.recover_stale_run()
            try:
                async with shared_scan_lease(self.repository, source="scheduled") as lease:
                    if time.monotonic() >= self._next_maintenance_at:
                        self._next_maintenance_at = time.monotonic() + self._MAINTENANCE_INTERVAL_SECONDS
                        await self.scanner_service.refresh_due_signal_outcomes(
                            observed_at=datetime.now(timezone.utc),
                            limit=self._MAINTENANCE_BATCH_LIMIT,
                        )
                        await self.scanner_service.refresh_due_prediction_snapshots(
                            observed_at=datetime.now(timezone.utc),
                            limit=self._MAINTENANCE_BATCH_LIMIT,
                        )
                        await self.scanner_service.close_open_positions_past_horizon(
                            observed_at=datetime.now(timezone.utc)
                        )
                    if self.repository.due_for_run():
                        await run_with_scan_lease(
                            self.scanner_service.run_scan, self.repository, source="scheduled"
                        )
                    else:
                        self.repository.clear_error(lease.owner)
            except AppError as exc:
                if exc.code != "scan_already_running":
                    logger.exception("scheduler loop failed", extra={"event": "scheduler_error"})
            except Exception:
                logger.exception("scheduler loop failed", extra={"event": "scheduler_error"})
            await asyncio.sleep(self.settings.scheduler_poll_seconds)
