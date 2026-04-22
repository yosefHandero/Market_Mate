from __future__ import annotations

from dataclasses import dataclass

from app.core.scoring import clamp
from app.schemas import DecisionSignal, MarketStatus, OptionsFlowSnapshot


@dataclass(frozen=True)
class LegacySignalComputation:
    score: float
    buy_score: float
    sell_score: float
    decision_signal: DecisionSignal
    signal_label: str
    scoring_version: str = "v3.0-explicit"


def compute_legacy_signal(
    *,
    price_change_pct: float,
    relative_volume: float,
    breakout_flag: bool,
    breakdown_flag: bool,
    above_vwap: bool,
    close_to_high_pct: float,
    close_to_low_pct: float,
    sentiment_score: float,
    catalyst_score: float,
    market_status: MarketStatus,
    relative_strength_pct: float,
    options_snapshot: OptionsFlowSnapshot,
    volatility_regime: str = "normal",
    data_quality: str = "ok",
    context_bias: float = 0.0,
) -> LegacySignalComputation:
    volume_component = clamp((relative_volume - 0.8) * 10, 0, 16)
    bullish_momentum = clamp(price_change_pct * 4, 0, 18)
    bearish_momentum = clamp((-price_change_pct) * 4, 0, 18)
    bullish_relative_strength = clamp((relative_strength_pct + 0.3) * 3.5, 0, 12)
    bearish_relative_weakness = clamp(((-relative_strength_pct) + 0.3) * 3.5, 0, 12)
    bullish_sentiment = clamp(max(sentiment_score, 0) * 11, 0, 11)
    bearish_sentiment = clamp(max(-sentiment_score, 0) * 11, 0, 11)
    bullish_market = 10 if market_status == "bullish" else 4 if market_status == "neutral" else 0
    bearish_market = 10 if market_status == "bearish" else 4 if market_status == "neutral" else 0
    bullish_options = clamp(options_snapshot.bullish_score, 0, 10)
    bearish_options = clamp(options_snapshot.bearish_score, 0, 10)
    neutral_catalyst = clamp(catalyst_score * 6, 0, 4)
    bullish_context = clamp(max(context_bias, 0) * 8, 0, 8)
    bearish_context = clamp(max(-context_bias, 0) * 8, 0, 8)

    if volatility_regime == "hot":
        bullish_momentum *= 1.05
        bearish_momentum *= 1.05
    elif volatility_regime == "extreme":
        bullish_momentum *= 0.85
        bearish_momentum *= 0.85
        volume_component *= 0.9

    if data_quality == "low":
        volume_component *= 0.6
        bullish_options *= 0.75
        bearish_options *= 0.75
    elif data_quality == "degraded":
        volume_component *= 0.8

    buy_confirmations = sum(
        [
            1 if breakout_flag else 0,
            1 if above_vwap else 0,
            1 if close_to_high_pct >= 0.65 else 0,
            1 if relative_strength_pct >= 0.75 else 0,
            1 if sentiment_score >= 0.2 else 0,
            1 if options_snapshot.bullish_score >= 6 else 0,
            1 if relative_volume >= 1.35 else 0,
        ]
    )
    sell_confirmations = sum(
        [
            1 if breakdown_flag else 0,
            1 if not above_vwap else 0,
            1 if close_to_low_pct >= 0.65 else 0,
            1 if relative_strength_pct <= -0.75 else 0,
            1 if sentiment_score <= -0.2 else 0,
            1 if options_snapshot.bearish_score >= 6 else 0,
            1 if relative_volume >= 1.35 else 0,
        ]
    )
    buy_score = round(
        clamp(
            volume_component
            + bullish_momentum
            + bullish_relative_strength
            + (12 if breakout_flag else 0)
            + (8 if above_vwap else 0)
            + clamp(close_to_high_pct * 8, 0, 8)
            + bullish_sentiment
            + bullish_market
            + bullish_options
            + neutral_catalyst
            + bullish_context
            + clamp(max(buy_confirmations - 1, 0) * 2.5, 0, 10),
            0,
            100,
        ),
        2,
    )
    sell_score = round(
        clamp(
            volume_component
            + bearish_momentum
            + bearish_relative_weakness
            + (12 if breakdown_flag else 0)
            + (8 if not above_vwap else 0)
            + clamp(close_to_low_pct * 8, 0, 8)
            + bearish_sentiment
            + bearish_market
            + bearish_options
            + neutral_catalyst
            + bearish_context
            + clamp(max(sell_confirmations - 1, 0) * 2.5, 0, 10),
            0,
            100,
        ),
        2,
    )
    if buy_score >= 60 and (buy_score - sell_score) >= 8:
        decision_signal: DecisionSignal = "BUY"
        score = buy_score
    elif sell_score >= 60 and (sell_score - buy_score) >= 8:
        decision_signal = "SELL"
        score = sell_score
    else:
        decision_signal = "HOLD"
        score = round(max(buy_score, sell_score), 2)
    signal_label = "strong" if score >= 80 and decision_signal != "HOLD" else "watch" if score >= 65 and decision_signal != "HOLD" else "weak"
    return LegacySignalComputation(
        score=score,
        buy_score=buy_score,
        sell_score=sell_score,
        decision_signal=decision_signal,
        signal_label=signal_label,
    )

