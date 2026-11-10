from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.schemas import ScanResult

# A usable fallback and inputs that were intentionally skipped are nonblocking.
HEALTHY_FRESHNESS_FLAG_VALUES = frozenset({
    "ok", "ws_override", "fallback", "successful_empty", "not_requested", "disabled",
})


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
    """True only when the stored bar age itself is severely old.

    Missing directional news and other context flags are data-quality warnings.
    They do not make a fresh bar stale.
    """
    age = row_bar_age_minutes(row)
    if age is None:
        return False
    return age > unified_severe_stale_minutes(settings)


def row_is_unusable_or_stale(row: ScanResult, settings: Settings) -> bool:
    """True when bar age is missing or older than the bar-freshness threshold.

    Context flags stay on ``row_has_bad_freshness_flags`` so readiness reporting
    does not collapse news or provider gaps into staleness.
    """
    return row_is_bar_stale(row, settings)


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
