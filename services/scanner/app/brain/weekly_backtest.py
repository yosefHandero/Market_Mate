from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.brain.weekly_bar_utils import (
    bars_as_of,
    close_price,
    forward_close_after,
    parse_bar_timestamp,
    sorted_bars,
)
from app.brain.weekly_patterns import DetectedPattern, detect_weekly_pattern
from app.schemas import SampleSource


@dataclass(frozen=True)
class PatternOutcomeSample:
    pattern_name: str
    directional_bias: str
    decision_signal: str
    entry_price: float
    future_price: float
    return_pct: float
    hit: bool
    as_of: datetime
    sample_source: SampleSource


@dataclass(frozen=True)
class PatternBacktestStats:
    pattern_name: str
    sample_size: int
    hit_rate_pct: float | None
    avg_forward_return_pct: float | None


def _signal_return(*, signal: str, entry_price: float, future_price: float) -> float:
    raw = ((future_price - entry_price) / entry_price) * 100
    if signal == "SELL":
        return raw * -1
    return raw


def _pattern_hit(*, signal: str, return_pct: float, hold_return_tolerance_pct: float = 1.0) -> bool:
    if signal == "BUY":
        return return_pct > 0
    if signal == "SELL":
        return return_pct > 0
    return abs(return_pct) <= hold_return_tolerance_pct


def walk_forward_pattern_samples(
    bars: list[dict],
    *,
    sample_source: SampleSource = "historical",
    warmup_bars: int = 60,
    step_days: int = 7,
    forward_days: int = 7,
    tolerance_days: int = 3,
    hold_return_tolerance_pct: float = 1.0,
) -> list[PatternOutcomeSample]:
    ordered = sorted_bars(bars)
    if len(ordered) <= warmup_bars + 1:
        return []

    start_at = parse_bar_timestamp(ordered[warmup_bars].get("t"))
    end_at = parse_bar_timestamp(ordered[-1].get("t")) - timedelta(days=forward_days + tolerance_days)
    if end_at <= start_at:
        return []

    samples: list[PatternOutcomeSample] = []
    cursor = start_at
    while cursor <= end_at:
        pattern = detect_weekly_pattern(ordered, as_of=cursor)
        if pattern is None:
            cursor += timedelta(days=step_days)
            continue
        usable = bars_as_of(ordered, cursor)
        closes = [close_price(bar) for bar in usable if close_price(bar) > 0]
        if not closes:
            cursor += timedelta(days=step_days)
            continue
        entry_price = closes[-1]
        future_price = forward_close_after(
            ordered,
            as_of=cursor,
            forward_days=forward_days,
            tolerance_days=tolerance_days,
        )
        if future_price is None:
            cursor += timedelta(days=step_days)
            continue
        return_pct = round(
            _signal_return(
                signal=pattern.decision_signal,
                entry_price=entry_price,
                future_price=future_price,
            ),
            4,
        )
        samples.append(
            PatternOutcomeSample(
                pattern_name=pattern.pattern_name,
                directional_bias=pattern.directional_bias,
                decision_signal=pattern.decision_signal,
                entry_price=entry_price,
                future_price=future_price,
                return_pct=return_pct,
                hit=_pattern_hit(
                    signal=pattern.decision_signal,
                    return_pct=return_pct,
                    hold_return_tolerance_pct=hold_return_tolerance_pct,
                ),
                as_of=cursor,
                sample_source=sample_source,
            )
        )
        cursor += timedelta(days=step_days)
    return samples


def summarize_pattern_stats(
    samples: list[PatternOutcomeSample],
    *,
    pattern_name: str | None = None,
) -> PatternBacktestStats:
    filtered = [sample for sample in samples if pattern_name is None or sample.pattern_name == pattern_name]
    if not filtered:
        return PatternBacktestStats(
            pattern_name=pattern_name or "all",
            sample_size=0,
            hit_rate_pct=None,
            avg_forward_return_pct=None,
        )
    hits = sum(1 for sample in filtered if sample.hit)
    returns = [sample.return_pct for sample in filtered]
    return PatternBacktestStats(
        pattern_name=pattern_name or filtered[-1].pattern_name,
        sample_size=len(filtered),
        hit_rate_pct=round((hits / len(filtered)) * 100, 2),
        avg_forward_return_pct=round(sum(returns) / len(returns), 4),
    )
