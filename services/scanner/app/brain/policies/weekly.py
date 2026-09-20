"""Calibrated weekly-probability policy: the replayable champion candidate.

BUY only when a bullish daily-bar pattern clears quality filters, a Wilson
lower bound on historical hit rate, a positive EV-after-friction floor, and a
computed probability. Everything else is ABSTAIN with a reason code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.brain.calibration import (
    ReliabilityBin,
    apply_reliability_map,
    reliability_map_to_payload,
)
from app.brain.candidate_quality import (
    buy_candidate_reject_reason,
    momentum_pct,
    relative_strength_vs_market,
)
from app.brain.config import WeeklyPolicyConfig
from app.brain.contracts import (
    BrainDecision,
    EvidenceBasis,
    ExitPlan,
    MarketSnapshot,
    SymbolSnapshot,
)
from app.brain.evaluation.stats import wilson_lower_bound_pct
from app.brain.gates import expected_value_after_friction
from app.brain.identity import decision_fingerprint, learned_artifact_identity
from app.brain.probability import compute_upside_probability
from app.brain.weekly_backtest import (
    PatternBacktestStats,
    summarize_pattern_stats,
    walk_forward_pattern_samples,
)
from app.brain.weekly_bar_utils import bars_as_of, close_price, sorted_bars
from app.brain.weekly_evidence import evaluate_weekly_pattern_evidence
from app.brain.weekly_patterns import detect_weekly_pattern, project_weekly_range

WEEKLY_POLICY_ID = "weekly_probability"
WEEKLY_POLICY_VERSION = "weekly-prob-v1"
CALIBRATION_SAMPLE_SOURCES = ("historical", "backfilled_replay")
TRUST_SAMPLE_SOURCES = ("live_paper_forward", "out_of_sample", "live_holdout")


def weekly_learned_artifacts_payload(
    *,
    reliability_maps: dict[str, list[ReliabilityBin]],
    extra_stats: dict[tuple[str, str, str], PatternBacktestStats],
) -> dict[str, Any]:
    maps: dict[str, list[dict[str, float | int]]] = {}
    for asset_type, bins in sorted(reliability_maps.items()):
        payload = reliability_map_to_payload(list(bins))
        if payload:
            maps[str(asset_type)] = payload

    stats_rows: list[dict[str, Any]] = []
    for key, stats in sorted(extra_stats.items(), key=lambda item: item[0]):
        pattern_name, asset_type, sample_source = key
        stats_rows.append(
            {
                "pattern_name": str(pattern_name),
                "asset_type": str(asset_type),
                "sample_source": str(sample_source),
                "stats_pattern_name": stats.pattern_name,
                "sample_size": int(stats.sample_size),
                "hit_rate_pct": stats.hit_rate_pct,
                "avg_forward_return_pct": stats.avg_forward_return_pct,
            }
        )
    return {
        "reliability_maps": maps,
        "pattern_stats": stats_rows,
    }


def _wilson_lb_from_stats(stats: PatternBacktestStats) -> float | None:
    if stats.sample_size <= 0 or stats.hit_rate_pct is None:
        return None
    successes = int(round(float(stats.hit_rate_pct) / 100.0 * stats.sample_size))
    successes = max(0, min(stats.sample_size, successes))
    return wilson_lower_bound_pct(successes, stats.sample_size)


class WeeklyProbabilityPolicy:
    policy_id = WEEKLY_POLICY_ID
    policy_version = WEEKLY_POLICY_VERSION
    replayable = True

    def __init__(
        self,
        *,
        config: WeeklyPolicyConfig | None = None,
        reliability_maps: dict[str, list[ReliabilityBin]] | None = None,
        extra_stats: dict[tuple[str, str, str], PatternBacktestStats] | None = None,
        learned_artifact_reference: dict[str, Any] | None = None,
    ) -> None:
        self.config = config or WeeklyPolicyConfig()
        self.reliability_maps = reliability_maps or {}
        self.extra_stats = extra_stats or {}
        self.learned_artifact_reference = learned_artifact_reference or {}

    def config_payload(self) -> dict[str, Any]:
        return self.config.payload()

    def learned_artifacts_payload(self) -> dict[str, Any]:
        return weekly_learned_artifacts_payload(
            reliability_maps=self.reliability_maps,
            extra_stats=self.extra_stats,
        )

    def learned_artifact_identity(self) -> dict[str, Any]:
        return learned_artifact_identity(
            artifact_type="weekly_probability_inputs",
            content_payload=self.learned_artifacts_payload(),
            reference_payload=self.learned_artifact_reference,
        )

    def learned_artifacts_fingerprint(self) -> str:
        return str(self.learned_artifact_identity()["content_hash"])

    def fingerprint(self) -> str:
        return decision_fingerprint(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            config_payload=self.config_payload(),
            learned_artifacts={
                "weekly_probability_inputs": self.learned_artifacts_fingerprint(),
            },
        )

    def decide_all(self, snapshot: MarketSnapshot) -> list[BrainDecision]:
        return [self._decide_symbol(symbol, snapshot) for symbol in snapshot.symbols]

    def _historical_stats(
        self,
        bars: list[dict],
        *,
        pattern_name: str,
        as_of: datetime,
    ) -> PatternBacktestStats:
        usable = bars_as_of(bars, as_of)
        warmup = max(self.config.daily_lookback_bars_min // 4, 60)
        samples = walk_forward_pattern_samples(
            usable,
            sample_source="historical",
            warmup_bars=warmup,
            step_days=max(7, int(self.config.sample_step_days)),
            forward_days=self.config.forward_days,
            tolerance_days=self.config.forward_tolerance_days,
            hold_return_tolerance_pct=self.config.hold_return_tolerance_pct,
        )
        return summarize_pattern_stats(samples, pattern_name=pattern_name)

    def _blended_stats(
        self,
        *,
        pattern_name: str,
        asset_type: str,
        fallback: PatternBacktestStats,
    ) -> tuple[PatternBacktestStats, dict[str, PatternBacktestStats]]:
        grouped: dict[str, PatternBacktestStats] = {}
        for source in (*CALIBRATION_SAMPLE_SOURCES, *TRUST_SAMPLE_SOURCES):
            extra = self.extra_stats.get((pattern_name, asset_type, source))
            if extra is not None:
                grouped[source] = extra
        historical = grouped.get("historical") or fallback
        if fallback.sample_size > historical.sample_size:
            historical = fallback
            grouped["historical"] = fallback
        else:
            grouped["historical"] = historical
        # Only calibration sources may change the served probability. Live
        # forward and holdout rows are trust/evaluation evidence only.
        blended = historical
        backfilled = grouped.get("backfilled_replay")
        if backfilled and backfilled.sample_size > 0:
            blended = backfilled
        return blended, grouped

    def _friction_pct(self, asset_type: str) -> float:
        bps = self.config.crypto_friction_bps if asset_type == "crypto" else self.config.stock_friction_bps
        return float(bps) / 100.0

    def _abstain(
        self,
        symbol: SymbolSnapshot,
        snapshot: MarketSnapshot,
        *,
        reasons: tuple[str, ...],
        pattern_name: str | None = None,
        evidence: EvidenceBasis | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> BrainDecision:
        return BrainDecision(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            decision_fingerprint=self.fingerprint(),
            symbol=symbol.symbol,
            asset_type=symbol.asset_type,
            as_of=snapshot.as_of,
            action="ABSTAIN",
            reasons=reasons,
            pattern_name=pattern_name,
            evidence_basis=evidence or EvidenceBasis(),
            diagnostics=diagnostics or {},
        )

    def _decide_symbol(self, symbol: SymbolSnapshot, snapshot: MarketSnapshot) -> BrainDecision:
        as_of = snapshot.as_of
        usable = bars_as_of(symbol.daily_bars, as_of)
        closes = [close_price(bar) for bar in sorted_bars(usable) if close_price(bar) > 0]
        if len(closes) < 20:
            return self._abstain(symbol, snapshot, reasons=("insufficient_bars",))

        pattern = detect_weekly_pattern(usable, as_of=as_of)
        if pattern is None:
            return self._abstain(symbol, snapshot, reasons=("no_pattern",))
        if pattern.directional_bias != "bullish" or pattern.decision_signal != "BUY":
            return self._abstain(
                symbol,
                snapshot,
                reasons=("not_bullish",),
                pattern_name=pattern.pattern_name,
            )

        price = closes[-1]
        range_low, range_high = project_weekly_range(price=price, pattern=pattern, closes=closes)
        walkforward_stats = self._historical_stats(
            usable, pattern_name=pattern.pattern_name, as_of=as_of
        )
        blended, grouped = self._blended_stats(
            pattern_name=pattern.pattern_name,
            asset_type=symbol.asset_type,
            fallback=walkforward_stats,
        )
        evidence_verdict = evaluate_weekly_pattern_evidence(
            stats_by_source=grouped,  # type: ignore[arg-type]
            settings=self.config,
            asset_type=symbol.asset_type,
            signal="BUY",
        )
        evidence = EvidenceBasis(
            basis=evidence_verdict.evidence_basis,
            sample_sizes={name: stats.sample_size for name, stats in grouped.items()},
            historical_hit_rate_pct=blended.hit_rate_pct,
            historical_avg_return_pct=blended.avg_forward_return_pct,
        )

        warmup = max(self.config.daily_lookback_bars_min // 4, 60)
        if self.config.apply_proof_candidate_filters:
            reject = buy_candidate_reject_reason(
                bars=usable,
                closes=closes,
                entry_price=price,
                as_of=as_of,
                settings=self.config,
                stats=blended,
                warmup_bars=warmup,
                step_days=int(self.config.sample_step_days),
            )
            if reject is not None:
                return self._abstain(
                    symbol,
                    snapshot,
                    reasons=(reject,),
                    pattern_name=pattern.pattern_name,
                    evidence=evidence,
                )

        wilson_lb = _wilson_lb_from_stats(blended)
        if wilson_lb is None or wilson_lb <= float(self.config.min_wilson_lb_pct):
            return self._abstain(
                symbol,
                snapshot,
                reasons=("wilson_lb_below_floor",),
                pattern_name=pattern.pattern_name,
                evidence=evidence,
                diagnostics={"wilson_lb_pct": wilson_lb, "sample_size": blended.sample_size},
            )

        lookback = int(self.config.momentum_lookback_days)
        benchmark_key = "BTC/USD" if symbol.asset_type == "crypto" else "SPY"
        market_bars = snapshot.benchmark_daily_bars.get(benchmark_key)
        trend_strength_pct = momentum_pct(closes, lookback)
        relative_strength_pct = relative_strength_vs_market(
            usable, market_bars, as_of=as_of, lookback=lookback
        )
        upside = compute_upside_probability(
            hit_rate_pct=blended.hit_rate_pct,
            sample_size=blended.sample_size,
            directional_bias=pattern.directional_bias,
            shrinkage_k=self.config.shrinkage_k,
            trend_strength_pct=trend_strength_pct,
            relative_strength_pct=relative_strength_pct,
        )
        if upside is None:
            return self._abstain(
                symbol,
                snapshot,
                reasons=("missing_probability",),
                pattern_name=pattern.pattern_name,
                evidence=evidence,
            )

        methodology = "pattern_recognition"
        if self.config.apply_calibration_map:
            reliability_map = self.reliability_maps.get(symbol.asset_type) or []
            if reliability_map:
                calibrated = apply_reliability_map(reliability_map, upside)
                if calibrated is not None:
                    upside = calibrated
                    methodology = "pattern_recognition_calibrated"

        ev_floor = max(float(self.config.min_expected_value_pct), float(self.config.min_ev_floor_pct))
        expected_value = expected_value_after_friction(
            upside_probability_pct=upside,
            entry_price=price,
            target_price=range_high,
            invalidation_price=range_low,
            friction_pct=self._friction_pct(symbol.asset_type),
        )
        if expected_value is None or expected_value <= ev_floor:
            return self._abstain(
                symbol,
                snapshot,
                reasons=("expected_value_below_min",),
                pattern_name=pattern.pattern_name,
                evidence=evidence,
                diagnostics={"expected_value_pct": expected_value, "ev_floor": ev_floor},
            )

        if symbol.data_quality == "degraded" or symbol.daily_bars_stale:
            return self._abstain(
                symbol,
                snapshot,
                reasons=("data_quality_insufficient",),
                pattern_name=pattern.pattern_name,
                evidence=evidence,
            )

        return BrainDecision(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            decision_fingerprint=self.fingerprint(),
            symbol=symbol.symbol,
            asset_type=symbol.asset_type,
            as_of=as_of,
            action="BUY",
            p_up_calibrated=upside,
            expected_value_pct=expected_value,
            exit_plan=ExitPlan(
                entry_price=price,
                target_price=range_high,
                stop_price=range_low,
                horizon_days=self.config.forward_days,
            ),
            evidence_basis=evidence,
            reasons=(),
            pattern_name=pattern.pattern_name,
            probability_methodology=methodology,
            diagnostics={
                "wilson_lb_pct": wilson_lb,
                "sample_size": blended.sample_size,
                "range_low": range_low,
                "range_high": range_high,
                "data_quality": symbol.data_quality,
                "daily_bars_source": symbol.daily_bars_source,
            },
        )
