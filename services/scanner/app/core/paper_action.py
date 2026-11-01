"""Existing Decision paper-action checks shared by selection and manual execution.

These checks gate paper workflow access, without changing signal or confidence math.
"""

from app.core.freshness_policy import is_healthy_freshness_flag
from app.core.readiness import FRESH_BAR_MAX_MINUTES, compute_trade_readiness
from app.core.strategy_contract import determine_recommended_action
from app.schemas import GateCheck, ScanResult


PAPER_READY_MIN_SCORE = 70


def paper_action_checks(result: ScanResult) -> list[GateCheck]:
    # Recompute from trusted metadata: a stale recommendation (or client snapshot)
    # must not reopen a blocked or review-only row.
    action = determine_recommended_action(
        signal=result.decision_signal,
        execution_eligibility=result.execution_eligibility,
        evidence_quality=result.evidence_quality,
    )
    readiness = compute_trade_readiness(result.model_copy(update={"recommended_action": action}))
    provider = (result.provider_status or "").strip().lower()
    age = result.bar_age_minutes
    bad_flags = {
        key: value for key, value in (result.freshness_flags or {}).items()
        if not is_healthy_freshness_flag(value)
    }
    return [
        GateCheck(name="paper_buy_signal", passed=result.decision_signal == "BUY",
                  detail=f"signal={result.decision_signal}; required BUY"),
        GateCheck(name="paper_evidence_gate", passed=result.gate_passed,
                  detail=f"evidence gate={result.gate_passed}; required passed"),
        GateCheck(name="paper_recommended_action", passed=action in {"preview", "dry_run"},
                  detail=f"action={action}; required preview or dry_run"),
        GateCheck(name="paper_readiness", passed=readiness.score >= PAPER_READY_MIN_SCORE,
                  detail=f"readiness={readiness.score:g}; minimum {PAPER_READY_MIN_SCORE}"),
        GateCheck(name="paper_hard_stop", passed=not readiness.hard_stop,
                  detail=readiness.reason if readiness.hard_stop else "no hard stop"),
        GateCheck(name="paper_provider", passed=provider not in {"critical", "error"},
                  detail=f"provider={provider}; critical/error block paper action"),
        GateCheck(name="paper_bar_freshness", passed=age is None or age <= FRESH_BAR_MAX_MINUTES,
                  detail=f"bar age={age if age is not None else 'unknown'} minutes; maximum {FRESH_BAR_MAX_MINUTES}"),
        GateCheck(name="paper_data_quality", passed=not bad_flags,
                  detail=(", ".join(f"{key}={value}" for key, value in sorted(bad_flags.items()))
                          if bad_flags else "no blocking market-data flags")),
    ]
