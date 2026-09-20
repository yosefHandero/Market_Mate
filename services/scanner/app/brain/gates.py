"""Decision gates and candidate ranking math.

Pure decision logic moved out of ``app/core/ranking.py``: expected value after
friction, the BUY-candidate predicate, and the candidate rank score. Display
ordering and operational actionability tiers stay in the host layer.
"""

from __future__ import annotations

from app.config import Settings
from app.schemas import ScanResult

_PROVENANCE_BONUS: dict[str, float] = {
    "live_forward_proven": 8.0,
    "mixed": 4.0,
    "historical_only": 0.0,
    "insufficient": -4.0,
}
_DATA_QUALITY_FACTOR: dict[str, float] = {"ok": 1.0, "low": 0.6, "degraded": 0.3}


def expected_value_after_friction(
    *,
    upside_probability_pct: float | None,
    entry_price: float,
    target_price: float | None,
    invalidation_price: float | None,
    friction_pct: float,
) -> float | None:
    """Probability-weighted expected return after friction, in percent.

    EV = p * upside_move - (1 - p) * downside_move - friction. Used to drop
    candidates whose reward/risk does not clear costs even when the pattern looks
    bullish. Returns None when inputs are insufficient to compute an EV.
    """
    if upside_probability_pct is None or entry_price <= 0:
        return None
    if target_price is None or invalidation_price is None:
        return None
    p = max(0.0, min(1.0, float(upside_probability_pct) / 100.0))
    upside_move = max(0.0, (float(target_price) - entry_price) / entry_price * 100.0)
    downside_move = max(0.0, (entry_price - float(invalidation_price)) / entry_price * 100.0)
    return round(p * upside_move - (1.0 - p) * downside_move - float(friction_pct), 4)


def is_buy_candidate(
    *,
    decision_signal: str | None,
    weekly_directional_bias: str | None,
    upside_probability_pct: float | None,
) -> bool:
    """A row is a buy candidate only if it is BUY-directional and never SELL.

    A bullish weekly pattern with a computed upside probability also qualifies.
    """
    if decision_signal == "SELL":
        return False
    bullish_weekly = weekly_directional_bias == "bullish" and upside_probability_pct is not None
    return bool(decision_signal == "BUY" or bullish_weekly)


def row_is_buy_candidate(row: ScanResult) -> bool:
    weekly = getattr(row, "weekly_prediction", None)
    return is_buy_candidate(
        decision_signal=getattr(row, "decision_signal", "HOLD"),
        weekly_directional_bias=getattr(weekly, "directional_bias", None) if weekly else None,
        upside_probability_pct=getattr(row, "upside_probability_pct", None),
    )


def buy_candidate_rank_score(row: ScanResult, *, settings: Settings) -> float:
    """Higher is better. Blends upside probability with confidence, data quality,
    pattern sample size, and evidence provenance (live-forward ranks above historical)."""
    upside_raw = getattr(row, "upside_probability_pct", None)
    upside = 50.0 if upside_raw is None else float(upside_raw)

    confidence = float(
        getattr(row, "confidence_score", 0.0)
        or getattr(row, "calibrated_confidence", 0.0)
        or 0.0
    )

    weekly = getattr(row, "weekly_prediction", None)
    data_quality = (
        getattr(weekly, "data_quality", None)
        or getattr(row, "data_quality", "ok")
        or "ok"
    ).strip().lower()
    dq_factor = _DATA_QUALITY_FACTOR.get(data_quality, 0.6)

    sample_size = int(getattr(weekly, "sample_size", 0) or 0)
    k = max(1.0, float(getattr(settings, "upside_prob_shrinkage_k", 20.0)))
    sample_factor = sample_size / (sample_size + k)

    provenance = (
        getattr(row, "evidence_provenance", None)
        or getattr(weekly, "evidence_basis", None)
        or "insufficient"
    )
    provenance_bonus = _PROVENANCE_BONUS.get(str(provenance).strip().lower(), 0.0)

    return round(
        upside * 0.5
        + confidence * 0.3
        + dq_factor * 100.0 * 0.1
        + sample_factor * 100.0 * 0.1
        + provenance_bonus,
        4,
    )
