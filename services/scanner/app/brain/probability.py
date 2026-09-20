"""Upside probability construction: shrunk historical hit rate + bounded tilt."""

from __future__ import annotations


def compute_upside_probability(
    *,
    hit_rate_pct: float | None,
    sample_size: int,
    directional_bias: str,
    shrinkage_k: float,
    trend_strength_pct: float | None = None,
    relative_strength_pct: float | None = None,
) -> float | None:
    """Probability that price is higher at the end of the growth window.

    Base signal is the detected pattern's historical hit rate, shrunk toward a
    neutral 50% prior by sample size so thin samples cannot look confident. When
    provided, trend strength and relative strength apply a bounded regime-aware
    adjustment so the same pattern reads stronger in a confirming regime and
    weaker in a fading one. Only bullish patterns produce a probability.
    """
    if directional_bias != "bullish":
        return None
    if hit_rate_pct is None or sample_size <= 0:
        base = 50.0
    else:
        n = float(sample_size)
        k = max(0.0, float(shrinkage_k))
        base = 50.0 + (float(hit_rate_pct) - 50.0) * (n / (n + k))

    adjustment = 0.0
    if trend_strength_pct is not None:
        # Each +1% of recent momentum nudges probability up to a small, capped amount.
        adjustment += max(-6.0, min(6.0, float(trend_strength_pct) * 0.6))
    if relative_strength_pct is not None:
        adjustment += max(-4.0, min(4.0, float(relative_strength_pct) * 0.4))
    # Cap the total regime tilt so it refines, never dominates, the sample edge.
    adjustment = max(-8.0, min(8.0, adjustment))
    return round(max(0.0, min(100.0, base + adjustment)), 2)
