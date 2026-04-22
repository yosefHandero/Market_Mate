from __future__ import annotations

from dataclasses import dataclass

from app.schemas import DecisionSignal, MarketStatus

SCORING_VERSION = "v4.1-integrated"

TREND_SMA_WINDOW = 20
TREND_SCALING_FACTOR = 2.5
TREND_MAX_CONTRIBUTION = 12


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
    buy_contributions: dict[str, float]
    sell_contributions: dict[str, float]
    selected_contributions: dict[str, float]
    buy_reasons: tuple[str, ...] = ()
    sell_reasons: tuple[str, ...] = ()


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
    trend_above_sma: bool = True,
    trend_strength_pct: float = 0.0,
) -> DirectionalScoreResult:
    bullish_momentum = clamp(price_change_pct * 4.2, 0, 18)
    bearish_momentum = clamp((-price_change_pct) * 4.2, 0, 18)
    bullish_relative_strength = clamp(relative_strength_pct * 3.8, 0, 16)
    bearish_relative_weakness = clamp((-relative_strength_pct) * 3.8, 0, 16)
    bullish_structure = (14 if breakout_flag else 0) + (10 if above_vwap else 0) + clamp(close_to_high_pct * 8, 0, 8)
    bearish_structure = (14 if breakdown_flag else 0) + (10 if not above_vwap else 0) + clamp(close_to_low_pct * 8, 0, 8)
    volume_confirmation = clamp((relative_volume - 1.0) * 4.5, 0, 5)
    bullish_alignment = clamp(max((1 if breakout_flag else 0) + (1 if above_vwap else 0) + (1 if price_change_pct >= 0.5 else 0) + (1 if relative_strength_pct >= 0.5 else 0) - 1, 0) * 3, 0, 9)
    bearish_alignment = clamp(max((1 if breakdown_flag else 0) + (1 if not above_vwap else 0) + (1 if price_change_pct <= -0.5 else 0) + (1 if relative_strength_pct <= -0.5 else 0) - 1, 0) * 3, 0, 9)

    if volatility_regime == "hot":
        bullish_momentum *= 1.05
        bearish_momentum *= 1.05
    elif volatility_regime == "extreme":
        bullish_momentum *= 0.85
        bearish_momentum *= 0.85
        bullish_structure *= 0.95
        bearish_structure *= 0.95

    if data_quality == "low":
        volume_confirmation *= 0.5
        bullish_structure *= 0.85
        bearish_structure *= 0.85
    elif data_quality == "degraded":
        volume_confirmation *= 0.8

    # Provider signal terms: bounded additive contributions (~15 pts max per side)
    sentiment_buy = clamp(sentiment_score * 5, 0, 5)       # max +5
    sentiment_sell = clamp(-sentiment_score * 5, 0, 5)      # max +5
    catalyst_buy = clamp(catalyst_score * 3, 0, 3)          # max +3, buy-only
    regime_buy = 3.0 if market_status == "bullish" else 0.0  # max +3
    regime_sell = 3.0 if market_status == "bearish" else 0.0 # max +3
    net_options = options_bullish_score - options_bearish_score
    options_buy = clamp(net_options * 0.5, 0, 4)            # max +4
    options_sell = clamp(-net_options * 0.5, 0, 4)          # max +4

    bullish_trend = clamp(trend_strength_pct * TREND_SCALING_FACTOR, 0, TREND_MAX_CONTRIBUTION)
    bearish_trend = clamp((-trend_strength_pct) * TREND_SCALING_FACTOR, 0, TREND_MAX_CONTRIBUTION)

    buy_confirmations = sum(
        [
            1 if breakout_flag else 0,
            1 if above_vwap else 0,
            1 if close_to_high_pct >= 0.65 else 0,
            1 if relative_strength_pct >= 0.75 else 0,
            1 if relative_volume >= 1.35 else 0,
            1 if trend_above_sma else 0,
        ]
    )
    sell_confirmations = sum(
        [
            1 if breakdown_flag else 0,
            1 if not above_vwap else 0,
            1 if close_to_low_pct >= 0.65 else 0,
            1 if relative_strength_pct <= -0.75 else 0,
            1 if relative_volume >= 1.35 else 0,
            1 if not trend_above_sma else 0,
        ]
    )

    buy_raw = (
        bullish_momentum
        + bullish_relative_strength
        + bullish_structure
        + bullish_alignment
        + volume_confirmation
        + sentiment_buy
        + catalyst_buy
        + regime_buy
        + options_buy
        + bullish_trend
    )
    sell_raw = (
        bearish_momentum
        + bearish_relative_weakness
        + bearish_structure
        + bearish_alignment
        + volume_confirmation
        + sentiment_sell
        + regime_sell
        + options_sell
        + bearish_trend
    )

    buy_score = round(clamp(buy_raw, 0, 100), 2)
    sell_score = round(clamp(sell_raw, 0, 100), 2)
    margin = round(abs(buy_score - sell_score), 2)

    if buy_score >= 52 and (buy_score - sell_score) >= 6:
        decision_signal: DecisionSignal = "BUY"
        selected_score = buy_score
    elif sell_score >= 52 and (sell_score - buy_score) >= 6:
        decision_signal = "SELL"
        selected_score = sell_score
    else:
        decision_signal = "HOLD"
        selected_score = round(max(buy_score, sell_score), 2)

    buy_reasons: list[str] = []
    sell_reasons: list[str] = []
    if breakout_flag:
        buy_reasons.append("breakout_structure")
    if above_vwap:
        buy_reasons.append("above_vwap")
    if close_to_high_pct >= 0.65:
        buy_reasons.append("close_to_high")
    if price_change_pct >= 0.75:
        buy_reasons.append("positive_momentum")
    if relative_strength_pct >= 0.75:
        buy_reasons.append("relative_outperformance")
    if relative_volume >= 1.35:
        buy_reasons.append("volume_confirmation")
    if breakdown_flag:
        sell_reasons.append("breakdown_structure")
    if not above_vwap:
        sell_reasons.append("below_vwap")
    if close_to_low_pct >= 0.65:
        sell_reasons.append("close_to_low")
    if price_change_pct <= -0.75:
        sell_reasons.append("negative_momentum")
    if relative_strength_pct <= -0.75:
        sell_reasons.append("relative_weakness")
    if relative_volume >= 1.35:
        sell_reasons.append("volume_confirmation")
    if sentiment_score >= 0.2:
        buy_reasons.append("positive_news_sentiment")
    if sentiment_score <= -0.2:
        sell_reasons.append("negative_news_sentiment")
    if catalyst_score >= 0.3:
        buy_reasons.append("sec_catalyst")
    if market_status == "bullish":
        buy_reasons.append("bullish_regime")
    if market_status == "bearish":
        sell_reasons.append("bearish_regime")
    if net_options >= 3:
        buy_reasons.append("bullish_options_flow")
    if net_options <= -3:
        sell_reasons.append("bearish_options_flow")
    if trend_above_sma and trend_strength_pct > 0.5:
        buy_reasons.append("price_above_20sma")
    if not trend_above_sma and trend_strength_pct < -0.5:
        sell_reasons.append("price_below_20sma")

    buy_contributions = {
        "momentum": round(bullish_momentum + bullish_relative_strength, 2),
        "structure": round(bullish_structure, 2),
        "volume": round(volume_confirmation, 2),
        "alignment": round(bullish_alignment, 2),
        "signals": round(sentiment_buy + catalyst_buy + regime_buy + options_buy, 2),
        "trend": round(bullish_trend, 2),
    }
    sell_contributions = {
        "momentum": round(bearish_momentum + bearish_relative_weakness, 2),
        "structure": round(bearish_structure, 2),
        "volume": round(volume_confirmation, 2),
        "alignment": round(bearish_alignment, 2),
        "signals": round(sentiment_sell + regime_sell + options_sell, 2),
        "trend": round(bearish_trend, 2),
    }
    if decision_signal == "BUY":
        selected_contributions = buy_contributions
    elif decision_signal == "SELL":
        selected_contributions = sell_contributions
    else:
        selected_contributions = buy_contributions if buy_score >= sell_score else sell_contributions

    return DirectionalScoreResult(
        buy_score=buy_score,
        sell_score=sell_score,
        selected_score=selected_score,
        decision_signal=decision_signal,
        score_margin=margin,
        buy_confirmations=buy_confirmations,
        sell_confirmations=sell_confirmations,
        buy_contributions=buy_contributions,
        sell_contributions=sell_contributions,
        selected_contributions=selected_contributions,
        buy_reasons=tuple(buy_reasons),
        sell_reasons=tuple(sell_reasons),
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
    options_bullish_score: float = 0.0,
    options_bearish_score: float = 0.0,
    trend_above_sma: bool = True,
    trend_strength_pct: float = 0.0,
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
        s_contrib = round(clamp(sentiment_score * 5, 0, 5), 1)
        parts.append(f"news tone is supportive (+{s_contrib:.0f} to buy thesis)" if s_contrib >= 2 else "news tone is supportive")
    elif sentiment_score < -0.15:
        s_contrib = round(clamp(-sentiment_score * 5, 0, 5), 1)
        parts.append(f"news tone is risk-off (+{s_contrib:.0f} to sell thesis)" if s_contrib >= 2 else "news tone is risk-off")

    if catalyst_score >= 0.25:
        c_contrib = round(clamp(catalyst_score * 3, 0, 3), 1)
        parts.append(f"recent filing adds catalyst support (+{c_contrib:.0f})" if c_contrib >= 2 else "a recent filing adds catalyst interest")

    if options_flow_summary:
        parts.append(options_flow_summary.rstrip("."))
    net_opt = options_bullish_score - options_bearish_score
    opt_contrib = round(clamp(abs(net_opt) * 0.5, 0, 4), 1)
    if opt_contrib >= 2:
        opt_side = "buy" if net_opt > 0 else "sell"
        parts.append(f"options flow reinforced {opt_side} thesis (+{opt_contrib:.0f})")

    regime_contrib = 3.0 if market_status in ("bullish", "bearish") else 0.0
    if regime_contrib >= 2:
        parts.append(f"market regime is {market_status} (+{regime_contrib:.0f} to {'buy' if market_status == 'bullish' else 'sell'} thesis)")
    else:
        parts.append(f"market regime is {market_status}")
    if abs(trend_strength_pct) > 0.1:
        direction = "above" if trend_above_sma else "below"
        parts.append(f"price is {abs(trend_strength_pct):.1f}% {direction} the 20-bar moving average")
    if volatility_regime != "normal":
        parts.append(f"volatility regime is {volatility_regime}")
    if gate_reason:
        parts.append(gate_reason.rstrip("."))
    if asset_type == "crypto" and benchmark_label == "BTC/USD":
        parts.append("crypto setup is benchmarked against BTC leadership")
    return "; ".join(parts) + "."
