from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.weekly_backtest import PatternBacktestStats
from app.core.weekly_bar_utils import (
    bars_as_of,
    close_price,
    forward_close_after,
    parse_bar_timestamp,
)


def sma(closes: list[float], window: int) -> float | None:
    if len(closes) < window or window <= 0:
        return None
    return sum(closes[-window:]) / window


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for index in range(len(closes) - period, len(closes)):
        delta = closes[index] - closes[index - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    if losses <= 0:
        return 100.0
    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))


def momentum_pct(closes: list[float], lookback: int) -> float | None:
    if len(closes) <= lookback or lookback <= 0:
        return None
    past = closes[-lookback - 1]
    if past <= 0:
        return None
    return (closes[-1] - past) / past * 100.0


def momentum_from_bars(bars: list[dict[str, Any]], as_of: datetime, *, lookback: int) -> float | None:
    visible = bars_as_of(bars, as_of)
    closes = [close_price(bar) for bar in visible if close_price(bar) > 0]
    return momentum_pct(closes, lookback)


def relative_strength_vs_market(
    symbol_bars: list[dict[str, Any]],
    market_bars: list[dict[str, Any]] | None,
    *,
    as_of: datetime,
    lookback: int,
) -> float | None:
    if not market_bars:
        return None
    symbol_return = momentum_from_bars(symbol_bars, as_of, lookback=lookback)
    market_return = momentum_from_bars(market_bars, as_of, lookback=lookback)
    if symbol_return is None or market_return is None:
        return None
    return round(symbol_return - market_return, 4)


def volume_confirmed(
    bars: list[dict[str, Any]],
    as_of: datetime,
    *,
    lookback_days: int,
    min_median_ratio: float,
) -> bool:
    visible = bars_as_of(bars, as_of)
    lookback = max(5, int(lookback_days))
    if len(visible) < lookback * 2:
        return True
    volumes = [float(bar.get("v") or 0.0) for bar in visible]
    recent = volumes[-lookback:]
    baseline = volumes[-lookback * 2 : -lookback]
    if not recent or not baseline:
        return True
    recent_avg = sum(recent) / len(recent)
    baseline_median = sorted(baseline)[len(baseline) // 2]
    if recent_avg <= 0:
        return False
    return recent_avg >= baseline_median * float(min_median_ratio)


def historical_buy_hold_avg_return(
    bars: list[dict[str, Any]],
    *,
    as_of: datetime,
    forward_days: int,
    tolerance_days: int,
    warmup_bars: int,
    step_days: int,
) -> float | None:
    """Average 1-week forward return from historical buy-and-hold entries before as_of."""
    visible = bars_as_of(bars, as_of)
    warmup = max(20, int(warmup_bars))
    step = max(7, int(step_days))
    if len(visible) < warmup + forward_days + tolerance_days + 1:
        return None
    returns: list[float] = []
    for idx in range(warmup, len(visible) - forward_days - tolerance_days, step):
        bar_ts = parse_bar_timestamp(visible[idx].get("t"))
        entry = close_price(visible[idx])
        if entry <= 0:
            continue
        future = forward_close_after(
            visible,
            as_of=bar_ts,
            forward_days=forward_days,
            tolerance_days=tolerance_days,
        )
        if future is None:
            continue
        returns.append(((future - entry) / entry) * 100.0)
    if not returns:
        return None
    return round(sum(returns) / len(returns), 4)


def atr_pct(bars: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    for index in range(len(bars) - period, len(bars)):
        high = float(bars[index].get("h", 0) or 0)
        low = float(bars[index].get("l", 0) or 0)
        prev_close = float(bars[index - 1].get("c", 0) or 0)
        if high <= 0 or low <= 0 or prev_close <= 0:
            continue
        true_range = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(true_range)
    last_close = float(bars[-1].get("c", 0) or 0)
    if not trs or last_close <= 0:
        return None
    return (sum(trs) / len(trs)) / last_close * 100.0


def buy_candidate_reject_reason(
    *,
    bars: list[dict[str, Any]],
    closes: list[float],
    entry_price: float,
    as_of: datetime,
    settings: Any,
    stats: PatternBacktestStats,
    warmup_bars: int,
    step_days: int,
) -> str | None:
    """Shared BUY-candidate quality gate used by both the live path and the proof engine.

    Returns a machine-readable reject reason when the candidate fails a quality
    filter, or None when it clears every filter. Fails closed: any inconclusive
    or weak setup is rejected so the served candidate matches the proven one.
    """
    sma50 = sma(closes, 50)
    if sma50 is not None and entry_price < sma50:
        return "below_sma50"
    relative_strength_index = rsi(closes, 14)
    if relative_strength_index is not None and relative_strength_index >= float(settings.proof_rsi_overbought):
        return "rsi_overbought"
    if stats.sample_size < int(settings.proof_min_pattern_samples):
        return "insufficient_pattern_samples"
    min_hit = 50.0 + float(settings.proof_min_pattern_edge_pct)
    if stats.hit_rate_pct is None or stats.hit_rate_pct < min_hit:
        return "pattern_edge_below_min"
    if stats.avg_forward_return_pct is None or stats.avg_forward_return_pct <= 0:
        return "nonpositive_expectancy"
    buy_hold_avg = historical_buy_hold_avg_return(
        bars,
        as_of=as_of,
        forward_days=int(settings.weekly_forward_days),
        tolerance_days=int(settings.weekly_forward_tolerance_days),
        warmup_bars=warmup_bars,
        step_days=step_days,
    )
    if (
        settings.proof_require_buy_hold_baseline
        and buy_hold_avg is not None
        and stats.avg_forward_return_pct is not None
        and stats.avg_forward_return_pct <= buy_hold_avg
    ):
        return "no_edge_vs_buy_hold"
    if not volume_confirmed(
        bars,
        as_of,
        lookback_days=int(settings.proof_volume_lookback_days),
        min_median_ratio=float(settings.proof_min_volume_median_ratio),
    ):
        return "volume_not_confirmed"
    return None
