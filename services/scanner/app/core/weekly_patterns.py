from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.core.weekly_bar_utils import bars_as_of, close_price, sorted_bars
from app.schemas import DecisionSignal

DirectionalBias = Literal["bullish", "bearish", "neutral"]

# Feature/engineering version for weekly-pattern detection and projection. Bump
# when the feature computation changes so evidence campaigns rotate rather than
# mixing predictions built from incompatible feature logic.
FEATURE_VERSION = "weekly-features-v1"


@dataclass(frozen=True)
class DetectedPattern:
    pattern_name: str
    directional_bias: DirectionalBias
    decision_signal: DecisionSignal
    strength: float


def _sma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _rsi(closes: list[float], period: int = 14) -> float | None:
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


def _rolling_high_low(closes: list[float], window: int) -> tuple[float, float]:
    segment = closes[-window:]
    return max(segment), min(segment)


def detect_weekly_pattern(
    bars: list[dict],
    *,
    as_of: datetime,
) -> DetectedPattern | None:
    usable = bars_as_of(bars, as_of)
    ordered = sorted_bars(usable)
    closes = [close_price(bar) for bar in ordered if close_price(bar) > 0]
    if len(closes) < 20:
        return None

    price = closes[-1]
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    rsi = _rsi(closes, 14)
    rolling_high, rolling_low = _rolling_high_low(closes, 20)
    prior_high, prior_low = _rolling_high_low(closes[:-1], 20) if len(closes) > 21 else (rolling_high, rolling_low)
    momentum_5d = ((price - closes[-6]) / closes[-6]) * 100 if len(closes) >= 6 and closes[-6] > 0 else 0.0
    range_pct = ((rolling_high - rolling_low) / max(price, 0.01)) * 100

    candidates: list[DetectedPattern] = []

    if sma20 is not None and sma50 is not None:
        if price > sma20 > sma50 and momentum_5d > 0:
            candidates.append(
                DetectedPattern(
                    pattern_name="uptrend_ma_stack",
                    directional_bias="bullish",
                    decision_signal="BUY",
                    strength=abs(momentum_5d) + 1.0,
                )
            )
        if price < sma20 < sma50 and momentum_5d < 0:
            candidates.append(
                DetectedPattern(
                    pattern_name="downtrend_ma_stack",
                    directional_bias="bearish",
                    decision_signal="SELL",
                    strength=abs(momentum_5d) + 1.0,
                )
            )

    if price > prior_high and momentum_5d > 0:
        candidates.append(
            DetectedPattern(
                pattern_name="breakout_20d_high",
                directional_bias="bullish",
                decision_signal="BUY",
                strength=abs(momentum_5d) + 2.0,
            )
        )
    if price < prior_low and momentum_5d < 0:
        candidates.append(
            DetectedPattern(
                pattern_name="breakdown_20d_low",
                directional_bias="bearish",
                decision_signal="SELL",
                strength=abs(momentum_5d) + 2.0,
            )
        )

    if rsi is not None:
        if rsi >= 58 and price >= (sma20 or price):
            candidates.append(
                DetectedPattern(
                    pattern_name="momentum_rsi_bull",
                    directional_bias="bullish",
                    decision_signal="BUY",
                    strength=rsi / 10.0,
                )
            )
        if rsi <= 42 and price <= (sma20 or price):
            candidates.append(
                DetectedPattern(
                    pattern_name="momentum_rsi_bear",
                    directional_bias="bearish",
                    decision_signal="SELL",
                    strength=(100.0 - rsi) / 10.0,
                )
            )

    if range_pct <= 6.0 and price > rolling_high * 0.995:
        candidates.append(
            DetectedPattern(
                pattern_name="volatility_squeeze_break",
                directional_bias="bullish",
                decision_signal="BUY",
                strength=3.0,
            )
        )

    if not candidates:
        return DetectedPattern(
            pattern_name="range_neutral",
            directional_bias="neutral",
            decision_signal="HOLD",
            strength=0.0,
        )

    return max(candidates, key=lambda item: item.strength)


def project_weekly_range(
    *,
    price: float,
    pattern: DetectedPattern,
    closes: list[float],
) -> tuple[float, float]:
    entry = max(0.01, float(price))
    if len(closes) >= 10:
        recent = closes[-10:]
        avg_range = sum(abs(recent[index] - recent[index - 1]) for index in range(1, len(recent))) / (len(recent) - 1)
        band = max(avg_range * 3.0, entry * 0.02)
    else:
        band = entry * 0.03

    if pattern.directional_bias == "bullish":
        return round(entry - band * 0.6, 4), round(entry + band * 1.4, 4)
    if pattern.directional_bias == "bearish":
        return round(entry - band * 1.4, 4), round(entry + band * 0.6, 4)
    return round(entry - band, 4), round(entry + band, 4)
