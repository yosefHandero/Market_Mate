"""Immutable-evidence integrity helpers: record hashing, trigger install, checks.

The SQLite trigger created in migration 0020 makes the core prediction columns
tamper-evident. This module provides:
- ``record_hash_for_snapshot`` so the same hash is computed at write time and at
  verification time,
- ``install_prediction_immutability_trigger`` so test databases built via
  ``Base.metadata.create_all`` (which skips migrations) still get the trigger,
- ``run_db_integrity_check`` for the ``POST /system/db/check`` admin endpoint.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.engine import Engine

import app.db  # noqa: F401  ensure app.db initializes before app.models.scan
from app.models.scan import PredictionSnapshotORM


IMMUTABILITY_TRIGGER_NAME = "trg_prediction_snapshots_immutable_core"

_CREATE_TRIGGER_SQL = f"""
CREATE TRIGGER {IMMUTABILITY_TRIGGER_NAME}
BEFORE UPDATE ON prediction_snapshots
FOR EACH ROW
WHEN OLD.record_hash IS NOT NULL AND (
    NEW.ticker <> OLD.ticker
    OR NEW.signal <> OLD.signal
    OR NEW.entry_price <> OLD.entry_price
    OR NEW.range_low <> OLD.range_low
    OR NEW.range_high <> OLD.range_high
    OR NEW.generated_at <> OLD.generated_at
    OR NEW.record_hash <> OLD.record_hash
    OR IFNULL(NEW.campaign_id, '') <> IFNULL(OLD.campaign_id, '')
    OR IFNULL(NEW.config_fingerprint, '') <> IFNULL(OLD.config_fingerprint, '')
    OR IFNULL(NEW.candidate_rank, -1) <> IFNULL(OLD.candidate_rank, -1)
    OR IFNULL(NEW.selection_status, '') <> IFNULL(OLD.selection_status, '')
    OR IFNULL(NEW.rejection_reason, '') <> IFNULL(OLD.rejection_reason, '')
)
BEGIN
    SELECT RAISE(ABORT, 'prediction_snapshots core fields are immutable');
END;
"""


# Immutable core fields covered by record_hash. Outcome fields are deliberately
# excluded so they can be filled in exactly once on resolution.
_HASH_FIELDS = (
    "run_id",
    "ticker",
    "asset_type",
    "signal",
    "entry_price",
    "range_low",
    "range_high",
    "horizon",
    "generated_at",
    "campaign_id",
    "config_fingerprint",
    "strategy_version",
    "feature_version",
    "candidate_rank",
    "selection_status",
    "rejection_reason",
)


def record_hash_for_snapshot(values: dict[str, Any]) -> str:
    """SHA-256 over the immutable core fields of a prediction snapshot."""
    payload = {key: _normalize(values.get(key)) for key in _HASH_FIELDS}
    encoded = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 8)
    return value


def install_prediction_immutability_trigger(engine: Engine) -> bool:
    """Install the immutability trigger on a SQLite engine. No-op elsewhere.

    Returns True if the trigger was (re)installed. Used by tests that build the
    schema via create_all instead of running migration 0020.
    """
    if engine.dialect.name != "sqlite":
        return False
    with engine.begin() as conn:
        conn.execute(text(f"DROP TRIGGER IF EXISTS {IMMUTABILITY_TRIGGER_NAME}"))
        conn.execute(text(_CREATE_TRIGGER_SQL))
    return True


@dataclass
class DbIntegrityReport:
    ok: bool
    quick_check: str
    checked_snapshots: int = 0
    hash_mismatches: list[int] = field(default_factory=list)
    trigger_present: bool | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "quick_check": self.quick_check,
            "checked_snapshots": self.checked_snapshots,
            "hash_mismatches": self.hash_mismatches,
            "trigger_present": self.trigger_present,
            "detail": self.detail,
        }


def run_db_integrity_check(session, *, engine: Engine, sample_limit: int = 500) -> DbIntegrityReport:
    """PRAGMA quick_check + spot re-hash of recent hashed snapshots."""
    quick_check = "skipped_non_sqlite"
    trigger_present: bool | None = None
    if engine.dialect.name == "sqlite":
        quick_check = str(session.execute(text("PRAGMA quick_check")).scalar() or "unknown")
        trigger_present = bool(
            session.execute(
                text(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name=:name"
                ),
                {"name": IMMUTABILITY_TRIGGER_NAME},
            ).scalar()
        )

    rows = list(
        session.execute(
            select(PredictionSnapshotORM)
            .where(PredictionSnapshotORM.record_hash.isnot(None))
            .order_by(PredictionSnapshotORM.id.desc())
            .limit(sample_limit)
        ).scalars().all()
    )
    mismatches: list[int] = []
    for row in rows:
        expected = record_hash_for_snapshot(
            {field_name: getattr(row, field_name, None) for field_name in _HASH_FIELDS}
        )
        if expected != row.record_hash:
            mismatches.append(int(row.id))

    ok = quick_check in {"ok", "skipped_non_sqlite"} and not mismatches
    detail = "integrity ok" if ok else "integrity check found issues"
    return DbIntegrityReport(
        ok=ok,
        quick_check=quick_check,
        checked_snapshots=len(rows),
        hash_mismatches=mismatches,
        trigger_present=trigger_present,
        detail=detail,
    )
