from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import time

from app.config import get_settings
from app.services.scanner import ScannerService
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

    @asynccontextmanager
    async def _lease_heartbeat(self, instance_id: str):
        stop = asyncio.Event()
        heartbeat_interval = max(5, self.settings.scheduler_lease_seconds // 3)

        async def heartbeat_loop() -> None:
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=heartbeat_interval)
                except TimeoutError:
                    self.repository.heartbeat(instance_id)

        heartbeat_task = asyncio.create_task(heartbeat_loop())
        try:
            yield
        finally:
            stop.set()
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

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
        instance_id = self.settings.app_instance_id
        self._apply_configured_enable_state()
        self._reset_missed_run_on_startup()
        self.repository.recover_stale_run()
        while True:
            acquired = self.repository.acquire_lease(instance_id, for_maintenance=True)
            if acquired:
                try:
                    self.repository.heartbeat(instance_id)
                    async with self._lease_heartbeat(instance_id):
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
                            self.repository.mark_run_started(instance_id)
                            await self.scanner_service.run_scan()
                            self.repository.mark_run_finished(instance_id)
                        else:
                            self.repository.clear_error(instance_id)
                except Exception as exc:
                    logger.exception(
                        "scheduler loop failed",
                        extra={"event": "scheduler_error"},
                    )
                    self.repository.mark_run_finished(instance_id, error=str(exc))
                finally:
                    self.repository.release_lease(instance_id)
            await asyncio.sleep(self.settings.scheduler_poll_seconds)
