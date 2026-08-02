"""Expected scan-window ledger: planned wake windows vs actual execution.

Mirrors the three Windows Task Scheduler windows so the app can answer
"did we scan when we should have?" after downtime or a skipped wake.

Window times are interpreted in the host machine's local timezone (the
personal Windows host that runs the wake tasks).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models.scan import ScanWindowORM


@dataclass(frozen=True)
class WindowSpec:
    name: str
    # Monday=0 … Sunday=6; empty means every day.
    weekdays: tuple[int, ...]
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int


# Keep in sync with scripts/windows/tasks/*.xml (local wall clock).
WINDOW_SPECS: tuple[WindowSpec, ...] = (
    WindowSpec(
        name="weekday_market",
        weekdays=(0, 1, 2, 3, 4),
        start_hour=8,
        start_minute=12,
        end_hour=16,
        end_minute=30,
    ),
    WindowSpec(
        name="daily_overnight",
        weekdays=(),
        start_hour=3,
        start_minute=13,
        end_hour=3,
        end_minute=45,
    ),
    WindowSpec(
        name="weekend_crypto",
        weekdays=(5, 6),
        start_hour=15,
        start_minute=58,
        end_hour=16,
        end_minute=30,
    ),
)


@dataclass(frozen=True)
class ScanWindowSummary:
    id: int
    window_name: str
    expected_start: datetime
    expected_end: datetime
    status: str
    scan_run_id: str | None
    detail: str | None

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["expected_start"] = self.expected_start.isoformat()
        payload["expected_end"] = self.expected_end.isoformat()
        return payload


def _local_tz():
    return datetime.now().astimezone().tzinfo or timezone.utc


def _localize(day: date, hour: int, minute: int) -> datetime:
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=_local_tz())
    return local.astimezone(timezone.utc)


def expected_windows_for_day(day: date) -> list[tuple[WindowSpec, datetime, datetime]]:
    weekday = day.weekday()
    out: list[tuple[WindowSpec, datetime, datetime]] = []
    for spec in WINDOW_SPECS:
        if spec.weekdays and weekday not in spec.weekdays:
            continue
        start = _localize(day, spec.start_hour, spec.start_minute)
        end = _localize(day, spec.end_hour, spec.end_minute)
        if end <= start:
            end = end + timedelta(days=1)
        out.append((spec, start, end))
    return out


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    return _aware(value).replace(tzinfo=None)


class ScanWindowService:
    """Ensure / mark / report expected scan windows."""

    def __init__(self, *, session_factory=None) -> None:
        self._session_factory = session_factory or SessionLocal

    def ensure_upcoming_windows(self, *, lookback_days: int = 7, lookahead_days: int = 1) -> int:
        """Upsert expected window rows for [today-lookback, today+lookahead]."""
        today = datetime.now().astimezone().date()
        created = 0
        with self._session_factory() as session:
            for offset in range(-lookback_days, lookahead_days + 1):
                day = today + timedelta(days=offset)
                for spec, start, end in expected_windows_for_day(day):
                    existing = session.execute(
                        select(ScanWindowORM).where(
                            ScanWindowORM.window_name == spec.name,
                            ScanWindowORM.expected_start == _naive_utc(start),
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        continue
                    now = _naive_utc(datetime.now(timezone.utc))
                    session.add(
                        ScanWindowORM(
                            window_name=spec.name,
                            expected_start=_naive_utc(start),
                            expected_end=_naive_utc(end),
                            status="pending",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    created += 1
            session.commit()
        return created

    def mark_executed(self, *, scan_run_id: str | None = None, at: datetime | None = None) -> int:
        """Mark the currently-open expected window as executed."""
        now = _aware(at or datetime.now(timezone.utc))
        naive = _naive_utc(now)
        updated = 0
        with self._session_factory() as session:
            rows = (
                session.execute(
                    select(ScanWindowORM).where(
                        ScanWindowORM.expected_start <= naive,
                        ScanWindowORM.expected_end >= naive,
                        ScanWindowORM.status.in_(("pending", "partial")),
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                row.status = "executed"
                row.scan_run_id = scan_run_id or row.scan_run_id
                row.detail = "Scan observed inside expected window"
                row.updated_at = naive
                updated += 1
            session.commit()
        return updated

    def sweep_missed(self, *, grace_minutes: int = 15) -> int:
        """Mark past-due pending windows as missed."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=grace_minutes)
        naive = _naive_utc(cutoff)
        marked = 0
        with self._session_factory() as session:
            rows = (
                session.execute(
                    select(ScanWindowORM).where(
                        ScanWindowORM.status == "pending",
                        ScanWindowORM.expected_end < naive,
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                row.status = "missed"
                row.detail = "Expected window ended with no scan observed"
                row.updated_at = _naive_utc(datetime.now(timezone.utc))
                marked += 1
            session.commit()
        return marked

    def list_recent(self, *, limit: int = 30) -> list[ScanWindowSummary]:
        with self._session_factory() as session:
            rows = (
                session.execute(
                    select(ScanWindowORM)
                    .order_by(ScanWindowORM.expected_start.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [
                ScanWindowSummary(
                    id=row.id,
                    window_name=row.window_name,
                    expected_start=_aware(row.expected_start),
                    expected_end=_aware(row.expected_end),
                    status=row.status,
                    scan_run_id=row.scan_run_id,
                    detail=row.detail,
                )
                for row in rows
            ]

    def missed_count(self, *, lookback_days: int = 14) -> int:
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        with self._session_factory() as session:
            rows = (
                session.execute(
                    select(ScanWindowORM).where(
                        ScanWindowORM.status == "missed",
                        ScanWindowORM.expected_start >= _naive_utc(since),
                    )
                )
                .scalars()
                .all()
            )
            return len(rows)

    def ensure_and_sweep(self) -> dict[str, int]:
        created = self.ensure_upcoming_windows()
        missed = self.sweep_missed()
        return {"created": created, "missed_marked": missed}
