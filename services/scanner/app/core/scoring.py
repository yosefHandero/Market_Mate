from __future__ import annotations

from dataclasses import dataclass

from app.schemas import DecisionSignal, MarketStatus

SCORING_VERSION = "v2.1-regime-gated"


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def market_status_from_change(spy_change_pct: float, qqq_change_pct: float) -> MarketStatus:
    avg = (spy_change_pct + qqq_change_pct) / 2
    if avg >= 0.6:
        return "bullish"
    if avg <= -0.6:
        return "bearish"
    return "neutral"


@dataclass(frozen=True)
class DirectionalScoreResult:
    buy_score: float
    sell_score: float
    selected_score: float
    decision_signal: DecisionSignal
    score_margin: float
    buy_confirmations: int
    sell_confirmations: int


def compute_directional_scores(
    *,
    relative_volume: float,
    price_change_pct: float,
    breakout_flag: bool,
    breakdown_flag: bool,
    above_vwap: bool,
    close_to_high_pct: float,
    close_to_low_pct: float,
    sentiment_score: float,
    catalyst_score: float,
    market_status: MarketStatus,
    relative_strength_pct: float,
    options_bullish_score: float,
    options_bearish_score: float,
    volatility_regime: str = "normal",
    data_quality: str = "ok",
    context_bias: float = 0.0,
) -> DirectionalScoreResult:
    volume_component = clamp((relative_volume - 0.8) * 10, 0, 16)
    bullish_momentum = clamp(price_change_pct * 4, 0, 18)
    bearish_momentum = clamp((-price_change_pct) * 4, 0, 18)
    bullish_relative_strength = clamp((relative_strength_pct + 0.3) * 3.5, 0, 12)
    bearish_relative_weakness = clamp(((-relative_strength_pct) + 0.3) * 3.5, 0, 12)
    bullish_sentiment = clamp(max(sentiment_score, 0) * 11, 0, 11)
    bearish_sentiment = clamp(max(-sentiment_score, 0) * 11, 0, 11)
    bullish_market = 10 if market_status == "bullish" else 4 if market_status == "neutral" else 0
    bearish_market = 10 if market_status == "bearish" else 4 if market_status == "neutral" else 0
    bullish_options = clamp(options_bullish_score, 0, 10)
    bearish_options = clamp(options_bearish_score, 0, 10)
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
            1 if options_bullish_score >= 6 else 0,
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
            1 if options_bearish_score >= 6 else 0,
            1 if relative_volume >= 1.35 else 0,
        ]
    )

    buy_raw = (
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
        + clamp(max(buy_confirmations - 1, 0) * 2.5, 0, 10)
    )
    sell_raw = (
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
        + clamp(max(sell_confirmations - 1, 0) * 2.5, 0, 10)
    )

    buy_score = round(clamp(buy_raw, 0, 100), 2)
    sell_score = round(clamp(sell_raw, 0, 100), 2)
    margin = round(abs(buy_score - sell_score), 2)

    if buy_score >= 60 and (buy_score - sell_score) >= 8:
        decision_signal: DecisionSignal = "BUY"
        selected_score = buy_score
    elif sell_score >= 60 and (sell_score - buy_score) >= 8:
        decision_signal = "SELL"
        selected_score = sell_score
    else:
        decision_signal = "HOLD"
        selected_score = round(max(buy_score, sell_score), 2)

    return DirectionalScoreResult(
        buy_score=buy_score,
        sell_score=sell_score,
        selected_score=selected_score,
        decision_signal=decision_signal,
        score_margin=margin,
        buy_confirmations=buy_confirmations,
        sell_confirmations=sell_confirmations,
    )


def build_explanation(
    *,
    ticker: str,
    decision_signal: DecisionSignal,
    buy_score: float,
    sell_score: float,
    relative_volume: float,
    price_change_pct: float,
    breakout_flag: bool,
    breakdown_flag: bool,
    above_vwap: bool,
    relative_strength_pct: float,
    sentiment_score: float,
    catalyst_score: float,
    market_status: MarketStatus,
    options_flow_summary: str,
    asset_type: str = "stock",
    benchmark_label: str = "SPY/QQQ",
    volatility_regime: str = "normal",
    gate_reason: str | None = None,
) -> str:
    parts: list[str] = [
        f"{ticker} has {relative_volume:.2f}x time-aware relative volume",
        f"session move is {price_change_pct:.2f}%",
        f"relative strength vs {benchmark_label} is {relative_strength_pct:.2f}%",
    ]

    if decision_signal == "BUY":
        parts.append(f"bull thesis {buy_score:.1f} vs bear {sell_score:.1f}")
        if breakout_flag:
            parts.append("price is clearing recent resistance")
        if above_vwap:
            parts.append("price is holding above VWAP")
    elif decision_signal == "SELL":
        parts.append(f"bear thesis {sell_score:.1f} vs bull {buy_score:.1f}")
        if breakdown_flag:
            parts.append("price is breaking recent support")
        if not above_vwap:
            parts.append("price is trading below VWAP")
    else:
        parts.append(f"bull thesis {buy_score:.1f} and bear thesis {sell_score:.1f} are too close")

    if sentiment_score > 0.15:
        parts.append("news tone is supportive")
    elif sentiment_score < -0.15:
        parts.append("news tone is risk-off")

    if catalyst_score > 0:
        parts.append("a recent filing adds catalyst risk but not clear direction")

    if options_flow_summary:
        parts.append(options_flow_summary.rstrip("."))

    parts.append(f"market regime is {market_status}")
    if volatility_regime != "normal":
        parts.append(f"volatility regime is {volatility_regime}")
    if gate_reason:
        parts.append(gate_reason.rstrip("."))
    if asset_type == "crypto" and benchmark_label == "BTC/USD":
        parts.append("crypto setup is benchmarked against BTC leadership")
    return "; ".join(parts) + "."
