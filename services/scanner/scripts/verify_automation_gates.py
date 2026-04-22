#!/usr/bin/env python3
"""DB-backed checks for automation acceptance gates (95+ dry-run evidence)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCANNER_ROOT = Path(__file__).resolve().parent.parent
if str(SCANNER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCANNER_ROOT))

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.models.scan import AutomationIntentORM, ExecutionAuditORM, PaperLoopBreakerORM


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _duplicate_dry_run_audits(session) -> list[dict[str, object]]:
    """Multiple dry_run rows with same idempotency_key (severity-1 if >1 successful dry-run per key)."""
    subq = (
        select(ExecutionAuditORM.idempotency_key, func.count().label("cnt"))
        .where(
            ExecutionAuditORM.idempotency_key.isnot(None),
            ExecutionAuditORM.dry_run.is_(True),
            ExecutionAuditORM.lifecycle_status == "dry_run",
        )
        .group_by(ExecutionAuditORM.idempotency_key)
        .having(func.count() > 1)
    )
    rows = session.execute(subq).all()
    return [{"idempotency_key": r[0], "count": int(r[1])} for r in rows]


def _retry_cap_violations(session, max_attempts: int) -> list[dict[str, object]]:
    stmt = select(AutomationIntentORM).where(
        AutomationIntentORM.attempt_count > max_attempts,
        AutomationIntentORM.status != "failed_terminal",
    )
    rows = session.execute(stmt).scalars().all()
    return [
        {
            "id": r.id,
            "idempotency_key": r.idempotency_key,
            "attempt_count": r.attempt_count,
            "status": r.status,
        }
        for r in rows
    ]


def _breaker_stuck_open_after_expiry(session, *, grace_seconds: int = 120) -> dict[str, object] | None:
    """phase still 'open' after open_until passed (should have moved to half_open on next prepare)."""
    row = session.get(PaperLoopBreakerORM, "default")
    if row is None or row.phase != "open" or row.open_until is None:
        return None
    ou = row.open_until
    if ou.tzinfo is None:
        ou = ou.replace(tzinfo=timezone.utc)
    if _utcnow() < ou + timedelta(seconds=grace_seconds):
        return None
    return {
        "breaker_key": row.breaker_key,
        "phase": row.phase,
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
        "open_until": row.open_until.isoformat() if row.open_until else None,
        "note": "open_until elapsed but phase still open (expected transition to half_open)",
    }


def _count_preview_http_lines(log_path: Path) -> int:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    # uvicorn access-style: POST ... /orders/preview
    pattern = re.compile(r'POST\s+[^\s]*\/orders\/preview', re.IGNORECASE)
    return len(pattern.findall(text))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify automation safety gates against the database.")
    parser.add_argument(
        "--breaker-grace-seconds",
        type=int,
        default=120,
        help="Grace after open_until before flagging stuck open (default 120).",
    )
    parser.add_argument(
        "--access-log",
        type=Path,
        default=None,
        help="Optional API access log file to count POST /orders/preview lines.",
    )
    args = parser.parse_args()

    settings = get_settings()
    max_attempts = settings.paper_loop_retry_max_attempts

    with SessionLocal() as session:
        dupes = _duplicate_dry_run_audits(session)
        retries = _retry_cap_violations(session, max_attempts)
        stuck = _breaker_stuck_open_after_expiry(session, grace_seconds=args.breaker_grace_seconds)

    preview_lines = None
    if args.access_log is not None:
        preview_lines = _count_preview_http_lines(args.access_log)

    gates = {
        "duplicate_dry_run_idempotency_keys": {
            "pass": len(dupes) == 0,
            "details": dupes,
        },
        "retry_cap_enforced": {
            "pass": len(retries) == 0,
            "max_attempts_config": max_attempts,
            "violations": retries,
        },
        "breaker_transitions_after_open_window": {
            "pass": stuck is None,
            "details": stuck,
        },
    }
    if preview_lines is not None:
        gates["http_post_orders_preview_lines_in_log"] = {
            "pass": preview_lines == 0,
            "count": preview_lines,
            "note": "Non-zero may include manual operator calls; filter by client if needed.",
        }

    overall_pass = all(g.get("pass") is True for g in gates.values())

    out = {
        "overall_pass": overall_pass,
        "checked_at": _utcnow().isoformat(),
        "gates": gates,
    }

    print(json.dumps(out, indent=2, default=str))

    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
