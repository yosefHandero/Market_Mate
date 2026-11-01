"""Run backend unittest tests without opening a personal DB or calling providers.

From services/scanner:
    .venv/Scripts/python.exe scripts/run_isolated_tests.py
    .venv/Scripts/python.exe scripts/run_isolated_tests.py tests.test_db

The process-wide audit hook is installed before importing the application. Even
if application code catches a blocked operation, the run still fails. Existing
test fixtures keep their own databases, all beneath this run's temporary root.
This guards Python SQLite connections and sockets; it is not an OS sandbox.
"""

from __future__ import annotations

import argparse
from contextvars import ContextVar
import os
from pathlib import Path
import sys
import socket
import tempfile
import unittest
from urllib.parse import unquote, urlsplit


_creating_socketpair = ContextVar("isolated_socketpair", default=False)


def allow_internal_socketpair() -> None:
    """Windows asyncio uses a loopback socket pair as a wakeup pipe.

    Permit only the connect performed inside stdlib socketpair. Ordinary
    loopback HTTP, DNS and every external provider connection stay forbidden.
    """
    original = socket.socketpair

    def socketpair(*args, **kwargs):
        token = _creating_socketpair.set(True)
        try:
            return original(*args, **kwargs)
        finally:
            _creating_socketpair.reset(token)

    socket.socketpair = socketpair


class IsolationGuard:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.allowed_connections = 0
        self.violations: list[str] = []

    def __call__(self, event: str, args: tuple) -> None:
        if event == "sqlite3.connect":
            raw = os.fsdecode(args[0])
            if raw != ":memory:":
                if raw.startswith("file:"):
                    uri = urlsplit(raw)
                    path = unquote(uri.path)
                    # UNC locations must not be mistaken for a local path.
                    if uri.netloc and uri.netloc != "localhost":
                        self.violations.append("sqlite3.connect remote URI")
                        raise AssertionError("Blocked SQLite connection outside isolated test root")
                    elif len(path) > 2 and path[0] == "/" and path[2] == ":":
                        path = path[1:]
                else:
                    path = raw
                if not path or path.startswith(("//", "\\\\")) or not Path(path).resolve().is_relative_to(self.root):
                    self.violations.append("sqlite3.connect outside temporary root")
                    raise AssertionError("Blocked SQLite connection outside isolated test root")
            self.allowed_connections += 1
        elif event in {"socket.connect", "socket.sendto", "socket.sendmsg", "socket.getaddrinfo"}:
            if (
                event == "socket.connect" and _creating_socketpair.get()
                and len(args) > 1 and isinstance(args[1], tuple)
                and args[1][0] in {"127.0.0.1", "::1"}
            ):
                return
            self.violations.append(event)
            raise AssertionError("Network access forbidden in isolated tests")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="*", help="Dotted unittest names; default: all tests")
    parser.add_argument("--verbosity", type=int, choices=(0, 1, 2), default=1)
    args = parser.parse_args(argv)
    scanner_root = Path(__file__).resolve().parents[1]
    os.chdir(scanner_root)
    sys.path.insert(0, str(scanner_root))

    with tempfile.TemporaryDirectory(prefix="market-mate-tests-") as directory:
        root = Path(directory).resolve()
        # Nested fixtures, including those that import tempfile themselves, stay
        # inside the same audited root. This is a disposable runner process.
        tempfile.tempdir = str(root)
        os.environ["DATABASE_URL"] = f"sqlite:///{(root / 'default.db').as_posix()}"
        os.environ["CACHE_DIR"] = str(root / "cache")
        os.environ["EXECUTION_ENABLED"] = "false"
        os.environ["ALLOW_LIVE_TRADING"] = "false"
        guard = IsolationGuard(root)
        allow_internal_socketpair()
        sys.addaudithook(guard)
        print(f"ISOLATION ROOT: {root}", flush=True)
        result = None
        try:
            # Metadata probes that use the import-time factory get an empty
            # schema, rather than the operator's database or synthetic evidence.
            import app.db as isolated_db

            isolated_db.Base.metadata.create_all(isolated_db.engine)
            loader = unittest.TestLoader()
            suite = (
                loader.loadTestsFromNames(args.tests)
                if args.tests
                else loader.discover(str(scanner_root / "tests"), top_level_dir=str(scanner_root))
            )
            result = unittest.TextTestRunner(verbosity=args.verbosity).run(suite)
        finally:
            if "app.db" in sys.modules:
                sys.modules["app.db"].engine.dispose()
            print(
                f"ISOLATION: {guard.allowed_connections} allowed SQLite connections; "
                f"{len(guard.violations)} forbidden attempts; "
                "all allowed file databases under temporary root",
                flush=True,
            )
            if guard.violations:
                print(f"FORBIDDEN: {guard.violations}", flush=True)
        return 0 if result and result.testsRun and result.wasSuccessful() and not guard.violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
