from __future__ import annotations

import asyncio
from contextlib import suppress
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Callable

from app.config import get_settings
from app.dependencies import coinbase_market_data_service, scheduler_service
from app.logging_utils import configure_logging


WORKER_PID_FILE = Path(__file__).resolve().parent.parent / "var" / "run" / "worker.pid"
WORKER_COMMAND_MARKER = "app.worker"


class WorkerInstanceGuardError(RuntimeError):
    pass


class DuplicateWorkerError(WorkerInstanceGuardError):
    pass


class WorkerPidInspectionError(WorkerInstanceGuardError):
    pass


def _command_line_is_worker(command_line: str | None) -> bool:
    if not command_line:
        return False
    normalized = " ".join(command_line.lower().split())
    return WORKER_COMMAND_MARKER in normalized


def _process_is_running(pid: int) -> bool | None:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_is_running(pid)
    return _posix_process_is_running(pid)


def _windows_process_is_running(pid: int) -> bool | None:
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "$p = Get-CimInstance Win32_Process "
        f'-Filter "ProcessId = {pid}"; '
        "if ($null -eq $p) { 'DEAD' } else { 'RUNNING' }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or "").strip().upper()
    if output == "RUNNING":
        return True
    if output == "DEAD":
        return False
    return None


def _posix_process_is_running(pid: int) -> bool | None:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def _process_command_line(pid: int) -> str | None:
    if pid <= 0:
        return None
    if os.name == "nt":
        return _windows_process_command_line(pid)
    return _posix_process_command_line(pid)


def _windows_process_command_line(pid: int) -> str | None:
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "$p = Get-CimInstance Win32_Process "
        f'-Filter "ProcessId = {pid}"; '
        "if ($p) { $p.CommandLine }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or "").strip()
    return output or None


def _posix_process_command_line(pid: int) -> str | None:
    cmdline_path = Path("/proc") / str(pid) / "cmdline"
    try:
        raw = cmdline_path.read_bytes()
    except OSError:
        raw = b""
    if raw:
        return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return None
    output = (result.stdout or "").strip()
    return output or None


def _read_pid_file(pid_file: Path) -> int | None:
    try:
        raw = pid_file.read_text(encoding="ascii").strip()
    except OSError:
        return None
    return _parse_pid(raw)


def _read_existing_pid_file(pid_file: Path) -> int | None:
    try:
        raw = pid_file.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise WorkerPidInspectionError(
            "Cannot read existing Market Mate scanner worker PID file "
            f"{pid_file}. Leaving it intact; inspect the file permissions before retrying."
        ) from exc
    return _parse_pid(raw)


def _parse_pid(raw: str) -> int | None:
    try:
        pid = int(raw)
    except ValueError:
        return None
    if pid <= 0:
        return None
    return pid


class WorkerInstanceGuard:
    def __init__(
        self,
        *,
        pid_file: Path = WORKER_PID_FILE,
        current_pid: int | None = None,
        command_line_reader: Callable[[int], str | None] = _process_command_line,
        process_liveness_checker: Callable[[int], bool | None] = _process_is_running,
    ) -> None:
        self.pid_file = pid_file
        self.current_pid = current_pid or os.getpid()
        self.command_line_reader = command_line_reader
        self.process_liveness_checker = process_liveness_checker
        self._acquired = False

    def __enter__(self) -> "WorkerInstanceGuard":
        self.acquire()
        return self

    def __exit__(self, *_exc_info) -> None:
        self.release()

    def acquire(self) -> None:
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(
                    self.pid_file,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
            except FileExistsError:
                self._verify_existing_pid_file_can_be_replaced()
                self.pid_file.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(f"{self.current_pid}\n")
            self._acquired = True
            return

    def release(self) -> None:
        if not self._acquired:
            return
        if _read_pid_file(self.pid_file) == self.current_pid:
            self.pid_file.unlink(missing_ok=True)
        self._acquired = False

    def _verify_existing_pid_file_can_be_replaced(self) -> None:
        existing_pid = _read_existing_pid_file(self.pid_file)
        if existing_pid is None or existing_pid == self.current_pid:
            return

        is_running = self._is_existing_pid_running(existing_pid)
        if is_running is False:
            return

        command_line = self._read_existing_command_line(existing_pid)
        if _command_line_is_worker(command_line):
            raise DuplicateWorkerError(
                "Market Mate scanner worker is already running "
                f"(PID {existing_pid}). Stop the existing worker before starting "
                f"another one. PID file: {self.pid_file}"
            )
        if command_line:
            return

        # The process may have exited between liveness and command-line checks.
        is_running_after_command_read = self._is_existing_pid_running(existing_pid)
        if is_running_after_command_read is False:
            return

        raise WorkerPidInspectionError(
            "Cannot verify existing Market Mate scanner worker PID file "
            f"{self.pid_file}: PID {existing_pid} is running, but its command line "
            "could not be inspected. Leaving the PID file intact. Stop that process "
            "or remove the PID file only after confirming it is not the Market Mate worker."
        )

    def _is_existing_pid_running(self, existing_pid: int) -> bool | None:
        try:
            return self.process_liveness_checker(existing_pid)
        except Exception as exc:
            raise WorkerPidInspectionError(
                "Cannot determine whether existing Market Mate scanner worker PID "
                f"{existing_pid} from {self.pid_file} is still running. Leaving the "
                "PID file intact until the process can be inspected."
            ) from exc

    def _read_existing_command_line(self, existing_pid: int) -> str | None:
        try:
            return self.command_line_reader(existing_pid)
        except Exception as exc:
            raise WorkerPidInspectionError(
                "Cannot inspect command line for existing Market Mate scanner worker "
                f"PID {existing_pid} from {self.pid_file}. Leaving the PID file intact."
            ) from exc


async def _worker_heartbeat_loop() -> None:
    settings = get_settings()
    instance_id = settings.app_instance_id
    poll_seconds = max(5, settings.scheduler_poll_seconds)
    while True:
        scheduler_service.repository.record_worker_heartbeat(instance_id)
        await asyncio.sleep(poll_seconds)


async def main() -> None:
    configure_logging()
    loop = asyncio.get_running_loop()
    main_task = asyncio.current_task()
    previous_break_handler = None
    if hasattr(signal, "SIGBREAK") and main_task is not None:
        previous_break_handler = signal.signal(
            signal.SIGBREAK,
            lambda *_args: loop.call_soon_threadsafe(main_task.cancel),
        )
    market_data_task = None
    heartbeat_task = asyncio.create_task(
        _worker_heartbeat_loop(),
        name="scheduler-worker-heartbeat",
    )
    if coinbase_market_data_service.enabled:
        market_data_task = asyncio.create_task(
            coinbase_market_data_service.run_forever(),
            name="coinbase-advanced-trade-ws-worker",
        )
    try:
        await scheduler_service.run_forever()
    finally:
        if previous_break_handler is not None:
            signal.signal(signal.SIGBREAK, previous_break_handler)
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        if market_data_task is not None:
            coinbase_market_data_service.stop()
            market_data_task.cancel()
            with suppress(asyncio.CancelledError):
                await market_data_task


def run() -> int:
    try:
        with WorkerInstanceGuard():
            asyncio.run(main())
    except WorkerInstanceGuardError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Ctrl+C / supervisor Ctrl+Break unwind the scheduler lease and PID guard.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
