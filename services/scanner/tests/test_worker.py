from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import app.worker as worker_module


class WorkerInstanceGuardTests(unittest.TestCase):
    def _pid_file(self, temp_dir: str) -> Path:
        return Path(temp_dir) / "var" / "run" / "worker.pid"

    def test_rejects_existing_live_market_mate_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = self._pid_file(temp_dir)
            pid_file.parent.mkdir(parents=True)
            pid_file.write_text("1234\n", encoding="ascii")
            observed_pids: list[int] = []

            def command_line_reader(pid: int) -> str:
                observed_pids.append(pid)
                return r"C:\Python312\python.exe -m app.worker"

            guard = worker_module.WorkerInstanceGuard(
                pid_file=pid_file,
                current_pid=4321,
                command_line_reader=command_line_reader,
                process_liveness_checker=lambda _pid: True,
            )

            with self.assertRaisesRegex(
                worker_module.DuplicateWorkerError,
                "already running.*1234",
            ):
                guard.acquire()

            self.assertEqual(observed_pids, [1234])
            self.assertEqual(pid_file.read_text(encoding="ascii"), "1234\n")

    def test_definitely_dead_pid_file_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = self._pid_file(temp_dir)
            pid_file.parent.mkdir(parents=True)
            pid_file.write_text("1234\n", encoding="ascii")
            observed_pids: list[int] = []

            def process_liveness_checker(pid: int) -> bool:
                observed_pids.append(pid)
                return False

            def command_line_reader(_pid: int) -> str | None:
                self.fail("dead PID command line should not be inspected")

            guard = worker_module.WorkerInstanceGuard(
                pid_file=pid_file,
                current_pid=4321,
                command_line_reader=command_line_reader,
                process_liveness_checker=process_liveness_checker,
            )

            with guard:
                self.assertEqual(pid_file.read_text(encoding="ascii"), "4321\n")

            self.assertEqual(observed_pids, [1234])
            self.assertFalse(pid_file.exists())

    def test_live_non_worker_pid_file_is_replaced_and_removed_on_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = self._pid_file(temp_dir)
            pid_file.parent.mkdir(parents=True)
            pid_file.write_text("1234\n", encoding="ascii")

            guard = worker_module.WorkerInstanceGuard(
                pid_file=pid_file,
                current_pid=4321,
                command_line_reader=lambda _pid: "python -m uvicorn app.main:app",
                process_liveness_checker=lambda _pid: True,
            )

            with guard:
                self.assertEqual(pid_file.read_text(encoding="ascii"), "4321\n")

            self.assertFalse(pid_file.exists())

    def test_malformed_pid_file_is_treated_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = self._pid_file(temp_dir)
            pid_file.parent.mkdir(parents=True)
            pid_file.write_text("not-a-pid\n", encoding="ascii")

            guard = worker_module.WorkerInstanceGuard(
                pid_file=pid_file,
                current_pid=4321,
                command_line_reader=lambda _pid: None,
            )

            with guard:
                self.assertEqual(pid_file.read_text(encoding="ascii"), "4321\n")

            self.assertFalse(pid_file.exists())

    def test_live_pid_with_unavailable_command_line_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = self._pid_file(temp_dir)
            pid_file.parent.mkdir(parents=True)
            pid_file.write_text("1234\n", encoding="ascii")

            guard = worker_module.WorkerInstanceGuard(
                pid_file=pid_file,
                current_pid=4321,
                command_line_reader=lambda _pid: None,
                process_liveness_checker=lambda _pid: True,
            )

            with self.assertRaisesRegex(
                worker_module.WorkerPidInspectionError,
                "command line could not be inspected",
            ):
                guard.acquire()

            self.assertEqual(pid_file.read_text(encoding="ascii"), "1234\n")

    def test_release_removes_only_current_worker_pid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = self._pid_file(temp_dir)
            guard = worker_module.WorkerInstanceGuard(
                pid_file=pid_file,
                current_pid=4321,
                command_line_reader=lambda _pid: None,
            )

            guard.acquire()
            guard.release()

            self.assertFalse(pid_file.exists())

        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = self._pid_file(temp_dir)
            guard = worker_module.WorkerInstanceGuard(
                pid_file=pid_file,
                current_pid=4321,
                command_line_reader=lambda _pid: None,
            )

            guard.acquire()
            pid_file.write_text("9999\n", encoding="ascii")
            guard.release()

            self.assertEqual(pid_file.read_text(encoding="ascii"), "9999\n")

    def test_run_reports_duplicate_worker_and_returns_nonzero(self) -> None:
        class DuplicateGuard:
            def __enter__(self):
                raise worker_module.DuplicateWorkerError("worker already running")

            def __exit__(self, *_exc_info):
                return None

        stderr = io.StringIO()
        with (
            patch.object(worker_module, "WorkerInstanceGuard", return_value=DuplicateGuard()),
            patch.object(worker_module.sys, "stderr", stderr),
        ):
            exit_code = worker_module.run()

        self.assertEqual(exit_code, 1)
        self.assertIn("worker already running", stderr.getvalue())

    def test_windows_launcher_syntax_is_valid(self) -> None:
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell is not available")

        repo_root = Path(__file__).resolve().parents[3]
        launcher = repo_root / "scripts" / "windows" / "Start-ScannerWorker.ps1"
        env = os.environ.copy()
        env["MARKET_MATE_LAUNCHER_UNDER_TEST"] = str(launcher)
        command = (
            "$scriptPath = $env:MARKET_MATE_LAUNCHER_UNDER_TEST; "
            "$tokens = $null; "
            "$parseErrors = $null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            "$scriptPath, [ref]$tokens, [ref]$parseErrors) | Out-Null; "
            "if ($parseErrors.Count -gt 0) { "
            "$parseErrors | ForEach-Object { Write-Error $_.Message }; exit 1 "
            "}"
        )

        result = subprocess.run(
            [shell, "-NoProfile", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_worker_startup_scripts_invoke_guarded_worker_entrypoint(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        direct_scripts = [
            repo_root / "scripts" / "start-worker.ps1",
            repo_root / "scripts" / "start-worker.sh",
            repo_root / "services" / "scanner" / "scripts" / "run_worker_local.sh",
        ]
        for script in direct_scripts:
            with self.subTest(script=script):
                self.assertIn("python -m app.worker", script.read_text(encoding="utf-8"))

        windows_launcher = (
            repo_root / "scripts" / "windows" / "Start-ScannerWorker.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("'-m', 'app.worker'", windows_launcher)

        wake_window = (
            repo_root / "scripts" / "windows" / "Invoke-WakeWindow.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("Start-ScannerWorker.ps1", wake_window)


if __name__ == "__main__":
    unittest.main()
