"""Display ordering and operational actionability tiers (host-side).

Decision math (EV after friction, BUY-candidate predicate, candidate rank
score) lives in ``app.brain.gates``; this module only orders rows for display
using operational state (freshness, provider status, eligibility).
"""

from __future__ import annotations

from typing import Protocol

from app.config import Settings
from app.core.freshness_policy import row_is_unusable_or_stale
from app.schemas import DecisionSignal, ScanResult


class RankableRow(Protocol):
    ticker: str
    score: float
    gate_passed: bool
    decision_signal: DecisionSignal
    provider_status: str
    execution_eligibility: str


def _normalize_signal(row: RankableRow, resolve_signal) -> DecisionSignal:
    signal = getattr(row, "decision_signal", None)
    if signal in {"BUY", "SELL", "HOLD"}:
        return signal  # type: ignore[return-value]
    return resolve_signal(row)


def actionability_sort_tier(
    row: RankableRow,
    *,
    settings: Settings,
    resolve_signal,
    scan_result: ScanResult | None = None,
) -> int:
    """
    Lower tier ranks higher.
    0 = clean actionable (gate passed, BUY/SELL, provider ok, fresh, eligible)
    1 = actionable but degraded (review/preview path)
    2 = directional but blocked/stale/critical
    3 = HOLD / flat
    """
    signal = _normalize_signal(row, resolve_signal)
    if signal not in {"BUY", "SELL"}:
        return 3

    provider = (getattr(row, "provider_status", None) or "ok").strip().lower()
    eligibility = (getattr(row, "execution_eligibility", None) or "not_applicable").strip().lower()
    gate_passed = bool(getattr(row, "gate_passed", False))

    stale = False
    if scan_result is not None:
        stale = row_is_unusable_or_stale(scan_result, settings)
    elif getattr(row, "bar_age_minutes", None) is not None:
        age = float(row.bar_age_minutes)  # type: ignore[arg-type]
        stale = age > settings.health_max_stale_minutes

    if (
        gate_passed
        and provider in {"ok", "healthy"}
        and eligibility == "eligible"
        and not stale
    ):
        return 0
    if gate_passed and provider != "critical" and eligibility in {"eligible", "review"} and not stale:
        return 1
    return 2


def display_sort_key(
    row: RankableRow,
    *,
    settings: Settings,
    resolve_signal,
    scan_result: ScanResult | None = None,
) -> tuple[int, int, float, str]:
    tier = actionability_sort_tier(
        row,
        settings=settings,
        resolve_signal=resolve_signal,
        scan_result=scan_result,
    )
    signal = _normalize_signal(row, resolve_signal)
    gate_tier = (
        0
        if getattr(row, "gate_passed", False) and signal in {"BUY", "SELL"}
        else 1
        if signal in {"BUY", "SELL"}
        else 2
    )
    return (tier, gate_tier, -float(getattr(row, "score", 0.0) or 0.0), row.ticker)
