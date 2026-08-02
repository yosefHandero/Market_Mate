from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReliabilityBin:
    low: float
    high: float
    realized_rate_pct: float
    count: int


def build_reliability_map(
    pairs: list[tuple[float, bool]],
    *,
    n_bins: int = 5,
) -> list[ReliabilityBin]:
    """Build a monotone-ish reliability map from (predicted_probability_pct, realized_up) pairs.

    Bins predicted probabilities into equal-width [0,100] buckets and records the
    realized up-rate per bucket. Intended to be learned on an earlier (research)
    window and applied to a later (holdout) window so it never uses future data.
    """
    clean = [(float(p), bool(up)) for p, up in pairs if p is not None]
    if not clean:
        return []
    bins = max(1, int(n_bins))
    width = 100.0 / bins
    result: list[ReliabilityBin] = []
    for index in range(bins):
        low = index * width
        high = 100.0 if index == bins - 1 else (index + 1) * width
        members = [up for p, up in clean if (p >= low and (p < high or (index == bins - 1 and p <= high)))]
        if not members:
            continue
        realized = sum(1 for up in members if up) / len(members) * 100.0
        result.append(
            ReliabilityBin(low=low, high=high, realized_rate_pct=round(realized, 4), count=len(members))
        )
    return result


def reliability_map_to_payload(reliability_map: list[ReliabilityBin]) -> list[dict[str, float | int]]:
    """Serialize a reliability map for persistence in a run's metrics JSON."""
    return [
        {
            "low": bin_.low,
            "high": bin_.high,
            "realized_rate_pct": bin_.realized_rate_pct,
            "count": bin_.count,
        }
        for bin_ in reliability_map
    ]


def reliability_map_from_payload(
    payload: list[dict] | None,
    *,
    min_count: int = 0,
) -> list[ReliabilityBin]:
    """Rebuild a reliability map from persisted payload, dropping thin bins.

    Bins whose learned sample count is below ``min_count`` are excluded so a raw
    probability that lands in an underpowered bin is served unchanged rather than
    snapped to a statistically meaningless realized rate.
    """
    if not payload:
        return []
    result: list[ReliabilityBin] = []
    for item in payload:
        try:
            count = int(item.get("count", 0))
        except (TypeError, ValueError):
            continue
        if count < max(0, int(min_count)):
            continue
        try:
            result.append(
                ReliabilityBin(
                    low=float(item["low"]),
                    high=float(item["high"]),
                    realized_rate_pct=float(item["realized_rate_pct"]),
                    count=count,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return result


def apply_reliability_map(reliability_map: list[ReliabilityBin], probability_pct: float | None) -> float | None:
    """Map a raw predicted probability to the realized rate of its learned bin."""
    if probability_pct is None or not reliability_map:
        return probability_pct
    value = float(probability_pct)
    for bin_ in reliability_map:
        if value >= bin_.low and (value < bin_.high or bin_.high >= 100.0):
            return bin_.realized_rate_pct
    return probability_pct


def calibrated_mean_abs_gap_pct(
    reliability_map: list[ReliabilityBin],
    holdout_pairs: list[tuple[float, bool]],
) -> float | None:
    """Mean absolute gap between calibrated prediction and realized outcome on holdout.

    A lower value means the research-derived calibration transfers well to the
    held-out window (evidence the probabilities are trustworthy, not overfit).
    """
    clean = [(float(p), bool(up)) for p, up in holdout_pairs if p is not None]
    if not clean:
        return None
    gaps: list[float] = []
    for prob, up in clean:
        calibrated = apply_reliability_map(reliability_map, prob)
        if calibrated is None:
            continue
        gaps.append(abs(calibrated - (100.0 if up else 0.0)))
    if not gaps:
        return None
    return round(sum(gaps) / len(gaps), 4)
