from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.core.freshness_policy import is_healthy_freshness_flag
from app.core.strategy_contract import RecommendedActionLabel, determine_recommended_action
from app.schemas import DecisionRow, GateCheck, ScanResult

FRESH_BAR_MAX_MINUTES = 45

ReadinessTone = Literal["high", "watch", "low", "none"]
ReadinessFactorKey = Literal[
    "signal_confidence",
    "actionability",
    "gate_status",
    "provider_health",
    "freshness",
    "risk_setup",
]
ReadinessProjection = Literal[
    "stable",
    "improving_possible",
    "decaying",
    "blocked_until_sample_size",
    "kill_switch_or_breaker",
]
ReadinessFactorBucket = Literal["system", "market", "safety"]


@dataclass(frozen=True)
class AutomationReadinessContext:
    kill_switch_enabled: bool = False
    breaker_state: str = "closed"


@dataclass(frozen=True)
class ReadinessFactor:
    key: ReadinessFactorKey
    label: str
    score: float
    reason: str
    bucket: ReadinessFactorBucket


@dataclass(frozen=True)
class TradeReadiness:
    score: float
    tone: ReadinessTone
    band: ReadinessTone
    reason: str
    reasons: tuple[str, ...]
    action: RecommendedActionLabel | None
    base_score: float
    factors: tuple[ReadinessFactor, ...]
    projection: ReadinessProjection
    hard_stop: bool


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _rounded(value: float) -> float:
    return round(value * 10_000) / 10_000


def _rounded_score(value: float) -> float:
    return _clamp(round(value), 0, 100)


def _finite_positive(value: object) -> float | None:
    if isinstance(value, (int, float)) and float(value) > 0:
        return float(value)
    return None


def _provider_norm(status: str | None) -> str:
    return (status or "").strip().lower()


def _is_provider_critical(status: str) -> bool:
    return status in {"critical", "error"}


def _is_provider_ok(status: str) -> bool:
    return status in {"ok", "healthy"}


def _evidence_norm(quality: str | None) -> str:
    return (quality or "").strip().lower()


def _is_usable_price(value: object) -> bool:
    return isinstance(value, (int, float)) and float(value) > 0


def _humanize_key(value: str) -> str:
    return value.replace("_", " ")


def _clean_gate_message(value: str | None) -> str | None:
    trimmed = (value or "").strip()
    if not trimmed or trimmed.lower() == "passed":
        return None
    return trimmed


def _bad_freshness_entries(flags: dict[str, str] | None) -> list[tuple[str, str]]:
    if not flags:
        return []
    return [(key, value) for key, value in flags.items() if not is_healthy_freshness_flag(value)]


def _first_bad_freshness_entry(flags: dict[str, str] | None) -> tuple[str, str] | None:
    entries = _bad_freshness_entries(flags)
    return entries[0] if entries else None


def _coalesce_optional[T](primary: T | None, fallback: T | None) -> T | None:
    return primary if primary is not None else fallback


def _merged_freshness_flags(
    result: ScanResult,
    decision: DecisionRow | None,
) -> dict[str, str] | None:
    return _coalesce_optional(result.freshness_flags, decision.freshness_flags if decision else None)


def _merged_provider_status(result: ScanResult, decision: DecisionRow | None) -> str:
    return _provider_norm(
        _coalesce_optional(result.provider_status, decision.provider_status if decision else None)
    )


def _merged_bar_age(result: ScanResult, decision: DecisionRow | None) -> float | None:
    return _coalesce_optional(result.bar_age_minutes, decision.bar_age_minutes if decision else None)


def _selected_action(
    result: ScanResult,
    decision: DecisionRow | None,
) -> RecommendedActionLabel | None:
    if decision and decision.recommended_action:
        return decision.recommended_action
    recommended = getattr(result, "recommended_action", None)
    if recommended:
        return recommended
    return determine_recommended_action(
        signal=result.decision_signal,
        execution_eligibility=result.execution_eligibility,
        evidence_quality=result.evidence_quality,
    )


def _parse_timestamp_ms(value: datetime | str | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value.timestamp() * 1000
        return parsed if parsed == parsed else None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000
        return parsed if parsed == parsed else None
    except ValueError:
        return None


def _base_confidence(result: ScanResult, decision: DecisionRow | None) -> float:
    candidates: list[tuple[float, float | None, str]] = []
    scan_at = _parse_timestamp_ms(result.created_at)
    decision_at = _parse_timestamp_ms(decision.last_updated) if decision else None

    calibrated = _finite_positive(result.calibrated_confidence)
    if calibrated is not None:
        candidates.append((calibrated, scan_at, "calibrated confidence"))
    score = _finite_positive(result.score)
    if score is not None:
        candidates.append((score, scan_at, "score"))
    raw_score = _finite_positive(result.raw_score)
    if raw_score is not None:
        candidates.append((raw_score, scan_at, "raw score"))
    if decision:
        decision_confidence = _finite_positive(decision.confidence)
        if decision_confidence is not None:
            candidates.append((decision_confidence, decision_at, "decision confidence"))

    dated = [candidate for candidate in candidates if candidate[1] is not None]
    if dated:
        dated.sort(key=lambda item: item[1] or 0, reverse=True)
        return _clamp(dated[0][0], 0, 100)

    return _clamp(candidates[0][0], 0, 100) if candidates else 0.0


def _base_confidence_source(result: ScanResult, decision: DecisionRow | None) -> str:
    candidates: list[tuple[str, float | None]] = []
    scan_at = _parse_timestamp_ms(result.created_at)
    decision_at = _parse_timestamp_ms(decision.last_updated) if decision else None
    if _finite_positive(result.calibrated_confidence) is not None:
        candidates.append(("calibrated confidence", scan_at))
    if _finite_positive(result.score) is not None:
        candidates.append(("score", scan_at))
    if _finite_positive(result.raw_score) is not None:
        candidates.append(("raw score", scan_at))
    if decision and _finite_positive(decision.confidence) is not None:
        candidates.append(("decision confidence", decision_at))
    dated = [candidate for candidate in candidates if candidate[1] is not None]
    if dated:
        dated.sort(key=lambda item: item[1] or 0, reverse=True)
        return dated[0][0]
    return candidates[0][0] if candidates else "no positive confidence"


def _finite_bar_age(value: float | None) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _is_fresh_data(
    flags: dict[str, str] | None,
    bar_age_minutes: float | None,
) -> bool:
    age = _finite_bar_age(bar_age_minutes)
    return age is not None and age <= FRESH_BAR_MAX_MINUTES and not _bad_freshness_entries(flags)


def _dry_run_prices(result: ScanResult) -> tuple[float, float, float, Literal["buy", "sell"]]:
    side: Literal["buy", "sell"] = "sell" if result.decision_signal == "SELL" else "buy"
    entry = max(0.01, float(result.price))
    stop = entry * 1.01 if side == "sell" else entry * 0.99
    target = entry * 0.98 if side == "sell" else entry * 1.02
    return _rounded(entry), _rounded(stop), _rounded(target), side


def _risk_structure_valid(
    side: Literal["buy", "sell"],
    entry: float,
    stop: float,
    target: float,
) -> bool:
    if side == "sell":
        return target <= entry and stop >= entry
    return target >= entry and stop <= entry


def _reward_risk_ratio(
    side: Literal["buy", "sell"],
    entry: float,
    stop: float,
    target: float,
) -> float:
    risk_per_unit = abs(entry - stop)
    reward_per_unit = abs(target - entry)
    if risk_per_unit <= 0:
        return 0.0
    return reward_per_unit / risk_per_unit


def _failed_gate_checks(result: ScanResult) -> list[GateCheck]:
    return [check for check in (result.gate_checks or []) if not check.passed]


def _is_sample_size_only_blocked(result: ScanResult) -> bool:
    if result.gate_passed is not False:
        return False
    failed = _failed_gate_checks(result)
    if not failed:
        return bool(re.search(r"sample[_ -]?size", result.gate_reason or "", re.IGNORECASE))
    return all(
        re.search(r"sample[_ -]?size", f"{check.name} {check.detail}", re.IGNORECASE)
        for check in failed
    )


def _is_hold_gate_not_applicable(result: ScanResult, decision: DecisionRow | None) -> bool:
    if result.decision_signal != "HOLD":
        return False
    gate_failed = result.gate_passed is False or (decision.gate_passed is False if decision else False)
    if not gate_failed:
        return False
    return not _failed_gate_checks(result)


def _action_cap(action: RecommendedActionLabel | None) -> float:
    if action in {"preview", "dry_run"}:
        return 100.0
    if action == "review":
        return 65.0
    if action == "blocked":
        return 35.0
    if action == "ignore":
        return 30.0
    return 40.0


def _factor_bucket(key: ReadinessFactorKey) -> ReadinessFactorBucket:
    if key in {"provider_health", "freshness"}:
        return "system"
    if key in {"gate_status", "actionability"}:
        return "safety"
    return "market"


def _with_bucket(
    *,
    key: ReadinessFactorKey,
    label: str,
    score: float,
    reason: str,
) -> ReadinessFactor:
    return ReadinessFactor(
        key=key,
        label=label,
        score=score,
        reason=reason,
        bucket=_factor_bucket(key),
    )


def _action_score(action: RecommendedActionLabel | None) -> ReadinessFactor:
    if action in {"preview", "dry_run"}:
        return _with_bucket(
            key="actionability",
            label="Actionability",
            score=100.0,
            reason="Paper preview or dry-run is selectable.",
        )
    if action == "review":
        return _with_bucket(
            key="actionability",
            label="Actionability",
            score=65.0,
            reason="Review/watch action caps readiness at 65.",
        )
    if action == "blocked":
        return _with_bucket(
            key="actionability",
            label="Actionability",
            score=35.0,
            reason="Blocked action caps readiness at 35.",
        )
    if action == "ignore":
        return _with_bucket(
            key="actionability",
            label="Actionability",
            score=30.0,
            reason="Ignore caps readiness at 30.",
        )
    return _with_bucket(
        key="actionability",
        label="Actionability",
        score=40.0,
        reason="Missing or unknown action caps readiness at 40.",
    )


def _gate_score(result: ScanResult, decision: DecisionRow | None) -> ReadinessFactor:
    gate_failed = result.gate_passed is False or (decision.gate_passed is False if decision else False)

    if not gate_failed and (result.gate_passed or (decision.gate_passed if decision else False)):
        return _with_bucket(
            key="gate_status",
            label="Gate status",
            score=100.0,
            reason="Configured trade gates passed.",
        )
    if _is_sample_size_only_blocked(result):
        return _with_bucket(
            key="gate_status",
            label="Gate status",
            score=35.0,
            reason="Only the sample-size gate is blocking confidence.",
        )
    if result.decision_signal == "HOLD":
        return _with_bucket(
            key="gate_status",
            label="Gate status",
            score=35.0,
            reason="Gate is not actionable while the signal is HOLD.",
        )
    if gate_failed:
        failed = _failed_gate_checks(result)
        detail = failed[0].detail if failed else None
        return _with_bucket(
            key="gate_status",
            label="Gate status",
            score=35.0,
            reason=_clean_gate_message(result.gate_reason) or detail or "One or more gates failed.",
        )
    return _with_bucket(
        key="gate_status",
        label="Gate status",
        score=60.0,
        reason="Gate state is unavailable.",
    )


def _provider_score(status: str) -> ReadinessFactor:
    if _is_provider_ok(status):
        return _with_bucket(
            key="provider_health",
            label="Provider health",
            score=100.0,
            reason="Provider status is OK.",
        )
    if status == "degraded":
        return _with_bucket(
            key="provider_health",
            label="Provider health",
            score=80.0,
            reason="Provider is degraded, applying a penalty rather than a hard stop.",
        )
    if _is_provider_critical(status):
        return _with_bucket(
            key="provider_health",
            label="Provider health",
            score=40.0,
            reason=f"Provider status is {status}.",
        )
    return _with_bucket(
        key="provider_health",
        label="Provider health",
        score=60.0,
        reason="Provider status is unknown.",
    )


def _freshness_score(
    flags: dict[str, str] | None,
    bar_age_minutes: float | None,
) -> ReadinessFactor:
    bad_entries = _bad_freshness_entries(flags)
    age = _finite_bar_age(bar_age_minutes)
    score = 100.0
    reasons: list[str] = []

    if bad_entries:
        penalty = min(len(bad_entries) * 5, 15)
        score -= penalty
        key, value = bad_entries[0]
        reasons.append(f"{len(bad_entries)} freshness flag{'s' if len(bad_entries) != 1 else ''}")
        reasons.append(f"{_humanize_key(key)}: {value}")

    if age is not None:
        if age > FRESH_BAR_MAX_MINUTES:
            score -= 10
            reasons.append(f"bars {round(age)}m old")
        if age > 120:
            score = min(score, 30.0)
        if age > 1440:
            score = min(score, 10.0)
    else:
        reasons.append("Bar age is unavailable.")

    return _with_bucket(
        key="freshness",
        label="Freshness",
        score=_clamp(score, 0, 100),
        reason=" | ".join(reasons) if reasons else "Data freshness is OK.",
    )


def _risk_penalty(result: ScanResult) -> tuple[float, str | None]:
    if not _is_usable_price(result.price) or result.decision_signal not in {"BUY", "SELL", "HOLD"}:
        return 12.0, "Risk setup structure is incomplete."

    entry, stop, target, side = _dry_run_prices(result)
    if not _risk_structure_valid(side, entry, stop, target):
        return 12.0, "Derived stop/target structure is not valid."

    if _reward_risk_ratio(side, entry, stop, target) < 1:
        return 4.0, "Reward/risk is below 1:1."

    return 0.0, None


def _risk_score(result: ScanResult) -> ReadinessFactor:
    if not _is_usable_price(result.price) or result.decision_signal not in {"BUY", "SELL", "HOLD"}:
        return _with_bucket(
            key="risk_setup",
            label="Risk setup",
            score=0.0,
            reason="Missing a usable price or known signal.",
        )

    entry, stop, target, side = _dry_run_prices(result)
    if not _risk_structure_valid(side, entry, stop, target):
        return _with_bucket(
            key="risk_setup",
            label="Risk setup",
            score=88.0,
            reason="Derived stop/target structure is not valid.",
        )

    rr = _reward_risk_ratio(side, entry, stop, target)
    if rr < 1:
        return _with_bucket(
            key="risk_setup",
            label="Risk setup",
            score=96.0,
            reason="Reward/risk is below 1:1.",
        )

    return _with_bucket(
        key="risk_setup",
        label="Risk setup",
        score=100.0,
        reason="Derived paper risk structure is usable.",
    )


def _evidence_penalty(
    result: ScanResult,
    decision: DecisionRow | None,
) -> tuple[float, list[str]]:
    eq = _evidence_norm(result.evidence_quality)
    quality_reasons = list(result.evidence_quality_reasons or [])
    if not quality_reasons and decision:
        quality_reasons = list(decision.evidence_quality_reasons or [])
    penalty = 0.0
    reasons: list[str] = []

    if eq == "low":
        penalty += 8.0
        reasons.append("Low evidence quality subtracts 8.")
    elif eq == "moderate":
        penalty += 2.0
        reasons.append("Moderate evidence quality subtracts 2.")
    if len(quality_reasons) > 2:
        penalty += 4.0
        reasons.append("More than two evidence reasons subtracts 4.")

    return penalty, reasons


def _signal_factor(
    base_score: float,
    result: ScanResult,
    decision: DecisionRow | None,
) -> ReadinessFactor:
    evidence_penalty, _ = _evidence_penalty(result, decision)
    score = max(0.0, base_score - evidence_penalty)
    source = _base_confidence_source(result, decision)
    return _with_bucket(
        key="signal_confidence",
        label="Signal confidence",
        score=score,
        reason=(
            f"Base confidence {round(base_score)} from {source}."
            if base_score > 0
            else "No positive confidence value was available."
        ),
    )


def _hard_stop_reason(
    result: ScanResult,
    provider: str,
    bar_age_minutes: float | None,
    automation: AutomationReadinessContext | None,
) -> str | None:
    if automation and automation.kill_switch_enabled:
        return "Hard stop: kill switch is active."
    if automation and automation.breaker_state == "open":
        return "Hard stop: automation circuit breaker is open."
    if not _is_usable_price(result.price):
        return "Hard stop: missing or invalid trigger price."
    age = _finite_bar_age(bar_age_minutes)
    if _is_provider_critical(provider) and age is not None and age > 360:
        return "Hard stop: provider is critical and bars are stale over 6 hours."
    return None


def _pick_readiness_reason(
    result: ScanResult,
    decision: DecisionRow | None,
    hard_stop: str | None,
    action: RecommendedActionLabel | None,
) -> str:
    if hard_stop:
        return hard_stop

    provider = _merged_provider_status(result, decision)
    flags = _merged_freshness_flags(result, decision)
    bar_age = _merged_bar_age(result, decision)

    if _is_hold_gate_not_applicable(result, decision):
        return "Low actionability: HOLD signal with usable data."

    if action == "blocked" or result.gate_passed is False:
        if _is_sample_size_only_blocked(result):
            return "Low trust: blocked only by sample size, not by a hard safety stop."
        failed = _failed_gate_checks(result)
        msg = (
            _clean_gate_message(result.gate_reason)
            or (_clean_gate_message(failed[0].detail) if failed else None)
            or "Gate checks did not pass."
        )
        return f"Blocked: {msg}"

    if result.decision_signal == "HOLD":
        return "Low actionability: HOLD signal with usable data."
    if action == "ignore":
        return "Low actionability: ignored by recommended action."
    if action == "review":
        return "Watch only: review pending."

    if _is_provider_critical(provider):
        return f"Low trust: provider {provider}."
    if provider == "degraded":
        return "Watch closely: provider is degraded."

    stale_bars = bar_age is not None and bar_age > FRESH_BAR_MAX_MINUTES
    if stale_bars:
        return f"Stale data: bars {round(bar_age)}m old."

    bad_fresh = _first_bad_freshness_entry(flags)
    if bad_fresh:
        return f"Stale data: {_humanize_key(bad_fresh[0])}: {bad_fresh[1]}."

    return "Actionable: gates passed and data is fresh."


def _pick_projection(
    *,
    result: ScanResult,
    action: RecommendedActionLabel | None,
    provider: str,
    freshness: ReadinessFactor,
    hard_stop: bool,
    automation: AutomationReadinessContext | None,
) -> ReadinessProjection:
    if automation and (
        automation.kill_switch_enabled or automation.breaker_state == "open"
    ):
        return "kill_switch_or_breaker"
    if _is_sample_size_only_blocked(result):
        return "blocked_until_sample_size"
    if provider == "degraded" or _is_provider_critical(provider) or freshness.score < 60:
        return "decaying"
    if action in {"review", "blocked"}:
        return "improving_possible"
    if hard_stop:
        return "decaying"
    return "stable"


def _apply_floors(
    *,
    score: float,
    result: ScanResult,
    provider: str,
    action: RecommendedActionLabel | None,
    flags: dict[str, str] | None,
    bar_age: float | None,
) -> float:
    floored = score
    non_critical_provider = not _is_provider_critical(provider)
    fresh = _is_fresh_data(flags, bar_age)

    if _is_usable_price(result.price) and non_critical_provider:
        floored = max(floored, 8.0)

    if _is_sample_size_only_blocked(result) and fresh and _is_provider_ok(provider):
        floored = max(floored, 15.0)

    if (result.decision_signal == "HOLD" or action == "ignore") and fresh and _is_provider_ok(provider):
        floored = max(floored, 12.0)

    return floored


def readiness_tone(score: float) -> ReadinessTone:
    rounded = _rounded_score(score)
    if rounded >= 70:
        return "high"
    if rounded >= 50:
        return "watch"
    if rounded >= 25:
        return "low"
    return "none"


def compute_trade_readiness(
    result: ScanResult,
    decision: DecisionRow | None = None,
    *,
    automation: AutomationReadinessContext | None = None,
) -> TradeReadiness:
    action = _selected_action(result, decision)
    base_score = _base_confidence(result, decision)
    provider = _merged_provider_status(result, decision)
    bar_age = _merged_bar_age(result, decision)
    hard_stop = _hard_stop_reason(result, provider, bar_age, automation)

    signal = _signal_factor(base_score, result, decision)
    actionability = _action_score(action)
    gate = _gate_score(result, decision)
    provider_health = _provider_score(provider)
    freshness_flags = _merged_freshness_flags(result, decision)
    freshness = _freshness_score(freshness_flags, bar_age)
    risk = _risk_score(result)
    factors = (signal, actionability, gate, provider_health, freshness, risk)

    score = base_score
    reasons: list[str] = []
    cap = _action_cap(action)

    if score > cap:
        reasons.append(f"Action cap limited readiness to {int(cap)}.")
    score = min(score, cap)

    sample_size_only = _is_sample_size_only_blocked(result)
    gate_failed = result.gate_passed is False or (decision.gate_passed is False if decision else False)
    if gate_failed and not sample_size_only and not _is_hold_gate_not_applicable(result, decision):
        score *= 0.6
        score = min(score, 35.0)
        reasons.append("Non-sample-size gate failure applied a 0.6 multiplier and 35 cap.")

    if _is_provider_critical(provider):
        score *= 0.4
        reasons.append(f"Provider {provider or 'critical'} applied a 0.4 multiplier.")
    elif provider == "degraded":
        score *= 0.8
        reasons.append("Provider degraded applied a 0.8 multiplier.")

    bad_freshness = _bad_freshness_entries(freshness_flags)
    if bad_freshness:
        freshness_penalty = min(len(bad_freshness) * 5, 15)
        score -= freshness_penalty
        reasons.append(
            f"{len(bad_freshness)} freshness flag{'s' if len(bad_freshness) != 1 else ''} "
            f"subtracted {freshness_penalty}."
        )

    finite_age = _finite_bar_age(bar_age)
    if finite_age is not None and finite_age > FRESH_BAR_MAX_MINUTES:
        score -= 10
        reasons.append(f"Bars {round(finite_age)}m old subtracted 10.")
    if finite_age is not None and finite_age > 120:
        score = min(score, 30.0)
        reasons.append("Bars older than 120m capped readiness at 30.")
    if finite_age is not None and finite_age > 1440:
        score = min(score, 10.0)
        reasons.append("Bars older than 24h capped readiness at 10.")

    evidence_penalty, evidence_reasons = _evidence_penalty(result, decision)
    if evidence_penalty > 0:
        score -= evidence_penalty
        reasons.extend(evidence_reasons)

    risk_penalty, risk_reason = _risk_penalty(result)
    if risk_penalty > 0:
        score -= risk_penalty
        if risk_reason:
            reasons.append(f"{risk_reason} Subtracted {int(risk_penalty)}.")

    score = _clamp(score, 0, 100)
    score = _apply_floors(
        score=score,
        result=result,
        provider=provider,
        action=action,
        flags=freshness_flags,
        bar_age=bar_age,
    )
    score = min(score, cap)

    if hard_stop:
        score = 0.0

    score = _rounded_score(score)
    tone = readiness_tone(score)
    primary_reason = _pick_readiness_reason(result, decision, hard_stop, action)
    all_reasons = list(dict.fromkeys([primary_reason, *reasons]))
    projection = _pick_projection(
        result=result,
        action=action,
        provider=provider,
        freshness=freshness,
        hard_stop=bool(hard_stop),
        automation=automation,
    )

    return TradeReadiness(
        score=score,
        tone=tone,
        band=tone,
        reason=primary_reason,
        reasons=tuple(all_reasons),
        action=action,
        base_score=_rounded_score(base_score),
        factors=tuple(
            ReadinessFactor(
                key=factor.key,
                label=factor.label,
                score=_rounded_score(factor.score),
                reason=factor.reason,
                bucket=factor.bucket,
            )
            for factor in factors
        ),
        projection=projection,
        hard_stop=bool(hard_stop),
    )
