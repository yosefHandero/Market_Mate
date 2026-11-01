"""Cross-process request ownership, cache and conservative attempt accounting.

Each operation uses its own short transaction. No connection survives a method
call; HTTP and asyncio waits never run inside a transaction. Reservations count
before sending (a crash between reservation and send can overcount, never undercount).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator


class CoordinationBlocked(RuntimeError):
    pass


def content_key(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class ProviderCoordination:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "provider_coordination.sqlite3"
        with self._transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS requests (
                key TEXT PRIMARY KEY, owner TEXT, owned_until REAL NOT NULL DEFAULT 0,
                payload TEXT, cache_until REAL NOT NULL DEFAULT 0,
                failed_until REAL NOT NULL DEFAULT 0)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS quota (
                account TEXT PRIMARY KEY, block_state TEXT, reset_at REAL,
                rate_until REAL NOT NULL DEFAULT 0, total_attempts INTEGER NOT NULL DEFAULT 0,
                day TEXT, day_attempts INTEGER NOT NULL DEFAULT 0, attempt_ceiling INTEGER,
                block_reason TEXT, last_attempt_at REAL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS quota_audit (
                id INTEGER PRIMARY KEY, account TEXT NOT NULL, action TEXT NOT NULL,
                reason TEXT NOT NULL, recorded_at REAL NOT NULL, verified_reset_at REAL)""")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _quota(conn: sqlite3.Connection, account: str) -> sqlite3.Row:
        conn.execute("INSERT OR IGNORE INTO quota(account) VALUES (?)", (account,))
        return conn.execute("SELECT * FROM quota WHERE account = ?", (account,)).fetchone()

    @staticmethod
    def _owns(conn: sqlite3.Connection, key: str, owner: str, now: float) -> bool:
        return conn.execute(
            "SELECT 1 FROM requests WHERE key=? AND owner=? AND owned_until>?",
            (key, owner, now),
        ).fetchone() is not None

    def claim(self, key: str, owner: str, ttl: float, *, now: float | None = None) -> tuple[str, Any]:
        now = time.time() if now is None else now
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM requests WHERE key=?", (key,)).fetchone()
            if row and row["cache_until"] > now and row["payload"] is not None:
                return "cached", json.loads(row["payload"])
            if row and row["failed_until"] > now:
                raise CoordinationBlocked("equivalent_request_recently_failed")
            if row and row["owner"] and row["owned_until"] > now:
                return "waiting", None
            conn.execute("""INSERT INTO requests(key,owner,owned_until) VALUES (?,?,?)
                ON CONFLICT(key) DO UPDATE SET owner=excluded.owner,
                owned_until=excluded.owned_until, payload=NULL, cache_until=0, failed_until=0""",
                (key, owner, now + ttl))
            return "owned", None

    def renew(self, key: str, owner: str, ttl: float, *, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._transaction() as conn:
            return conn.execute("UPDATE requests SET owned_until=? WHERE key=? AND owner=? AND owned_until>?",
                                (now + ttl, key, owner, now)).rowcount == 1

    def complete(self, key: str, owner: str, payload: Any, ttl: float, *, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        serialized = json.dumps(payload, allow_nan=False)
        with self._transaction() as conn:
            return conn.execute("""UPDATE requests SET owner=NULL, owned_until=0,
                payload=?, cache_until=?, failed_until=0 WHERE key=? AND owner=? AND owned_until>?""",
                (serialized, now + ttl, key, owner, now)).rowcount == 1

    def release(self, key: str, owner: str, *, failed: bool = False) -> None:
        with self._transaction() as conn:
            conn.execute("""UPDATE requests SET owner=NULL, owned_until=0, failed_until=?
                WHERE key=? AND owner=? AND owned_until>?""",
                (time.time() + 5 if failed else 0, key, owner, time.time()))

    def reserve_attempt(self, account: str, key: str, owner: str, daily_budget: int | None,
                        *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        with self._transaction() as conn:
            if not self._owns(conn, key, owner, now):
                raise CoordinationBlocked("request_ownership_lost")
            state = self._quota(conn, account)
            if state["block_state"] == "reset_unknown":
                raise CoordinationBlocked("quota_exhausted_reset_unknown")
            if state["block_state"] == "reset_known" and (state["reset_at"] or 0) > now:
                raise CoordinationBlocked("quota_exhausted_waiting_verified_reset")
            if state["rate_until"] > now:
                raise CoordinationBlocked("rate_limit_cooldown")
            if state["attempt_ceiling"] is not None and state["total_attempts"] >= state["attempt_ceiling"]:
                raise CoordinationBlocked("operational_attempt_ceiling_reached")
            day_count = state["day_attempts"] if state["day"] == day else 0
            if daily_budget is not None and day_count >= daily_budget:
                raise CoordinationBlocked("configured_daily_attempt_budget_reached")
            conn.execute("""UPDATE quota SET total_attempts=total_attempts+1, day=?, day_attempts=?,
                last_attempt_at=?, block_state=NULL, reset_at=NULL, block_reason=NULL WHERE account=?""",
                (day, day_count + 1, now, account))

    def record_block(self, account: str, key: str, owner: str, *, reason: str,
                     rate_until: float | None = None, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._transaction() as conn:
            if not self._owns(conn, key, owner, now):
                return False
            self._quota(conn, account)
            if rate_until is not None:
                conn.execute("UPDATE quota SET rate_until=MAX(rate_until,?) WHERE account=?", (rate_until, account))
            else:
                # Marketaux does not document a quota-reset timestamp header.
                # Retry-After is a retry instruction, not proof of a daily reset.
                conn.execute("UPDATE quota SET block_state='reset_unknown', reset_at=NULL, block_reason=? WHERE account=?",
                             (reason, account))
            return True

    def recover(self, account: str, reason: str, *, verified_reset_at: float | None = None,
                now: float | None = None) -> None:
        if not reason.strip():
            raise ValueError("A quota verification reason is required")
        now = time.time() if now is None else now
        with self._transaction() as conn:
            self._quota(conn, account)
            action = "verified_reset_scheduled" if verified_reset_at is not None else "verified_available"
            conn.execute("""INSERT INTO quota_audit(account,action,reason,recorded_at,verified_reset_at)
                VALUES (?,?,?,?,?)""", (account, action, reason.strip(), now, verified_reset_at))
            conn.execute("UPDATE quota SET block_state=?, reset_at=?, block_reason=?, rate_until=0 WHERE account=?",
                         ("reset_known" if verified_reset_at is not None else None,
                          verified_reset_at, reason.strip(), account))

    def set_attempt_ceiling(self, account: str, remaining: int | None, reason: str) -> None:
        if (remaining is not None and remaining < 0) or not reason.strip():
            raise ValueError("Nonnegative remaining attempts and an audit reason are required")
        with self._transaction() as conn:
            state = self._quota(conn, account)
            ceiling = None if remaining is None else state["total_attempts"] + remaining
            conn.execute("UPDATE quota SET attempt_ceiling=? WHERE account=?", (ceiling, account))
            conn.execute("INSERT INTO quota_audit(account,action,reason,recorded_at) VALUES (?,?,?,?)",
                         (account, f"attempt_ceiling:{remaining}", reason.strip(), time.time()))

    def status(self, account: str) -> dict[str, Any]:
        with self._transaction() as conn:
            result = dict(self._quota(conn, account))
            result.pop("account")
            result["audit"] = [dict(row) for row in conn.execute(
                "SELECT action,reason,recorded_at,verified_reset_at FROM quota_audit WHERE account=? ORDER BY id DESC LIMIT 10",
                (account,))]
            return result

    def read_cache(self, key: str) -> Any | None:
        with self._transaction() as conn:
            row = conn.execute("SELECT payload FROM requests WHERE key=? AND cache_until>?", (key, time.time())).fetchone()
            return json.loads(row["payload"]) if row and row["payload"] is not None else None

    def write_cache(self, key: str, value: Any, ttl: float) -> None:
        with self._transaction() as conn:
            conn.execute("""INSERT INTO requests(key,payload,cache_until) VALUES (?,?,?)
                ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, cache_until=excluded.cache_until""",
                (key, json.dumps(value, allow_nan=False), time.time() + ttl))
