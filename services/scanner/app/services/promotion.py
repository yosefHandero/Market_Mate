from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.schemas import PromotionGateResult, PromotionReadinessResponse
from app.services.repository import ScanRepository


class PromotionService:
    def __init__(self, scan_repository: ScanRepository | None = None) -> None:
        self.settings = get_settings()
        self.repo = scan_repository or ScanRepository()

    def evaluate_promotion_readiness(self, current_phase: str) -> PromotionReadinessResponse:
        generated_at = datetime.now(timezone.utc)
        summary = self.repo.get_paper_ledger_summary()
        reconciliation = self.repo.reconcile_paper_loop()
        automation = self.repo.list_execution_audits(limit=200)
        seven_days_ago = generated_at - timedelta(days=7)
        recent_audits = [row for row in automation if row.created_at >= seven_days_ago]
        duplicate_like = [
            row for row in recent_audits
            if (row.error_message or "").lower().find("idempotency") >= 0
        ]
        dry_runs = [row for row in recent_audits if row.lifecycle_status == "dry_run"]
        positive_realized = summary.total_realized_pnl >= 0
        checks = [
            PromotionGateResult(
                key="reconciliation_clean",
                passed=reconciliation.ok,
                detail="Paper intents, audits, and ledger rows reconcile cleanly." if reconciliation.ok else f"{reconciliation.total_issues} reconciliation issue(s) remain.",
            ),
            PromotionGateResult(
                key="no_duplicate_incidents",
                passed=not duplicate_like,
                detail="No duplicate/idempotency incidents detected in recent audits." if not duplicate_like else f"{len(duplicate_like)} duplicate/idempotency-like audit failures found.",
            ),
            PromotionGateResult(
                key="minimum_dry_runs",
                passed=len(dry_runs) >= 5,
                detail=f"{len(dry_runs)} dry-run audit(s) in the last 7 days.",
            ),
            PromotionGateResult(
                key="realized_pnl_non_negative",
                passed=positive_realized,
                detail=f"Realized paper P&L is {summary.total_realized_pnl:.2f}.",
            ),
        ]
        phase_order = ["disabled", "shadow", "limited", "broad"]
        target_phase = None
        if current_phase in phase_order:
            idx = phase_order.index(current_phase)
            target_phase = phase_order[min(idx + 1, len(phase_order) - 1)]
        passed = all(check.passed for check in checks)
        details = [check.detail for check in checks]
        return PromotionReadinessResponse(
            current_phase=current_phase,  # type: ignore[arg-type]
            target_phase=target_phase,  # type: ignore[arg-type]
            passed=passed,
            generated_at=generated_at,
            details=details,
            checks=checks,
        )
