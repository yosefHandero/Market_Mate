from __future__ import annotations

from dataclasses import dataclass

from app.brain.structural_prediction import build_structural_prediction
from app.schemas import (
    DecisionSignal,
    EvidenceQuality,
    ExitWindow,
    PricePrediction,
    WeeklyPatternPrediction,
)

EvidenceGradeLabel = str

_STOP_GROWING_CONDITIONS: dict[str, list[str]] = {
    "uptrend_ma_stack": [
        "Close falls back below the 20-day moving average.",
        "5-day momentum turns negative.",
    ],
    "breakout_20d_high": [
        "Price closes back below the prior 20-day breakout high.",
        "Breakout fails to hold on rising volume.",
    ],
    "momentum_rsi_bull": [
        "RSI rolls back below 55.",
        "Close drops below the 20-day moving average.",
    ],
    "volatility_squeeze_break": [
        "Price closes back inside the prior squeeze range.",
        "Expansion stalls and range contracts again.",
    ],
}

_DEFAULT_STOP_GROWING_CONDITIONS = [
    "5-day momentum turns negative.",
    "Close falls back below the 20-day moving average.",
]


def _provenance_confidence_note(evidence_basis: str | None) -> str:
    key = (evidence_basis or "insufficient").strip().lower()
    if key == "live_forward_proven":
        return "Backed by live paper-forward evidence."
    if key == "mixed":
        return "Partial live-forward evidence; edge still building."
    if key == "historical_only":
        return "Historical evidence only; not yet live-proven."
    return "Insufficient evidence; confidence may change quickly."


def _exit_risk_warning(
    *,
    evidence_quality: EvidenceQuality | str,
    data_quality: str,
    daily_bars_stale: bool,
    sample_size: int,
) -> str:
    if daily_bars_stale:
        return "Daily history is stale; treat the exit estimate cautiously."
    quality = (data_quality or "ok").strip().lower()
    if quality == "degraded":
        return "Daily history is limited or low quality; low-confidence estimate."
    if sample_size <= 0:
        return "No historical pattern samples yet; range is indicative only."
    grade = (evidence_quality or "low").strip().lower()
    if grade in {"low", "degraded"}:
        return "Evidence is weak; the projected range is indicative only."
    return "Standard market risk applies; upside is not guaranteed."


def build_exit_window(
    *,
    price: float,
    weekly_prediction: WeeklyPatternPrediction | None,
    price_prediction: PricePrediction | None,
    decision_signal: DecisionSignal,
    evidence_quality: EvidenceQuality | str,
    data_quality: str,
    forward_days: int = 7,
) -> ExitWindow | None:
    bullish_weekly = (
        weekly_prediction is not None and weekly_prediction.directional_bias == "bullish"
    )
    if not (bullish_weekly or decision_signal == "BUY"):
        return None

    entry = max(0.01, float(price))
    weekly_high = weekly_prediction.range_high if weekly_prediction is not None else None
    weekly_low = weekly_prediction.range_low if weekly_prediction is not None else None
    structural_target = price_prediction.range_high if price_prediction is not None else None
    structural_stop = price_prediction.range_low if price_prediction is not None else None

    upside_candidates = [
        value for value in (weekly_high, structural_target) if value is not None and value > entry
    ]
    estimated_exit_price = round(min(upside_candidates), 4) if upside_candidates else weekly_high

    invalidation_level = None
    invalidation_note = "No structural stop available."
    if price_prediction is not None:
        invalidation_note = price_prediction.invalidation
    stop_candidates = [
        value for value in (structural_stop, weekly_low) if value is not None and value < entry
    ]
    if stop_candidates:
        invalidation_level = round(max(stop_candidates), 4)

    pattern_name = weekly_prediction.pattern_name if weekly_prediction is not None else ""
    conditions = _STOP_GROWING_CONDITIONS.get(pattern_name, _DEFAULT_STOP_GROWING_CONDITIONS)

    forward = max(1, int(forward_days))
    weeks = max(1, round(forward / 7))
    window_label = f"~{weeks} week{'s' if weeks != 1 else ''} ({forward} trading-day horizon)"

    if estimated_exit_price is not None and estimated_exit_price > entry:
        stop_growing_signal = (
            f"Growth likely to slow near ${estimated_exit_price:.2f} "
            f"(about +{((estimated_exit_price - entry) / entry) * 100:.1f}%)."
        )
    else:
        stop_growing_signal = "Growth expected to slow near the projected range high."

    sample_size = weekly_prediction.sample_size if weekly_prediction is not None else 0
    evidence_basis = weekly_prediction.evidence_basis if weekly_prediction is not None else None

    return ExitWindow(
        expected_growth_window_label=window_label,
        expected_growth_days=forward,
        estimated_exit_price=estimated_exit_price,
        projected_range_low=weekly_low,
        projected_range_high=weekly_high,
        invalidation_level=invalidation_level,
        invalidation_note=invalidation_note,
        stop_growing_signal=stop_growing_signal,
        stop_growing_conditions=list(conditions),
        risk_warning=_exit_risk_warning(
            evidence_quality=evidence_quality,
            data_quality=data_quality,
            daily_bars_stale=(
                weekly_prediction.daily_bars_stale if weekly_prediction is not None else False
            ),
            sample_size=sample_size,
        ),
        confidence_change_note=_provenance_confidence_note(evidence_basis),
    )

_EVIDENCE_GRADE_MAP: dict[str, EvidenceGradeLabel] = {
    "high": "Strong",
    "moderate": "Mixed",
    "low": "Weak",
    "degraded": "Weak",
}

_REASON_LABELS: dict[str, str] = {
    "breakout_structure": "Breakout structure",
    "above_vwap": "Above VWAP",
    "below_vwap": "Below VWAP",
    "close_to_high": "Close to session high",
    "close_to_low": "Close to session low",
    "positive_momentum": "Positive momentum",
    "negative_momentum": "Negative momentum",
    "relative_strength": "Relative strength",
    "relative_weakness": "Relative weakness",
    "volume_confirmation": "Volume confirmation",
    "breakdown_structure": "Breakdown structure",
}


def cap_confidence_by_data_quality(confidence: float, data_quality: str) -> float:
    """Confidence cannot look strong on thin/degraded daily history."""
    value = float(confidence or 0.0)
    quality = (data_quality or "ok").strip().lower()
    if quality == "degraded":
        value = min(value, 40.0)
    elif quality == "low":
        value = min(value, 70.0)
    return round(max(0.0, min(100.0, value)), 2)


def evidence_grade_label(quality: EvidenceQuality | str | None) -> EvidenceGradeLabel:
    key = (quality or "low").strip().lower()
    if key in _EVIDENCE_GRADE_MAP:
        return _EVIDENCE_GRADE_MAP[key]
    return "Weak"


def _humanize_key(key: str) -> str:
    cleaned = key.strip()
    if cleaned in _REASON_LABELS:
        return _REASON_LABELS[cleaned]
    return cleaned.replace("_", " ").title()


def build_top_reasons(
    *,
    directional_reasons: tuple[str, ...] | list[str] | None = None,
    score_contributions: dict[str, float] | None = None,
    evidence_quality_reasons: tuple[str, ...] | list[str] | None = None,
    explanation: str | None = None,
    gate_reason: str | None = None,
    gate_passed: bool = True,
    limit: int = 3,
) -> list[str]:
    reasons: list[str] = []

    contributions = score_contributions or {}
    ranked = sorted(
        ((key, value) for key, value in contributions.items() if isinstance(value, (int, float)) and value != 0),
        key=lambda item: abs(item[1]),
        reverse=True,
    )
    for key, value in ranked:
        reasons.append(f"{_humanize_key(key)} ({value:+.1f})")

    for reason in directional_reasons or ():
        label = _humanize_key(reason)
        if label and label not in reasons:
            reasons.append(label)

    for reason in evidence_quality_reasons or ():
        text = (reason or "").strip()
        if text and text not in reasons:
            reasons.append(text)

    if explanation and explanation.strip():
        text = explanation.strip()
        if text not in reasons:
            reasons.append(text)

    if gate_reason and gate_reason.strip() and not gate_passed:
        text = gate_reason.strip()
        if text not in reasons:
            reasons.append(text)

    unique: list[str] = []
    for reason in reasons:
        cleaned = reason.strip()
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    return unique[:limit]


@dataclass(frozen=True)
class DecisionEnrichment:
    evidence_grade: EvidenceGradeLabel
    top_reasons: list[str]
    price_prediction: PricePrediction


def build_decision_enrichment(
    *,
    price: float,
    decision_signal: DecisionSignal,
    volatility_regime: str,
    horizon: str,
    asset_type: str,
    evidence_quality: EvidenceQuality | str,
    directional_reasons: tuple[str, ...] | list[str] | None = None,
    score_contributions: dict[str, float] | None = None,
    evidence_quality_reasons: tuple[str, ...] | list[str] | None = None,
    explanation: str | None = None,
    gate_reason: str | None = None,
    gate_passed: bool = True,
) -> DecisionEnrichment:
    return DecisionEnrichment(
        evidence_grade=evidence_grade_label(evidence_quality),
        top_reasons=build_top_reasons(
            directional_reasons=directional_reasons,
            score_contributions=score_contributions,
            evidence_quality_reasons=evidence_quality_reasons,
            explanation=explanation,
            gate_reason=gate_reason,
            gate_passed=gate_passed,
        ),
        price_prediction=build_structural_prediction(
            price=price,
            decision_signal=decision_signal,
            volatility_regime=volatility_regime,
            horizon=horizon,
            asset_type=asset_type,
        ),
    )
