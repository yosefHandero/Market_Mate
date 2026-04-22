from __future__ import annotations

from dataclasses import dataclass

from app.core.scoring import build_explanation, compute_directional_scores
from app.core.strategy_contract import STRATEGY_VERSION
from app.schemas import DecisionSignal, MarketStatus, OptionsFlowSnapshot


@dataclass(frozen=True)
class SignalComputation:
    score: float
    buy_score: float
    sell_score: float
    decision_signal: DecisionSignal
    signal_label: str
    explanation: str
    directional_reasons: tuple[str, ...] = ()
    directional_contributions: dict[str, float] | None = None
    scoring_version: str = STRATEGY_VERSION


def compute_signal_and_explanation(
    *,
    ticker: str,
    price: float,
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
    asset_type: str = "stock",
    benchmark_label: str = "SPY/QQQ",
    volatility_regime: str = "normal",
    data_quality: str = "ok",
    context_bias: float = 0.0,
    gate_reason: str | None = None,
    trend_above_sma: bool = True,
    trend_strength_pct: float = 0.0,
) -> SignalComputation:
    directional = compute_directional_scores(
        relative_volume=relative_volume,
        price_change_pct=price_change_pct,
        breakout_flag=breakout_flag,
        breakdown_flag=breakdown_flag,
        above_vwap=above_vwap,
        close_to_high_pct=close_to_high_pct,
        close_to_low_pct=close_to_low_pct,
        sentiment_score=sentiment_score,
        catalyst_score=catalyst_score,
        market_status=market_status,
        relative_strength_pct=relative_strength_pct,
        options_bullish_score=options_snapshot.bullish_score,
        options_bearish_score=options_snapshot.bearish_score,
        volatility_regime=volatility_regime,
        data_quality=data_quality,
        context_bias=context_bias,
        trend_above_sma=trend_above_sma,
        trend_strength_pct=trend_strength_pct,
    )

    if directional.selected_score >= 70 and directional.decision_signal != "HOLD":
        signal_label = "strong"
    elif directional.selected_score >= 58 and directional.decision_signal != "HOLD":
        signal_label = "watch"
    else:
        signal_label = "weak"

    explanation = build_explanation(
        ticker=ticker,
        decision_signal=directional.decision_signal,
        buy_score=directional.buy_score,
        sell_score=directional.sell_score,
        relative_volume=relative_volume,
        price_change_pct=price_change_pct,
        breakout_flag=breakout_flag,
        breakdown_flag=breakdown_flag,
        above_vwap=above_vwap,
        relative_strength_pct=relative_strength_pct,
        sentiment_score=sentiment_score,
        catalyst_score=catalyst_score,
        market_status=market_status,
        options_flow_summary=options_snapshot.summary,
        asset_type=asset_type,
        benchmark_label=benchmark_label,
        volatility_regime=volatility_regime,
        gate_reason=gate_reason,
        options_bullish_score=options_snapshot.bullish_score,
        options_bearish_score=options_snapshot.bearish_score,
        trend_above_sma=trend_above_sma,
        trend_strength_pct=trend_strength_pct,
    )

    return SignalComputation(
        score=directional.selected_score,
        buy_score=directional.buy_score,
        sell_score=directional.sell_score,
        decision_signal=directional.decision_signal,
        signal_label=signal_label,
        explanation=explanation,
        directional_reasons=(
            directional.buy_reasons if directional.decision_signal == "BUY" else directional.sell_reasons
        ),
        directional_contributions=directional.selected_contributions,
    )


def map_score_to_decision_signal(
    *,
    score: float,
    price_change_pct: float,
    decision_signal: DecisionSignal | None = None,
    buy_score: float | None = None,
    sell_score: float | None = None,
    scoring_version: str | None = None,
) -> DecisionSignal:
    if decision_signal in {"BUY", "SELL", "HOLD"}:
        return decision_signal
    if buy_score is not None and sell_score is not None and (buy_score > 0 or sell_score > 0):
        if buy_score >= 60 and (buy_score - sell_score) >= 8:
            return "BUY"
        if sell_score >= 60 and (sell_score - buy_score) >= 8:
            return "SELL"
        return "HOLD"
    if scoring_version and (
        scoring_version.startswith("v2")
        or scoring_version.startswith("v3")
        or scoring_version.startswith("v4")
    ):
        return "HOLD"
    if score >= 75:
        return "BUY"
    if score <= 45 and price_change_pct < 0:
        return "SELL"
    return "HOLD"

