"""Regression checks for the process-wide verification safety guard."""

from pathlib import Path
import tempfile
import unittest

from scripts.run_isolated_tests import IsolationGuard, _creating_socketpair


class IsolationGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.guard = IsolationGuard(self.root)

    def test_allows_memory_and_temporary_file_databases(self) -> None:
        for database in (":memory:", self.root / "fixture.db", (self.root / "uri.db").as_uri()):
            self.guard("sqlite3.connect", (database,))
        self.assertEqual(self.guard.allowed_connections, 3)
        self.assertEqual(self.guard.violations, [])

    def test_refuses_file_database_outside_temporary_root(self) -> None:
        for database in (self.root.parent / "outside.db", "", self.root / ".." / "outside.db"):
            with self.subTest(database=database):
                with self.assertRaisesRegex(AssertionError, "outside isolated test root"):
                    self.guard("sqlite3.connect", (database,))
        self.assertEqual(self.guard.allowed_connections, 0)
        self.assertEqual(len(self.guard.violations), 3)

    def test_refuses_encoded_uri_traversal(self) -> None:
        outside = self.root.as_uri() + "/%2e%2e/outside.db?mode=ro"
        with self.assertRaises(AssertionError):
            self.guard("sqlite3.connect", (outside,))
        self.assertEqual(len(self.guard.violations), 1)

    def test_refuses_remote_uri(self) -> None:
        with self.assertRaises(AssertionError):
            self.guard("sqlite3.connect", ("file://example.invalid/share/scanner.db",))
        self.assertEqual(len(self.guard.violations), 1)

    def test_network_attempts_remain_recorded_after_exception_is_caught(self) -> None:
        for event in ("socket.connect", "socket.sendto", "socket.sendmsg", "socket.getaddrinfo"):
            with self.assertRaisesRegex(AssertionError, "Network access forbidden"):
                self.guard(event, ())
        self.assertEqual(len(self.guard.violations), 4)

    def test_unrelated_audit_events_are_ignored(self) -> None:
        self.guard("open", ("not-a-database.txt", "r", 0))
        self.assertEqual(self.guard.allowed_connections, 0)
        self.assertEqual(self.guard.violations, [])

    def test_only_internal_socketpair_connect_is_allowed(self) -> None:
        with self.assertRaises(AssertionError):
            self.guard("socket.connect", (None, ("127.0.0.1", 8005)))
        token = _creating_socketpair.set(True)
        try:
            self.guard("socket.connect", (None, ("127.0.0.1", 12345)))
            with self.assertRaises(AssertionError):
                self.guard("socket.connect", (None, ("example.invalid", 443)))
            with self.assertRaises(AssertionError):
                self.guard("socket.getaddrinfo", ("example.invalid", 443))
        finally:
            _creating_socketpair.reset(token)
