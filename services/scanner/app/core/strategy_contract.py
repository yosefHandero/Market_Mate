from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.schemas import DecisionSignal

StrategyIntent = Literal["long", "short", "flat"]
EvidenceQualityLabel = Literal["high", "moderate", "low", "degraded"]
ExecutionEligibilityLabel = Literal["eligible", "blocked", "not_applicable", "review"]
DataGradeLabel = Literal["decision", "research", "degraded"]

STRATEGY_ID = "scanner-directional"
STRATEGY_VERSION = "v4.1-integrated"
PRIMARY_HOLDING_HORIZON = "1h"
ENTRY_ASSUMPTION = (
    "Assume the position is entered on the next available trade after the scan snapshot. "
    "Validation remains direction-based and does not claim perfect fills."
)
EXIT_ASSUMPTION = (
    "Primary validation measures forward returns over fixed 15m, 1h, and 1d horizons. "
    "This is not yet a stop-loss or target-based exit system."
)


@dataclass(frozen=True)
class StrategySignalDefinition:
    signal: DecisionSignal
    intent: StrategyIntent
    operational_meaning: str


@dataclass(frozen=True)
class StrategyContract:
    strategy_id: str
    strategy_version: str
    name: str
    primary_holding_horizon: str
    entry_assumption: str
    exit_assumption: str
    buy_definition: StrategySignalDefinition
    sell_definition: StrategySignalDefinition
    hold_definition: StrategySignalDefinition
    evidence_inputs: tuple[str, ...]
    critical_provider_inputs: tuple[str, ...]
    supportive_provider_inputs: tuple[str, ...]
    known_limitations: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceQualityAssessment:
    label: EvidenceQualityLabel
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class StrategyEvaluationMetadata:
    strategy_id: str
    strategy_version: str
    primary_holding_horizon: str
    entry_assumption: str
    exit_assumption: str
    evidence_quality: EvidenceQualityLabel
    evidence_quality_score: float
    evidence_quality_reasons: tuple[str, ...]
    data_grade: DataGradeLabel
    execution_eligibility: ExecutionEligibilityLabel
    confidence_label: str = "calibrated_confidence"


CURRENT_STRATEGY_CONTRACT = StrategyContract(
    strategy_id=STRATEGY_ID,
    strategy_version=STRATEGY_VERSION,
    name="Directional intraday scanner with evidence gate",
    primary_holding_horizon=PRIMARY_HOLDING_HORIZON,
    entry_assumption=ENTRY_ASSUMPTION,
    exit_assumption=EXIT_ASSUMPTION,
    buy_definition=StrategySignalDefinition(
        signal="BUY",
        intent="long",
        operational_meaning=(
            "Directional long thesis. The system expects upside over the configured validation horizon "
            "if the setup stays valid and the evidence gate remains supportive."
        ),
    ),
    sell_definition=StrategySignalDefinition(
        signal="SELL",
        intent="short",
        operational_meaning=(
            "Directional short thesis. The system expects downside over the configured validation horizon "
            "if the setup stays valid and the evidence gate remains supportive."
        ),
    ),
    hold_definition=StrategySignalDefinition(
        signal="HOLD",
        intent="flat",
        operational_meaning=(
            "No directional edge is strong enough to support action. HOLD means abstain, not weak conviction."
        ),
    ),
    evidence_inputs=(
        "price_change_pct",
        "breakout_or_breakdown",
        "vwap_context",
        "relative_strength_pct",
        "volatility_regime",
        "data_quality",
        "provider_status",
        "directional_news",
        "options_flow",
        "sec_catalyst",
        "binance_microstructure",
        "deribit_positioning",
        "fred_macro_regime",
        "internal_breadth",
        "defillama_macro_breadth",
    ),
    critical_provider_inputs=("alpaca_market_bars",),
    supportive_provider_inputs=(
        "marketaux",
        "finnhub",
        "sec",
        "options_flow",
        "coingecko",
        "fear_greed",
        "binance",
        "deribit",
        "fred",
        "internal_breadth",
        "defillama",
    ),
    known_limitations=(
        "The strategy is direction-based and does not yet model limit-order queue position or exact fills.",
        "Current validation is recent-window based and should not be treated as a substitute for full walk-forward proof.",
        "A calibrated confidence value is not a probability of profit.",
        "Sentiment, catalyst, regime, and options flow contribute bounded terms (max ~15 points) to the directional score. Remaining secondary providers (Binance, Deribit, FRED, DeFi Llama, breadth) still operate as confidence overlays only.",
    ),
)


def get_current_strategy_contract() -> StrategyContract:
    return CURRENT_STRATEGY_CONTRACT


def assess_evidence_quality(
    *,
    signal: DecisionSignal,
    gate_passed: bool,
    calibration_source: str,
    data_quality: str,
    provider_status: str,
    provider_warnings: list[str] | tuple[str, ...] | None = None,
) -> EvidenceQualityAssessment:
    reasons: list[str] = []
    score = 1.0
    warnings = tuple(provider_warnings or [])

    if signal == "HOLD":
        score = 0.55
        reasons.append("No action is justified because the directional edge is not strong enough.")

    if not gate_passed and signal in {"BUY", "SELL"}:
        score -= 0.12
        reasons.append("Recent evidence gate did not approve the setup, so trust is capped even if the direction is interesting.")

    if calibration_source == "raw":
        score -= 0.05
        reasons.append("Confidence is using raw score because mature calibration samples are limited.")
    elif calibration_source == "signal":
        score -= 0.02
        reasons.append("Confidence is calibrated at the signal bucket level rather than a mature score band.")
    else:
        reasons.append("Confidence is informed by mature score-band evidence.")

    if data_quality == "low":
        score -= 0.34
        reasons.append("Market-data coverage is thin for this setup.")
    elif data_quality == "degraded":
        score -= 0.22
        reasons.append("Market-data quality is degraded for this setup.")
    else:
        reasons.append("Core market-data inputs look usable.")

    if provider_status == "critical":
        score -= 0.42
        reasons.append("A critical provider dependency is degraded or stale.")
    elif provider_status == "degraded":
        score -= 0.18
        reasons.append("One or more supportive providers are degraded.")
    else:
        reasons.append("Provider state is healthy enough for research use.")

    if warnings:
        reasons.append(f"Provider warnings: {', '.join(sorted(warnings))}.")

    score = max(0.0, min(round(score, 2), 1.0))
    if score >= 0.82:
        label: EvidenceQualityLabel = "high"
    elif score >= 0.6:
        label = "moderate"
    elif score >= 0.35:
        label = "low"
    else:
        label = "degraded"

    return EvidenceQualityAssessment(
        label=label,
        score=score,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def determine_execution_eligibility(
    *,
    signal: DecisionSignal,
    gate_passed: bool,
    provider_status: str,
    evidence_quality: EvidenceQualityLabel,
) -> ExecutionEligibilityLabel:
    if signal == "HOLD":
        return "not_applicable"
    if provider_status == "critical":
        return "blocked"
    if not gate_passed:
        return "blocked"
    if evidence_quality == "degraded":
        return "blocked"
    if evidence_quality == "low" or provider_status == "degraded":
        return "review"
    return "eligible"


def determine_data_grade(
    *,
    signal: DecisionSignal,
    provider_status: str,
    data_quality: str,
    evidence_quality: EvidenceQualityLabel,
    execution_eligibility: ExecutionEligibilityLabel,
) -> DataGradeLabel:
    if provider_status == "critical" or data_quality in {"low", "degraded"} or evidence_quality == "degraded":
        return "degraded"
    if signal in {"BUY", "SELL"} and execution_eligibility == "eligible":
        return "decision"
    return "research"


def build_strategy_evaluation_metadata(
    *,
    signal: DecisionSignal,
    gate_passed: bool,
    calibration_source: str,
    data_quality: str,
    provider_status: str,
    provider_warnings: list[str] | tuple[str, ...] | None = None,
) -> StrategyEvaluationMetadata:
    quality = assess_evidence_quality(
        signal=signal,
        gate_passed=gate_passed,
        calibration_source=calibration_source,
        data_quality=data_quality,
        provider_status=provider_status,
        provider_warnings=provider_warnings,
    )
    execution_eligibility = determine_execution_eligibility(
        signal=signal,
        gate_passed=gate_passed,
        provider_status=provider_status,
        evidence_quality=quality.label,
    )
    return StrategyEvaluationMetadata(
        strategy_id=STRATEGY_ID,
        strategy_version=STRATEGY_VERSION,
        primary_holding_horizon=PRIMARY_HOLDING_HORIZON,
        entry_assumption=ENTRY_ASSUMPTION,
        exit_assumption=EXIT_ASSUMPTION,
        evidence_quality=quality.label,
        evidence_quality_score=quality.score,
        evidence_quality_reasons=quality.reasons,
        data_grade=determine_data_grade(
            signal=signal,
            provider_status=provider_status,
            data_quality=data_quality,
            evidence_quality=quality.label,
            execution_eligibility=execution_eligibility,
        ),
        execution_eligibility=execution_eligibility,
    )
