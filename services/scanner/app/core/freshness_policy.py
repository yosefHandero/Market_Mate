from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.schemas import ScanResult

# Freshness flag values that indicate healthy market data (not blocking).
HEALTHY_FRESHNESS_FLAG_VALUES = frozenset({"ok", "ws_override"})


def is_healthy_freshness_flag(value: object) -> bool:
    return str(value).strip().lower() in HEALTHY_FRESHNESS_FLAG_VALUES


def unified_freshness_max_age_minutes(settings: Settings) -> int:
    """Scan-run freshness threshold (minutes): how recently the last full scan completed."""
    return settings.health_max_stale_minutes


def unified_bar_freshness_max_age_minutes(settings: Settings) -> int:
    """Per-bar staleness threshold (minutes).

    Decoupled from scan-run freshness so delayed feeds (e.g. ~31-minute Alpaca bars)
    do not read as critical while the scan itself is still fresh.
    """
    return settings.provider_max_bar_age_minutes


def unified_severe_stale_minutes(settings: Settings) -> int:
    """Row-level severe staleness threshold (minutes)."""
    return max(settings.health_max_stale_minutes * 12, 360)


def row_has_bad_freshness_flags(row: ScanResult) -> bool:
    return any(
        not is_healthy_freshness_flag(value)
        for value in (row.freshness_flags or {}).values()
    )


def row_bar_age_minutes(row: ScanResult) -> float | None:
    age = row.bar_age_minutes
    return age if isinstance(age, (int, float)) else None


def row_is_bar_stale(row: ScanResult, settings: Settings) -> bool:
    age = row_bar_age_minutes(row)
    if age is None:
        return True
    return age > unified_bar_freshness_max_age_minutes(settings)


def row_is_severely_stale(row: ScanResult, settings: Settings) -> bool:
    age = row_bar_age_minutes(row)
    severe = unified_severe_stale_minutes(settings)
    return (age is not None and age > severe) or row_has_bad_freshness_flags(row)


def row_is_unusable_or_stale(row: ScanResult, settings: Settings) -> bool:
    return row_is_bar_stale(row, settings) or row_has_bad_freshness_flags(row)


def enrich_scan_run_freshness(
    *,
    created_at: datetime | None,
    settings: Settings,
) -> tuple[float | None, bool | None]:
    if created_at is None:
        return None, False
    comparable = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    age_minutes = round(
        (datetime.now(timezone.utc) - comparable).total_seconds() / 60,
        2,
    )
    return age_minutes, age_minutes <= unified_freshness_max_age_minutes(settings)
