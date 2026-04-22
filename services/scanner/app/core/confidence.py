from __future__ import annotations

from dataclasses import dataclass

from app.core.scoring import clamp
from app.provider_models import (
    BinanceMicrostructureSnapshot,
    BreadthSnapshot,
    DefiLlamaSnapshot,
    DeribitPositioningSnapshot,
    FREDMacroSnapshot,
    SECCatalystSnapshot,
)
from app.schemas import DecisionSignal, OptionsFlowSnapshot


@dataclass(frozen=True)
class ConfidenceOverlay:
    adjusted_confidence: float
    delta: float
    reasons: tuple[str, ...]
    review_flags: tuple[str, ...]


def compute_confidence_overlay(
    *,
    asset_type: str,
    decision_signal: DecisionSignal,
    base_confidence: float,
    market_status: str,
    sentiment_score: float,
    catalyst_score: float,
    options_snapshot: OptionsFlowSnapshot,
    context_bias: float = 0.0,
    provider_status: str = "ok",
    binance_snapshot: BinanceMicrostructureSnapshot | None = None,
    deribit_snapshot: DeribitPositioningSnapshot | None = None,
    sec_snapshot: SECCatalystSnapshot | None = None,
    fred_snapshot: FREDMacroSnapshot | None = None,
    breadth_snapshot: BreadthSnapshot | None = None,
    defillama_snapshot: DefiLlamaSnapshot | None = None,
) -> ConfidenceOverlay:
    delta = 0.0
    reasons: list[str] = []
    review_flags: list[str] = []

    if decision_signal == "HOLD":
        return ConfidenceOverlay(
            adjusted_confidence=round(base_confidence, 2),
            delta=0.0,
            reasons=("hold_signal_no_confidence_overlay",),
            review_flags=(),
        )

    signal_sign = 1 if decision_signal == "BUY" else -1

    if market_status == "bullish" and signal_sign > 0:
        delta += 0.5
        reasons.append("market_regime_supportive")
    elif market_status == "bearish" and signal_sign < 0:
        delta += 0.5
        reasons.append("market_regime_supportive")
    elif market_status == "bullish" and signal_sign < 0:
        delta -= 0.5
        reasons.append("market_regime_headwind")
    elif market_status == "bearish" and signal_sign > 0:
        delta -= 0.5
        reasons.append("market_regime_headwind")

    if sentiment_score * signal_sign >= 0.2:
        delta += 1.0
        reasons.append("directional_news_supportive")
    elif sentiment_score * signal_sign <= -0.2:
        delta -= 1.0
        reasons.append("directional_news_headwind")

    if asset_type == "stock":
        option_bias = options_snapshot.bullish_score - options_snapshot.bearish_score
        if option_bias * signal_sign >= 3:
            delta += 1.0
            reasons.append("options_flow_supportive")
        elif option_bias * signal_sign <= -3:
            delta -= 1.0
            reasons.append("options_flow_headwind")
        if (sec_snapshot and sec_snapshot.catalyst_score >= 0.35) or catalyst_score >= 0.35:
            delta += 0.5
            reasons.append("sec_catalyst_support")

    if asset_type == "crypto":
        if binance_snapshot and binance_snapshot.available:
            if (binance_snapshot.aggressor_pressure or 0.0) * signal_sign >= 0.12:
                delta += 3.5
                reasons.append("binance_aggressor_support")
            elif (binance_snapshot.aggressor_pressure or 0.0) * signal_sign <= -0.12:
                delta -= 3.5
                reasons.append("binance_aggressor_headwind")
            if (binance_snapshot.book_imbalance or 0.0) * signal_sign >= 0.12:
                delta += 2.0
                reasons.append("binance_book_imbalance_support")
            if binance_snapshot.spread_bps is not None and binance_snapshot.spread_bps >= 12:
                delta -= 1.0
                reasons.append("binance_spread_wide")
        if deribit_snapshot and deribit_snapshot.available:
            crowding = deribit_snapshot.crowding_score or 0.0
            if crowding * signal_sign <= -0.4:
                delta -= 8.0
                reasons.append("deribit_crowding_headwind")
                review_flags.append("crypto_crowding_extreme")
            elif crowding * signal_sign >= 0.2:
                delta += 1.5
                reasons.append("deribit_positioning_support")

    if fred_snapshot and fred_snapshot.available:
        if fred_snapshot.regime == "risk_off" and signal_sign > 0:
            delta -= 3.0
            reasons.append("fred_macro_risk_off")
        elif fred_snapshot.regime == "risk_on" and signal_sign > 0:
            delta += 1.5
            reasons.append("fred_macro_risk_on")

    if breadth_snapshot and breadth_snapshot.available:
        buy_balance = breadth_snapshot.buy_balance or 0.0
        sell_balance = breadth_snapshot.sell_balance or 0.0
        breadth_edge = buy_balance - sell_balance
        if breadth_edge * signal_sign >= 8:
            delta += 2.0
            reasons.append("internal_breadth_support")
        elif breadth_edge * signal_sign <= -8:
            delta -= 2.0
            reasons.append("internal_breadth_headwind")

    if defillama_snapshot and defillama_snapshot.available and asset_type == "crypto":
        if (defillama_snapshot.supportive_score or 0.0) * signal_sign >= 0.2:
            delta += 1.5
            reasons.append("defillama_supportive")
        elif (defillama_snapshot.supportive_score or 0.0) * signal_sign <= -0.2:
            delta -= 1.5
            reasons.append("defillama_headwind")

    if context_bias * signal_sign >= 0.12:
        delta += 1.0
        reasons.append("context_bias_supportive")
    elif context_bias * signal_sign <= -0.12:
        delta -= 1.0
        reasons.append("context_bias_headwind")

    if provider_status == "degraded":
        delta -= 1.0
        reasons.append("supportive_provider_degraded")
    elif provider_status == "critical":
        delta -= 4.0
        reasons.append("critical_provider_degraded")

    adjusted_confidence = round(clamp(base_confidence + delta, 0.0, 100.0), 2)
    if not reasons:
        reasons.append("no_secondary_confidence_modifiers")
    return ConfidenceOverlay(
        adjusted_confidence=adjusted_confidence,
        delta=round(delta, 2),
        reasons=tuple(dict.fromkeys(reasons)),
        review_flags=tuple(dict.fromkeys(review_flags)),
    )

