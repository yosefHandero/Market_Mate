from __future__ import annotations

import asyncio
import logging
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

    async def run_forever(self) -> None:
        instance_id = self.settings.app_instance_id
        while True:
            acquired = self.repository.acquire_lease(instance_id)
            if acquired:
                try:
                    self.repository.heartbeat(instance_id)
                    await self.scanner_service.refresh_due_signal_outcomes(
                        observed_at=datetime.now(timezone.utc)
                    )
                    if self.repository.due_for_run():
                        self.repository.mark_run_started(instance_id)
                        await self.scanner_service.run_scan()
                        self.repository.mark_run_finished(instance_id)
                except Exception as exc:
                    logger.exception(
                        "scheduler loop failed",
                        extra={"event": "scheduler_error"},
                    )
                    self.repository.mark_run_finished(instance_id, error=str(exc))
                finally:
                    self.repository.release_lease(instance_id)
            await asyncio.sleep(self.settings.scheduler_poll_seconds)
