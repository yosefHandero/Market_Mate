"""Pure metric statistics used by the walk-forward engine and live summaries."""

from __future__ import annotations

import math


def calibration_band(predicted: float | None) -> str:
    if predicted is None:
        return "unknown"
    if predicted < 50:
        return "<50"
    if predicted < 60:
        return "50-59"
    if predicted < 70:
        return "60-69"
    if predicted < 80:
        return "70-79"
    if predicted < 90:
        return "80-89"
    return "90-100"


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return round(sorted_values[0], 4)
    rank = pct * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return round(sorted_values[low] * (1 - frac) + sorted_values[high] * frac, 4)


def worst_decile_mean(returns: list[float]) -> float | None:
    if not returns:
        return None
    ordered = sorted(returns)
    count = max(1, len(ordered) // 10)
    return mean(ordered[:count])


def confidence_discrimination_pct(resolved: list[dict]) -> float | None:
    """Realized up-rate of high-confidence picks minus low-confidence picks.

    Splits resolved predictions at the median confidence and returns the
    difference in realized up-rate (percentage points). Positive means higher
    stated confidence tracks better realized outcomes; a value at or below zero
    means the confidence signal is not discriminating and must not add trust.
    """
    scored = [
        (float(p["confidence"]), float(p["return_after_1w"]) > 0)
        for p in resolved
        if p.get("confidence") is not None and p.get("return_after_1w") is not None
    ]
    if len(scored) < 4:
        return None
    scored.sort(key=lambda item: item[0])
    mid = len(scored) // 2
    low = scored[:mid]
    high = scored[mid:]
    if not low or not high:
        return None
    low_rate = sum(1 for _c, up in low if up) / len(low) * 100.0
    high_rate = sum(1 for _c, up in high if up) / len(high) * 100.0
    return round(high_rate - low_rate, 4)


def max_drawdown_pct(ordered_returns: list[float]) -> float | None:
    if not ordered_returns:
        return None
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for ret in ordered_returns:
        equity *= 1.0 + (ret / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            drawdown = (peak - equity) / peak * 100.0
            max_dd = max(max_dd, drawdown)
    return round(max_dd, 4)


def wilson_lower_bound_pct(successes: int, total: int, *, z: float = 1.96) -> float | None:
    """Wilson score 95% lower bound on a proportion, returned as a percentage.

    Used as the honest floor on the realized up-rate: it answers "given this many
    samples, how low could the true rate plausibly be?" A thin sample yields a low
    bound, correctly refusing to certify an edge that has not been earned.
    """
    if total <= 0:
        return None
    phat = successes / total
    denom = 1.0 + (z * z) / total
    center = phat + (z * z) / (2.0 * total)
    margin = z * math.sqrt((phat * (1.0 - phat) + (z * z) / (4.0 * total)) / total)
    return round((center - margin) / denom * 100.0, 4)


def average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def spearman_ic(pairs: list[tuple[float, float]]) -> tuple[float | None, float | None]:
    """Spearman rank information coefficient between signal and realized return.

    Returns (ic, t_stat). IC is the correlation between the predicted upside
    probability and the realized forward return - the core "is there real edge in
    the signal" measure. t_stat > ~2 indicates the correlation is unlikely to be
    noise. Returns (None, None) for underpowered or degenerate samples.
    """
    if len(pairs) < 4:
        return None, None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    rx = average_ranks(xs)
    ry = average_ranks(ys)
    n = len(pairs)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    var_x = sum((rx[i] - mx) ** 2 for i in range(n))
    var_y = sum((ry[i] - my) ** 2 for i in range(n))
    if var_x <= 0 or var_y <= 0:
        return None, None
    ic = cov / math.sqrt(var_x * var_y)
    if abs(ic) >= 1.0 or n <= 2:
        return round(ic, 4), None
    t_stat = ic * math.sqrt((n - 2) / (1.0 - ic * ic))
    return round(ic, 4), round(t_stat, 4)
