from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.db import check_database_connection, get_schema_status
from app.services.repository import ScanRepository


def compute_scan_freshness_fields(
    *,
    last_scan_at: datetime | None,
    health_max_stale_minutes: int,
) -> tuple[float | None, bool | None]:
    """Return (last_scan_age_minutes, scan_fresh). No scan -> (None, False) for honest readiness UX."""
    if last_scan_at is None:
        return None, False
    comparable = last_scan_at if last_scan_at.tzinfo else last_scan_at.replace(tzinfo=timezone.utc)
    age_minutes = round(
        (datetime.now(timezone.utc) - comparable).total_seconds() / 60,
        2,
    )
    return age_minutes, age_minutes <= health_max_stale_minutes


def evaluate_operational_readiness(
    *,
    scan_repository: ScanRepository,
    settings: Settings | None = None,
) -> tuple[bool, str | None]:
    """
    State execution and preview depend on: DB reachable, schema complete, at least one full scan, scan not stale.
    """
    cfg = settings or get_settings()
    if not check_database_connection():
        return False, "Database connection failed."
    schema_status = get_schema_status()
    if not schema_status.ok:
        return False, "Database schema is incomplete."
    last_scan_at = scan_repository.get_latest_run_timestamp()
    if last_scan_at is None:
        return False, "No full scan has completed yet; operational readiness requires at least one scan."
    age_minutes, scan_fresh = compute_scan_freshness_fields(
        last_scan_at=last_scan_at,
        health_max_stale_minutes=cfg.health_max_stale_minutes,
    )
    if not scan_fresh:
        return False, (
            f"Latest full scan is stale ({age_minutes:.2f} min > {cfg.health_max_stale_minutes} min)."
        )
    return True, None
