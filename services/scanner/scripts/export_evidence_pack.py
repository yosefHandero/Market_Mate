from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import desc, select

SCANNER_ROOT = Path(__file__).resolve().parent.parent
if str(SCANNER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCANNER_ROOT))

from app.config import get_settings
from app.db import SessionLocal
from app.models.journal import JournalEntryORM
from app.models.scan import ExecutionAuditORM, SignalOutcomeORM
from app.services.repository import ScanRepository


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _http_get_json(base_url: str, path: str, *, params: dict[str, str] | None = None, admin_token: str | None = None):
    query = f"?{urlencode(params)}" if params else ""
    request = Request(f"{base_url.rstrip('/')}{path}{query}")
    if admin_token:
        request.add_header("X-API-Key", admin_token)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")


def _paper_loop_samples(limit: int = 10) -> list[dict[str, object]]:
    with SessionLocal() as session:
        audit_rows = session.execute(
            select(ExecutionAuditORM).order_by(desc(ExecutionAuditORM.created_at)).limit(limit)
        ).scalars().all()
        samples: list[dict[str, object]] = []
        for audit in audit_rows:
            outcome = None
            if getattr(audit, "signal_outcome_id", None):
                outcome = session.get(SignalOutcomeORM, audit.signal_outcome_id)
            elif audit.signal_run_id:
                outcome = session.execute(
                    select(SignalOutcomeORM)
                    .where(
                        SignalOutcomeORM.run_id == audit.signal_run_id,
                        SignalOutcomeORM.ticker == audit.ticker,
                    )
                    .order_by(desc(SignalOutcomeORM.generated_at), desc(SignalOutcomeORM.id))
                    .limit(1)
                ).scalar_one_or_none()
            journal_rows = session.execute(
                select(JournalEntryORM)
                .where(
                    JournalEntryORM.ticker == audit.ticker,
                    JournalEntryORM.run_id == audit.signal_run_id,
                )
                .order_by(desc(JournalEntryORM.created_at))
            ).scalars().all()
            samples.append(
                {
                    "audit": {
                        "id": audit.id,
                        "created_at": audit.created_at,
                        "ticker": audit.ticker,
                        "lifecycle_status": audit.lifecycle_status,
                        "signal_outcome_id": getattr(audit, "signal_outcome_id", None),
                        "signal_run_id": audit.signal_run_id,
                        "latest_signal": audit.latest_signal,
                        "trade_gate_allowed": audit.trade_gate_allowed,
                        "trade_gate_reason": audit.trade_gate_reason,
                    },
                    "outcome": (
                        {
                            "id": outcome.id,
                            "generated_at": outcome.generated_at,
                            "signal": outcome.signal,
                            "gate_passed": outcome.gate_passed,
                            "status_15m": outcome.status_15m,
                            "status_1h": outcome.status_1h,
                            "status_1d": outcome.status_1d,
                            "return_after_15m": outcome.return_after_15m,
                            "return_after_1h": outcome.return_after_1h,
                            "return_after_1d": outcome.return_after_1d,
                        }
                        if outcome is not None
                        else None
                    ),
                    "journal_entries": [
                        {
                            "id": row.id,
                            "created_at": row.created_at,
                            "decision": row.decision,
                            "run_id": row.run_id,
                            "ticker": row.ticker,
                            "pnl_pct": row.pnl_pct,
                            "notes": row.notes,
                        }
                        for row in journal_rows
                    ],
                }
            )
        return samples


def _gate_consistency_report(limit: int = 100) -> dict[str, object]:
    with SessionLocal() as session:
        audit_rows = session.execute(
            select(ExecutionAuditORM).order_by(desc(ExecutionAuditORM.created_at)).limit(limit)
        ).scalars().all()
        mismatches: list[dict[str, object]] = []
        checked = 0
        matches = 0
        for audit in audit_rows:
            outcome = None
            if getattr(audit, "signal_outcome_id", None):
                outcome = session.get(SignalOutcomeORM, audit.signal_outcome_id)
            elif audit.signal_run_id:
                outcome = session.execute(
                    select(SignalOutcomeORM)
                    .where(
                        SignalOutcomeORM.run_id == audit.signal_run_id,
                        SignalOutcomeORM.ticker == audit.ticker,
                    )
                    .order_by(desc(SignalOutcomeORM.generated_at), desc(SignalOutcomeORM.id))
                    .limit(1)
                ).scalar_one_or_none()
            if outcome is None or audit.trade_gate_allowed is None:
                continue
            checked += 1
            consistent = bool(audit.trade_gate_allowed) == bool(outcome.gate_passed)
            if consistent:
                matches += 1
                continue
            mismatches.append(
                {
                    "audit_id": audit.id,
                    "ticker": audit.ticker,
                    "created_at": audit.created_at,
                    "signal_outcome_id": getattr(audit, "signal_outcome_id", None),
                    "trade_gate_allowed": audit.trade_gate_allowed,
                    "stored_gate_passed": getattr(outcome, "gate_passed", None),
                    "trade_gate_reason": audit.trade_gate_reason,
                    "stored_gate_reason": getattr(outcome, "gate_reason", None),
                }
            )
        return {
            "checked_audits": checked,
            "matching_audits": matches,
            "mismatch_count": len(mismatches),
            "match_rate": round((matches / checked) * 100, 2) if checked else None,
            "mismatches": mismatches[:20],
        }


def _paper_order_lifecycle(limit: int = 100) -> dict[str, object]:
    with SessionLocal() as session:
        audit_rows = session.execute(
            select(ExecutionAuditORM).order_by(desc(ExecutionAuditORM.created_at)).limit(limit)
        ).scalars().all()
    lifecycle_counts: dict[str, int] = {}
    broker_status_counts: dict[str, int] = {}
    submitted_rows: list[dict[str, object]] = []
    for audit in audit_rows:
        lifecycle_counts[audit.lifecycle_status] = lifecycle_counts.get(audit.lifecycle_status, 0) + 1
        broker_key = audit.broker_status or "unknown"
        broker_status_counts[broker_key] = broker_status_counts.get(broker_key, 0) + 1
        if bool(getattr(audit, "submitted", False)):
            submitted_rows.append(
                {
                    "audit_id": audit.id,
                    "ticker": audit.ticker,
                    "created_at": audit.created_at,
                    "broker_order_id": audit.broker_order_id,
                    "broker_status": audit.broker_status,
                    "signal_run_id": audit.signal_run_id,
                    "signal_outcome_id": getattr(audit, "signal_outcome_id", None),
                }
            )
    return {
        "audits_considered": len(audit_rows),
        "submitted_count": len(submitted_rows),
        "lifecycle_counts": lifecycle_counts,
        "broker_status_counts": broker_status_counts,
        "submitted_orders": submitted_rows[:25],
    }


def _trust_readiness_summary(*, repo: ScanRepository, readyz: dict, threshold_sweep: dict) -> dict[str, object]:
    snapshot = repo.get_trust_readiness_snapshot()
    gate_buckets = {bucket.key: bucket for bucket in snapshot.summary.by_signal_and_gate}
    return {
        "trust_evidence_ready": readyz.get("trust_evidence_ready"),
        "trust_threshold_status": readyz.get("trust_threshold_evidence_status"),
        "trust_threshold_source": readyz.get("trust_threshold_source"),
        "trust_threshold_warning_count": readyz.get("trust_threshold_warning_count"),
        "buy_passed_evaluated_count": gate_buckets.get("BUY:passed").evaluated_count if gate_buckets.get("BUY:passed") else 0,
        "sell_passed_evaluated_count": gate_buckets.get("SELL:passed").evaluated_count if gate_buckets.get("SELL:passed") else 0,
        "buy_blocked_evaluated_count": gate_buckets.get("BUY:blocked").evaluated_count if gate_buckets.get("BUY:blocked") else 0,
        "sell_blocked_evaluated_count": gate_buckets.get("SELL:blocked").evaluated_count if gate_buckets.get("SELL:blocked") else 0,
        "recommendation": threshold_sweep.get("recommendation", {}),
    }


def _scheduler_health(readyz: dict) -> dict[str, object]:
    return {
        "scheduler_running": readyz.get("scheduler_running"),
        "scheduler_enabled": readyz.get("scheduler_enabled"),
        "scheduler_interval_seconds": readyz.get("scheduler_interval_seconds"),
        "next_scan_due_at": readyz.get("next_scan_due_at"),
        "last_scheduler_run_started_at": readyz.get("last_scheduler_run_started_at"),
        "last_scheduler_run_finished_at": readyz.get("last_scheduler_run_finished_at"),
        "last_scheduler_error": readyz.get("last_scheduler_error"),
        "scan_fresh": readyz.get("scan_fresh"),
        "last_scan_at": readyz.get("last_scan_at"),
        "last_scan_age_minutes": readyz.get("last_scan_age_minutes"),
    }


def _product_thesis() -> dict[str, object]:
    return {
        "primary_thesis": "Decision-support and validation platform first; automation second.",
        "primary_user": "Disciplined solo trader, researcher, or very small trading team.",
        "supported_product_boundary": ["apps/web", "services/scanner"],
        "non_goals": [
            "Normal live trading as the default operating mode.",
            "Promoting new providers into the main scoring path without proof.",
            "Treating the home-page simulation as portfolio truth.",
        ],
    }


def _evidence_policy(*, settings, trust_snapshot) -> dict[str, object]:
    return {
        "primary_horizon": settings.validation_primary_horizon,
        "recent_window_days": settings.trust_recent_window_days,
        "window_start": trust_snapshot.window.start,
        "window_end": trust_snapshot.window.end,
        "thresholds": {
            "trade_gate_min_evaluated_count": settings.trade_gate_min_evaluated_count,
            "trade_gate_min_win_rate": settings.trade_gate_min_win_rate,
            "trade_gate_min_avg_return": settings.trade_gate_min_avg_return,
            "calibration_min_signal_samples": settings.calibration_min_signal_samples,
            "calibration_min_score_band_samples": settings.calibration_min_score_band_samples,
            "outcome_baseline_min_evaluated_per_horizon": settings.outcome_baseline_min_evaluated_per_horizon,
            "outcome_baseline_min_mean_return_pct": settings.outcome_baseline_min_mean_return_pct,
        },
        "friction_assumptions_bps": {
            "stock_slippage_bps": settings.stock_slippage_bps,
            "stock_spread_bps": settings.stock_spread_bps,
            "stock_fee_bps": settings.stock_fee_bps,
            "crypto_slippage_bps": settings.crypto_slippage_bps,
            "crypto_spread_bps": settings.crypto_spread_bps,
            "crypto_fee_bps": settings.crypto_fee_bps,
        },
        "minimum_proof_targets": {
            "primary_loop_evaluated_signals": 300,
            "passed_buy_signals": 100,
            "passed_sell_signals": 100,
            "prospective_window_weeks_min": 8,
            "prospective_window_weeks_target": 12,
        },
        "required_benchmarks": [
            "simpler_baseline_directional_model",
            "core_data_only_variant",
            "currently_deployed_strategy_version",
        ],
        "promotion_gates": {
            "providers_must_prove_incremental_value": True,
            "replay_is_not_final_proof": True,
            "live_rollout_requires_recent_positive_friction_adjusted_evidence": True,
        },
    }


def _paper_trading_ops_summary(*, readyz: dict, execution_alignment: dict, gate_consistency: dict) -> dict[str, object]:
    execution_counts = {
        "taken_trades": execution_alignment.get("taken_trades", {}).get("total_signals", 0) or 0,
        "skipped_or_watched": execution_alignment.get("skipped_or_watched", {}).get("total_signals", 0) or 0,
        "blocked_previews": execution_alignment.get("blocked_previews", {}).get("total_signals", 0) or 0,
        "journal_took": execution_alignment.get("journal_took", {}).get("total_signals", 0) or 0,
    }
    checklist = {
        "ready": bool(readyz.get("ready")),
        "scan_fresh": bool(readyz.get("scan_fresh")),
        "scheduler_running": bool(readyz.get("scheduler_running")),
        "threshold_evidence_ready": bool(readyz.get("trust_evidence_ready")),
        "critical_pending_due": any(
            (readyz.get(key) or 0) > 0 for key in ("pending_due_15m_count", "pending_due_1h_count", "pending_due_1d_count")
        ),
        "gate_consistency_ok": (gate_consistency.get("mismatch_count", 0) or 0) == 0,
    }
    return {
        "checklist": checklist,
        "execution_counts": execution_counts,
        "operator_review_required": not all(
            (
                checklist["ready"],
                checklist["scan_fresh"],
                checklist["scheduler_running"],
                checklist["threshold_evidence_ready"],
                checklist["gate_consistency_ok"],
            )
        ),
    }


def _evaluate_exit_bar(
    *,
    readyz: dict,
    validation_summary: dict,
    threshold_sweep: dict,
    performance_report: dict,
    execution_alignment: dict,
    gate_consistency: dict,
    paper_lifecycle: dict,
) -> dict[str, object]:
    gate_buckets = {bucket["key"]: bucket for bucket in validation_summary.get("by_signal_and_gate", [])}
    execution_counts = {
        "taken_trades": execution_alignment.get("taken_trades", {}).get("total_signals", 0) or 0,
        "skipped_or_watched": execution_alignment.get("skipped_or_watched", {}).get("total_signals", 0) or 0,
        "blocked_previews": execution_alignment.get("blocked_previews", {}).get("total_signals", 0) or 0,
        "journal_took": execution_alignment.get("journal_took", {}).get("total_signals", 0) or 0,
    }
    non_zero_execution_cohorts = sum(1 for count in execution_counts.values() if count > 0)
    checks = {
        "freshness_ready": bool(readyz.get("ready") and readyz.get("scan_fresh")),
        "threshold_ready": threshold_sweep.get("recommendation", {}).get("evidence_status") == "ready",
        "baseline_passes": bool(performance_report.get("baseline", {}).get("passes_baseline")),
        "buy_passed_min_sample": (gate_buckets.get("BUY:passed", {}).get("evaluated_count", 0) or 0) >= 20,
        "sell_passed_min_sample": (gate_buckets.get("SELL:passed", {}).get("evaluated_count", 0) or 0) >= 20,
        "buy_blocked_min_sample": (gate_buckets.get("BUY:blocked", {}).get("evaluated_count", 0) or 0) >= 10,
        "sell_blocked_min_sample": (gate_buckets.get("SELL:blocked", {}).get("evaluated_count", 0) or 0) >= 10,
        "paper_cohorts_populated": sum(execution_counts.values()) >= 12 and non_zero_execution_cohorts >= 2,
        "paper_submissions_present": (paper_lifecycle.get("submitted_count", 0) or 0) >= 1,
        "gate_consistency_ok": (gate_consistency.get("mismatch_count", 0) or 0) == 0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "execution_counts": execution_counts,
        "non_zero_execution_cohorts": non_zero_execution_cohorts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the scanner trust evidence pack.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8005")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    repo = ScanRepository()
    trust_snapshot = repo.get_trust_readiness_snapshot()
    start = trust_snapshot.window.start.isoformat()
    end = trust_snapshot.window.end.isoformat()
    output_root = (
        Path(args.output_dir)
        if args.output_dir
        else settings.cache_dir_path.parent / "evidence-pack" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    output_root.mkdir(parents=True, exist_ok=True)

    admin_token = settings.admin_api_token or None
    readyz = _http_get_json(args.base_url, "/readyz")
    strategy_contract = _http_get_json(args.base_url, "/strategy/contract")
    scan_cadence = _http_get_json(args.base_url, "/scan/history", params={"limit": "50"})
    validation_summary = _http_get_json(
        args.base_url,
        "/signals/validation/summary",
        params={"start": start, "end": end},
    )
    threshold_sweep = _http_get_json(
        args.base_url,
        "/signals/validation/threshold-sweep",
        params={"start": start, "end": end},
    )
    execution_alignment = _http_get_json(
        args.base_url,
        "/signals/validation/execution-alignment",
        params={"start": start, "end": end},
    )
    performance_report = _http_get_json(
        args.base_url,
        "/signals/outcomes/performance-report",
        params={"start": start, "end": end},
        admin_token=admin_token,
    )
    orders_audits = _http_get_json(args.base_url, "/orders/audits", params={"limit": "100"})
    gate_consistency = _gate_consistency_report()
    paper_lifecycle = _paper_order_lifecycle()

    _write_json(output_root / "db-integrity.json", repo.get_integrity_report())
    _write_json(output_root / "product-thesis.json", _product_thesis())
    _write_json(output_root / "strategy-contract.json", strategy_contract)
    _write_json(output_root / "evidence-policy.json", _evidence_policy(settings=settings, trust_snapshot=trust_snapshot))
    _write_json(output_root / "readyz.json", readyz)
    _write_json(output_root / "scheduler-health.json", _scheduler_health(readyz))
    _write_json(output_root / "scan-cadence.json", scan_cadence)
    _write_json(output_root / "validation-summary-recent.json", validation_summary)
    _write_json(output_root / "threshold-sweep-recent.json", threshold_sweep)
    _write_json(output_root / "performance-report-recent.json", performance_report)
    _write_json(output_root / "execution-alignment-recent.json", execution_alignment)
    _write_json(output_root / "orders-audits-recent.json", orders_audits)
    _write_json(output_root / "orders-audits-sample.json", orders_audits[:25])
    _write_json(output_root / "paper-loop-samples.json", _paper_loop_samples())
    _write_json(output_root / "gate-consistency-report.json", gate_consistency)
    _write_json(output_root / "paper-order-lifecycle.json", paper_lifecycle)
    _write_json(
        output_root / "paper-trading-ops-summary.json",
        _paper_trading_ops_summary(
            readyz=readyz,
            execution_alignment=execution_alignment,
            gate_consistency=gate_consistency,
        ),
    )
    _write_json(
        output_root / "trust-readiness-summary.json",
        _trust_readiness_summary(repo=repo, readyz=readyz, threshold_sweep=threshold_sweep),
    )
    _write_json(
        output_root / "exit-bar.json",
        _evaluate_exit_bar(
            readyz=readyz,
            validation_summary=validation_summary,
            threshold_sweep=threshold_sweep,
            performance_report=performance_report,
            execution_alignment=execution_alignment,
            gate_consistency=gate_consistency,
            paper_lifecycle=paper_lifecycle,
        ),
    )

    test_output_path = output_root / "test-results.txt"
    if args.skip_tests:
        test_output_path.write_text("Skipped by --skip-tests.\n", encoding="utf-8")
    else:
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            capture_output=True,
            text=True,
            check=False,
        )
        test_output_path.write_text(
            f"$ {' '.join(completed.args)}\n\n{completed.stdout}\n{completed.stderr}",
            encoding="utf-8",
        )

    print(output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
