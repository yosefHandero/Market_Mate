from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone

from app.config import get_settings
from app.services.scanner import ScannerService
from app.services.scheduler_repository import SchedulerRepository

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(
        self,
        *,
        scanner_service: ScannerService | None = None,
        repository: SchedulerRepository | None = None,
    ) -> None:
        self.settings = get_settings()
        self.scanner_service = scanner_service or ScannerService()
        self.repository = repository or SchedulerRepository()

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

    async def _run_scan_with_heartbeat(self, instance_id: str) -> None:
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
            await self.scanner_service.run_scan()
        finally:
            stop.set()
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    def _apply_configured_enable_state(self) -> None:
        """Make the SCHEDULER_ENABLED config authoritative on worker startup.

        Enablement is persisted in the DB (via /scan/scheduler/start). Previously the
        config flag was never used to gate the loop, so a fresh DB stayed disabled and
        no evidence accrued. When SCHEDULER_ENABLED is true we enable the DB scheduler
        on startup so scans, outcome resolution, and horizon closes actually run."""
        if not self.settings.scheduler_enabled:
            return
        if self.repository.get_state().enabled:
            return
        self.repository.set_enabled(enabled=True)
        logger.info(
            "scheduler auto-enabled from SCHEDULER_ENABLED config",
            extra={"event": "scheduler_auto_enabled"},
        )

    def _refresh_scan_windows(self, *, scan_run_id: str | None = None) -> None:
        """Maintain the expected-window ledger and mark the current window executed."""
        try:
            from app.services.scan_windows import ScanWindowService

            windows = ScanWindowService()
            windows.ensure_and_sweep()
            if scan_run_id is not None:
                windows.mark_executed(scan_run_id=scan_run_id)
        except Exception:
            logger.exception(
                "scan window ledger refresh failed",
                extra={"event": "scan_window_refresh_failed"},
            )

    async def run_forever(self) -> None:
        instance_id = self.settings.app_instance_id
        self._apply_configured_enable_state()
        self._reset_missed_run_on_startup()
        self.repository.recover_stale_run()
        self._refresh_scan_windows()
        while True:
            acquired = self.repository.acquire_lease(instance_id)
            if acquired:
                try:
                    self.repository.heartbeat(instance_id)
                    await self.scanner_service.refresh_due_signal_outcomes(
                        observed_at=datetime.now(timezone.utc)
                    )
                    await self.scanner_service.refresh_due_prediction_snapshots(
                        observed_at=datetime.now(timezone.utc)
                    )
                    await self.scanner_service.close_open_positions_past_horizon(
                        observed_at=datetime.now(timezone.utc)
                    )
                    if self.repository.due_for_run():
                        self.repository.mark_run_started(instance_id)
                        await self._run_scan_with_heartbeat(instance_id)
                        self.repository.mark_run_finished(instance_id)
                        latest_run_id = None
                        try:
                            latest = self.scanner_service.repo.get_latest_run()
                            latest_run_id = getattr(latest, "run_id", None) if latest else None
                        except Exception:
                            latest_run_id = None
                        self._refresh_scan_windows(scan_run_id=latest_run_id)
                    else:
                        self.repository.clear_error(instance_id)
                        self._refresh_scan_windows()
                except Exception as exc:
                    logger.exception(
                        "scheduler loop failed",
                        extra={"event": "scheduler_error"},
                    )
                    self.repository.mark_run_finished(instance_id, error=str(exc))
                finally:
                    self.repository.release_lease(instance_id)
            await asyncio.sleep(self.settings.scheduler_poll_seconds)
