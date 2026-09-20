"""Manual Windows app supervisor. No application/database imports or wake timers."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]
SCANNER = REPO / "services" / "scanner"
RUN_DIR = SCANNER / "var" / "run"
_JOB_HANDLE = None  # Retain until process exit; Windows then closes/kills the job.


def own_process_tree() -> None:
    """Children inherit this job, even through venv and Next.js launchers.

    The non-inherited handle belongs only to this supervisor. Abrupt termination
    closes it and kills the entire owned tree. Never enumerate/kill other apps.
    """
    global _JOB_HANDLE
    if os.name != "nt":
        raise RuntimeError("Use the Windows manual launcher on Windows.")

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
            ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
            ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits), ("io_counters", ctypes.c_ulonglong * 6),
            ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        kernel.CloseHandle(handle)
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        kernel.CloseHandle(handle)
        raise ctypes.WinError(ctypes.get_last_error())
    _JOB_HANDLE = handle


class SessionLock:
    def __init__(self, run_dir: Path):
        self.path = run_dir / "manual-session.lock"
        self.handle = None

    def __enter__(self):
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0)
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.handle.close()
            raise RuntimeError("MarketMate is already running. Use Stop-MarketMate.ps1 first.") from None
        return self

    def __exit__(self, *_exc):
        import msvcrt
        self.handle.seek(0)
        msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        self.handle.close()


def env_value(name: str) -> str:
    if name in os.environ:
        return os.environ[name]
    env_file = SCANNER / ".env"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = raw.strip().partition("=")
            if sep and key.strip() == name:
                return value.strip().strip("\"'")
    return ""


def api_request(path: str, *, method: str = "GET") -> dict:
    headers = {}
    token = env_value("ADMIN_API_TOKEN")
    if token:
        headers["X-API-Key"] = token
    request = Request("http://127.0.0.1:8005" + path, method=method, headers=headers)
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def port_available(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def require_running(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is not None:
            raise RuntimeError(f"A MarketMate service exited ({process.returncode}); inspect this session's logs.")


def owned_process_count() -> int:
    """Count the job's processes, including this supervisor, without a PID sweep."""
    class Accounting(ctypes.Structure):
        _fields_ = [("times", ctypes.c_longlong * 4), ("page_faults", wintypes.DWORD),
                    ("total", wintypes.DWORD), ("active", wintypes.DWORD), ("terminated", wintypes.DWORD)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                               wintypes.DWORD, ctypes.c_void_p]
    info = Accounting()
    if not kernel.QueryInformationJobObject(_JOB_HANDLE, 1, ctypes.byref(info), ctypes.sizeof(info), None):
        raise ctypes.WinError(ctypes.get_last_error())
    return info.active


def wait_ready(check, processes, stopped, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        require_running(processes)
        if stopped():
            raise KeyboardInterrupt
        try:
            if check():
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    raise RuntimeError("Startup timed out; inspect this session's logs.")


def stop_children(processes: list[subprocess.Popen], timeout: float = 30) -> None:
    # A process-group signal reaches both a venv launcher and its actual worker.
    # API/worker handle SIGBREAK; the job is the final descendant cleanup guard.
    for process in reversed(processes):
        if process.poll() is None:
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            except OSError:
                pass
    deadline = time.monotonic() + timeout
    for process in reversed(processes):
        try:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
    # A venv launcher may exit before the actual worker finishes cancellation.
    # Give all descendants the same grace period, not just the launcher PIDs.
    while _JOB_HANDLE and owned_process_count() > 1 and time.monotonic() < deadline:
        time.sleep(0.1)


def start(*, no_auto_scan: bool, run_dir: Path = RUN_DIR) -> int:
    state_path = run_dir / "manual-session.json"
    stop_path = run_dir / "manual-session.stop"
    with SessionLock(run_dir), ExitStack() as files:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node.js is required; install the documented app dependencies first.")
        for port in (8005, 3000):
            if not port_available(port):
                raise RuntimeError(f"Port {port} is occupied. Stop that app yourself before starting MarketMate.")
        own_process_tree()
        session_id = uuid4().hex
        state = {"session_id": session_id, "pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()}
        state_path.write_text(json.dumps(state), encoding="utf-8")
        stop_path.unlink(missing_ok=True)
        processes = []
        log_dir = SCANNER / "var" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        service_env = os.environ.copy()
        # Session-only orchestration: enable AFTER readiness, never during worker boot.
        service_env["SCHEDULER_ENABLED"] = "false"
        service_env["PYTHONUNBUFFERED"] = "1"

        def stopped():
            return stop_path.exists() and stop_path.read_text(encoding="utf-8").strip() == session_id

        def spawn(label, command, cwd):
            log = files.enter_context((log_dir / f"manual-{label}-{stamp}.log").open("wb"))
            process = subprocess.Popen(command, cwd=cwd, env=service_env, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            processes.append(process)
            print(f"Started {label}; log: {log.name}", flush=True)

        scheduler_stopped = False
        try:
            spawn("api", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8005"], SCANNER)
            wait_ready(lambda: api_request("/livez").get("live"), processes, stopped)
            api_request("/scan/scheduler/stop", method="POST")
            scheduler_stopped = True
            spawn("web", [node, "scripts/run-next.mjs", "dev", "--hostname", "127.0.0.1", "--port", "3000"], REPO / "apps" / "web")

            def web_ready():
                with urlopen("http://127.0.0.1:3000", timeout=5) as response:
                    return response.status == 200

            wait_ready(web_ready, processes, stopped)
            spawn("worker", [sys.executable, "-m", "app.worker"], SCANNER)
            wait_ready(lambda: api_request("/readyz").get("worker_alive"), processes, stopped)
            # Allow singleton failures to surface instead of trusting a stale heartbeat.
            time.sleep(1)
            require_running(processes)
            if not no_auto_scan:
                api_request("/scan/scheduler/start", method="POST")
            state["ready"] = True
            state_path.write_text(json.dumps(state), encoding="utf-8")
            print("MarketMate ready: http://127.0.0.1:3000 | API: http://127.0.0.1:8005", flush=True)
            print("Paper-only. Ctrl+C or Stop-MarketMate.ps1 stops this session.", flush=True)
            while not stopped():
                require_running(processes)
                time.sleep(0.25)
            return 0
        except KeyboardInterrupt:
            return 0
        finally:
            print("Stopping MarketMate services...", flush=True)
            if scheduler_stopped:
                try:
                    api_request("/scan/scheduler/stop", method="POST")
                except (OSError, ValueError):
                    print("Scheduler stop endpoint unavailable; stopping owned services.", flush=True)
            stop_children(processes)
            state_path.unlink(missing_ok=True)
            stop_path.unlink(missing_ok=True)
            print("MarketMate stopped.", flush=True)


def request_stop(run_dir: Path = RUN_DIR, *, timeout: float = 45) -> int:
    state_path = run_dir / "manual-session.json"
    if not state_path.exists():
        print("No manual MarketMate session is recorded.")
        return 0
    state = json.loads(state_path.read_text(encoding="utf-8"))
    (run_dir / "manual-session.stop").write_text(state["session_id"], encoding="utf-8")
    deadline = time.monotonic() + timeout
    while state_path.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    if state_path.exists():
        raise RuntimeError("Stop was requested but not confirmed. Inspect session logs; no unrelated process was stopped.")
    print("MarketMate stopped.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop"))
    parser.add_argument("--no-auto-scan", action="store_true")
    args = parser.parse_args()
    try:
        return request_stop() if args.action == "stop" else start(no_auto_scan=args.no_auto_scan)
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
