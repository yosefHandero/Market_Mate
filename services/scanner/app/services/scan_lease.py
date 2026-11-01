"""Shared ownership for manual scans, scheduled scans, and scan maintenance."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

from app.errors import AppError
from app.services.scheduler_repository import SchedulerRepository


class ScanLeaseLost(AppError):
    def __init__(self) -> None:
        super().__init__(
            message="Scan ownership was lost; remaining work was cancelled. Check the latest saved scan before retrying.",
            status_code=503,
            code="scan_lease_lost",
        )


@dataclass
class ScanLease:
    repository: SchedulerRepository
    owner: str
    lost: bool = False
    scan_started: bool = False

    def check(self, session=None) -> None:
        # With a session, the conditional write is in the evidence transaction:
        # a successor cannot acquire ownership between this fence and commit.
        if self.lost or not self.repository.check_lease(self.owner, session=session):
            self.lost = True
            raise ScanLeaseLost()


_current_lease: ContextVar[ScanLease | None] = ContextVar("scan_lease", default=None)


def assert_current_scan_lease(session=None) -> None:
    lease = _current_lease.get()
    if lease is not None:
        lease.check(session=session)


@asynccontextmanager
async def shared_scan_lease(repository: SchedulerRepository, *, source: str):
    current = _current_lease.get()
    if current is not None:
        current.check()
        yield current
        return

    # Per-operation identity: one process can receive concurrent manual calls.
    owner = f"{source[:20]}-{uuid4().hex}"
    interval = max(0.01, repository.settings.scheduler_lease_seconds / 3)
    if not repository.acquire_lease(owner, for_maintenance=True):
        raise AppError(
            message="Scan already running. Wait for the active scan or maintenance to finish.",
            status_code=409,
            code="scan_already_running",
        )
    lease = ScanLease(repository, owner)
    token = _current_lease.set(lease)
    parent = asyncio.current_task()

    async def renew() -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                renewed = repository.heartbeat(owner)
            except Exception:
                renewed = False
            if not renewed:
                lease.lost = True
                parent.cancel()
                return

    heartbeat = asyncio.create_task(renew())
    try:
        yield lease
        lease.check()
    except asyncio.CancelledError:
        if lease.lost:
            raise ScanLeaseLost() from None
        raise
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        _current_lease.reset(token)
        repository.release_lease(owner)


async def run_with_scan_lease(operation, repository: SchedulerRepository, *, source: str):
    async with shared_scan_lease(repository, source=source) as lease:
        if lease.scan_started:
            return await operation()
        if not repository.mark_run_started(lease.owner):
            raise ScanLeaseLost()
        lease.scan_started = True
        try:
            result = await operation()
            lease.check()
        except BaseException as exc:
            repository.mark_run_finished(
                lease.owner,
                error="Scan cancelled" if isinstance(exc, asyncio.CancelledError) else str(exc),
            )
            raise
        else:
            repository.mark_run_finished(lease.owner)
            return result
        finally:
            lease.scan_started = False
