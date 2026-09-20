"""Lifecycle tests use temporary files and harmless children, never app imports."""
import ctypes
from ctypes import wintypes
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "manual_app.py"
spec = importlib.util.spec_from_file_location("manual_app", MODULE)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def running(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


@unittest.skipUnless(os.name == "nt", "Windows lifecycle")
class ManualAppTests(unittest.TestCase):
    def test_duplicate_session_lock_rejects_and_releases(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            with app.SessionLock(path):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with app.SessionLock(path):
                        self.fail("duplicate lock acquired")
            with app.SessionLock(path):
                pass

    def test_stop_request_only_targets_recorded_session(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            state = path / "manual-session.json"
            state.write_text(json.dumps({"session_id": "this-session", "pid": os.getpid()}))

            def supervisor():
                stop = path / "manual-session.stop"
                deadline = time.monotonic() + 3
                while not stop.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(stop.read_text(), "this-session")
                state.unlink()

            thread = threading.Thread(target=supervisor)
            thread.start()
            self.assertEqual(app.request_stop(path, timeout=3), 0)
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())

    def test_occupied_port_fails_before_launch_or_database_import(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(app, "port_available", return_value=False), \
                patch.object(app, "own_process_tree") as own, patch.object(app.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "occupied"):
                app.start(no_auto_scan=True, run_dir=Path(temp))
            own.assert_not_called()
            spawn.assert_not_called()
            self.assertFalse(any(name == "app.db" for name in sys.modules))

    def test_manual_start_controls_scheduler_before_worker_without_rewriting_env(self):
        for no_auto_scan in (False, True):
            with self.subTest(no_auto_scan=no_auto_scan), tempfile.TemporaryDirectory() as temp:
                path = Path(temp)
                run_dir = path / "var" / "run"
                env_file = path / ".env"
                env_file.write_text("SCHEDULER_ENABLED=true\nEXECUTION_ENABLED=false\n")
                events = []
                checks = []

                def spawn(command, **kwargs):
                    events.append(("spawn", command, kwargs["env"]["SCHEDULER_ENABLED"]))
                    return object()

                def check(_processes):
                    checks.append(True)
                    if len(checks) == 2:
                        state = json.loads((run_dir / "manual-session.json").read_text())
                        (run_dir / "manual-session.stop").write_text(state["session_id"])

                def request(route, **kwargs):
                    events.append(("request", route))
                    return {}

                with patch.object(app, "SCANNER", path), patch.object(app, "port_available", return_value=True), \
                        patch.object(app, "own_process_tree"), patch.object(app.shutil, "which", return_value="node"), \
                        patch.object(app.subprocess, "Popen", side_effect=spawn), \
                        patch.object(app, "wait_ready"), patch.object(app, "api_request", side_effect=request), \
                        patch.object(app, "require_running", side_effect=check), \
                        patch.object(app, "stop_children") as stop, patch.object(app.time, "sleep"):
                    self.assertEqual(app.start(no_auto_scan=no_auto_scan, run_dir=run_dir), 0)
                stop.assert_called_once()
                self.assertEqual(len(stop.call_args.args[0]), 3)
                self.assertEqual([e[2] for e in events if e[0] == "spawn"], ["false"] * 3)
                worker_index = next(i for i, e in enumerate(events) if e[0] == "spawn" and "app.worker" in e[1])
                self.assertLess(events.index(("request", "/scan/scheduler/stop")), worker_index)
                self.assertEqual(("request", "/scan/scheduler/start") in events, not no_auto_scan)
                self.assertEqual(events[-1], ("request", "/scan/scheduler/stop"))
                self.assertEqual(env_file.read_text(), "SCHEDULER_ENABLED=true\nEXECUTION_ENABLED=false\n")
                self.assertFalse((run_dir / "manual-session.json").exists())

    def test_startup_failure_stops_owned_children_and_releases_session(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            run_dir = path / "var" / "run"
            with patch.object(app, "SCANNER", path), patch.object(app, "port_available", return_value=True), \
                    patch.object(app, "own_process_tree"), patch.object(app.shutil, "which", return_value="node"), \
                    patch.object(app.subprocess, "Popen", return_value="owned-api"), \
                    patch.object(app, "wait_ready", side_effect=RuntimeError("failed startup")), \
                    patch.object(app, "api_request") as request, patch.object(app, "stop_children") as stop:
                with self.assertRaisesRegex(RuntimeError, "failed startup"):
                    app.start(no_auto_scan=True, run_dir=run_dir)
            stop.assert_called_once_with(["owned-api"])
            request.assert_not_called()
            self.assertFalse((run_dir / "manual-session.json").exists())
            with app.SessionLock(run_dir):
                pass

    def test_abrupt_supervisor_exit_kills_child_and_grandchild_only(self):
        with tempfile.TemporaryDirectory() as temp:
            pid_file = Path(temp) / "children.json"
            grandchild = "import time; time.sleep(60)"
            child = (
                "import os,subprocess,sys,time,json; from pathlib import Path; "
                f"p=subprocess.Popen([sys.executable,'-c',{grandchild!r}]); "
                f"Path({str(pid_file)!r}).write_text(json.dumps([os.getpid(),p.pid])); time.sleep(60)"
            )
            supervisor = (
                "import sys,subprocess,time; "
                f"sys.path.insert(0,{str(MODULE.parent)!r}); import manual_app; "
                "manual_app.own_process_tree(); "
                f"subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(60)"
            )
            unrelated = subprocess.Popen([sys.executable, "-c", grandchild])
            owner = subprocess.Popen([sys.executable, "-c", supervisor], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 10
                while not pid_file.exists() and owner.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(pid_file.exists(), owner.communicate(timeout=1) if owner.poll() is not None else "no child started")
                children = json.loads(pid_file.read_text())
                self.assertTrue(all(running(pid) for pid in children))
                owner.terminate()
                owner.wait(timeout=5)
                deadline = time.monotonic() + 5
                while any(running(pid) for pid in children) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(any(running(pid) for pid in children))
                self.assertIsNone(unrelated.poll(), "unrelated process must survive")
            finally:
                if owner.poll() is None:
                    owner.terminate()
                owner.communicate(timeout=5)
                unrelated.terminate()
                unrelated.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
