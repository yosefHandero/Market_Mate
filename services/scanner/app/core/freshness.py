from __future__ import annotations

from datetime import datetime, timezone


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def signal_age_minutes(*, observed_at: datetime, signal_created_at: datetime) -> float:
    return round((as_utc(observed_at) - as_utc(signal_created_at)).total_seconds() / 60, 2)


def is_stale_signal(
    *,
    observed_at: datetime,
    signal_created_at: datetime,
    stale_after_minutes: int,
) -> tuple[bool, float]:
    age_minutes = signal_age_minutes(
        observed_at=observed_at,
        signal_created_at=signal_created_at,
    )
    return age_minutes > stale_after_minutes, age_minutes
