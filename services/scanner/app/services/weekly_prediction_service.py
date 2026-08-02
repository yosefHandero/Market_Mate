from __future__ import annotations

from datetime import datetime

from app.config import Settings, get_settings
from app.core.calibration import apply_reliability_map
from app.core.candidate_quality import (
    buy_candidate_reject_reason,
    momentum_pct,
    relative_strength_vs_market,
)
from app.core.ranking import expected_value_after_friction
from app.core.weekly_backtest import (
    PatternBacktestStats,
    summarize_pattern_stats,
    walk_forward_pattern_samples,
)
from app.core.weekly_evidence import evaluate_weekly_pattern_evidence
from app.core.weekly_patterns import detect_weekly_pattern, project_weekly_range
from app.core.weekly_bar_utils import bars_as_of, close_price, sorted_bars
from app.schemas import GateCheck, SampleSource, WeeklyPatternPrediction
from app.services.daily_bar_service import DailyBarService
from app.services.repository import ScanRepository
from app.services.walk_forward_repository import WalkForwardRepository


def compute_upside_probability(
    *,
    hit_rate_pct: float | None,
    sample_size: int,
    directional_bias: str,
    shrinkage_k: float,
    trend_strength_pct: float | None = None,
    relative_strength_pct: float | None = None,
) -> float | None:
    """Probability that price is higher at the end of the growth window.

    Base signal is the detected pattern's historical hit rate, shrunk toward a
    neutral 50% prior by sample size so thin samples cannot look confident. When
    provided, trend strength and relative strength apply a bounded regime-aware
    adjustment so the same pattern reads stronger in a confirming regime and
    weaker in a fading one. Only bullish patterns produce a probability.
    """
    if directional_bias != "bullish":
        return None
    if hit_rate_pct is None or sample_size <= 0:
        base = 50.0
    else:
        n = float(sample_size)
        k = max(0.0, float(shrinkage_k))
        base = 50.0 + (float(hit_rate_pct) - 50.0) * (n / (n + k))

    adjustment = 0.0
    if trend_strength_pct is not None:
        # Each +1% of recent momentum nudges probability up to a small, capped amount.
        adjustment += max(-6.0, min(6.0, float(trend_strength_pct) * 0.6))
    if relative_strength_pct is not None:
        adjustment += max(-4.0, min(4.0, float(relative_strength_pct) * 0.4))
    # Cap the total regime tilt so it refines, never dominates, the sample edge.
    adjustment = max(-8.0, min(8.0, adjustment))
    return round(max(0.0, min(100.0, base + adjustment)), 2)


class WeeklyPredictionService:
    def __init__(
        self,
        *,
        daily_bars: DailyBarService | None = None,
        repository: ScanRepository | None = None,
        walk_forward_repository: WalkForwardRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.daily_bars = daily_bars or DailyBarService(settings=self.settings)
        self.repository = repository or ScanRepository()
        self.walk_forward_repository = walk_forward_repository or WalkForwardRepository()

    def _stats_from_walkforward(
        self,
        bars: list[dict],
        *,
        pattern_name: str,
        as_of: datetime,
    ) -> PatternBacktestStats:
        # No look-ahead: only bars on or before as_of may inform a served
        # prediction. Feeding the full bar list would let a future bar change a
        # past prediction (safe only while as_of ~ now, but wrong by construction).
        usable = bars_as_of(bars, as_of)
        samples = walk_forward_pattern_samples(
            usable,
            sample_source="historical",
            warmup_bars=max(self.settings.weekly_daily_lookback_bars_min // 4, 60),
            forward_days=self.settings.weekly_forward_days,
            tolerance_days=self.settings.weekly_forward_tolerance_days,
            hold_return_tolerance_pct=self.settings.weekly_hold_return_tolerance_pct,
        )
        return summarize_pattern_stats(samples, pattern_name=pattern_name)

    @staticmethod
    def _served_blend(
        repo_stats: dict[SampleSource, PatternBacktestStats],
        *,
        fallback: PatternBacktestStats,
    ) -> PatternBacktestStats:
        """Stats that may inform a *served* probability.

        Only calibration sources (historical + backfilled_replay) are allowed.
        out_of_sample and live_paper_forward outcomes must never flow into served
        probabilities: doing so contaminates the holdout and contradicts the
        declared trust policy (weekly_evidence.CALIBRATION_SOURCES). They still
        inform the trust verdict, just not the number we serve.
        """
        blended = repo_stats.get("historical") or fallback
        backfilled = repo_stats.get("backfilled_replay")
        if backfilled and backfilled.sample_size > 0:
            blended = backfilled
        return blended

    def _stats_by_source_from_repository(
        self,
        *,
        pattern_name: str,
        asset_type: str,
    ) -> dict[SampleSource, PatternBacktestStats]:
        grouped: dict[SampleSource, PatternBacktestStats] = {}
        for source in ("historical", "backfilled_replay", "live_paper_forward", "out_of_sample"):
            stats = self.repository.get_weekly_pattern_stats(
                pattern_name=pattern_name,
                asset_type=asset_type,
                sample_source=source,
            )
            grouped[source] = stats
        return grouped

    async def build_weekly_prediction(
        self,
        *,
        symbol: str,
        asset_type: str,
        as_of: datetime,
        daily_bars: list[dict] | None = None,
        market_daily_bars: list[dict] | None = None,
    ) -> WeeklyPatternPrediction | None:
        if not self.settings.weekly_primary_horizon_enabled:
            return None

        bars = daily_bars
        daily_bars_source = "prefetched"
        if bars is None:
            bars, daily_bars_source = await self.daily_bars.get_daily_bars(symbol, asset_type=asset_type)
        data_quality = self.daily_bars.assess_data_quality(bars, asset_type=asset_type, as_of=as_of)
        daily_bars_stale = self.daily_bars.is_daily_bars_stale(bars, asset_type=asset_type, as_of=as_of)
        pattern = detect_weekly_pattern(bars, as_of=as_of)
        if pattern is None:
            return None

        usable = bars_as_of(bars, as_of)
        closes = [close_price(bar) for bar in sorted_bars(usable) if close_price(bar) > 0]
        if not closes:
            return None
        price = closes[-1]
        range_low, range_high = project_weekly_range(price=price, pattern=pattern, closes=closes)

        walkforward_stats = self._stats_from_walkforward(
            bars, pattern_name=pattern.pattern_name, as_of=as_of
        )
        repo_stats = self._stats_by_source_from_repository(
            pattern_name=pattern.pattern_name,
            asset_type=asset_type,
        )
        if walkforward_stats.sample_size > (repo_stats.get("historical") or PatternBacktestStats("none", 0, None, None)).sample_size:
            repo_stats["historical"] = walkforward_stats

        # Trust verdict may weigh every source, including live_paper_forward and
        # out_of_sample outcomes.
        evidence = evaluate_weekly_pattern_evidence(stats_by_source=repo_stats, settings=self.settings)
        blended_stats = self._served_blend(repo_stats, fallback=walkforward_stats)

        is_bullish_buy = pattern.directional_bias == "bullish" and pattern.decision_signal == "BUY"
        warmup = max(self.settings.weekly_daily_lookback_bars_min // 4, 60)
        if is_bullish_buy and self.settings.weekly_apply_proof_candidate_filters:
            if buy_candidate_reject_reason(
                bars=usable,
                closes=closes,
                entry_price=price,
                as_of=as_of,
                settings=self.settings,
                stats=blended_stats,
                warmup_bars=warmup,
                step_days=int(self.settings.proof_step_days),
            ) is not None:
                return None

        lookback = int(self.settings.proof_momentum_lookback_days)
        trend_strength_pct = momentum_pct(closes, lookback) if is_bullish_buy else None
        relative_strength_pct = (
            relative_strength_vs_market(usable, market_daily_bars, as_of=as_of, lookback=lookback)
            if is_bullish_buy
            else None
        )
        upside_probability_pct = compute_upside_probability(
            hit_rate_pct=blended_stats.hit_rate_pct,
            sample_size=blended_stats.sample_size,
            directional_bias=pattern.directional_bias,
            shrinkage_k=self.settings.upside_prob_shrinkage_k,
            trend_strength_pct=trend_strength_pct,
            relative_strength_pct=relative_strength_pct,
        )

        methodology = "pattern_recognition"
        if is_bullish_buy and upside_probability_pct is not None and self.settings.weekly_apply_calibration_map:
            reliability_map = self.walk_forward_repository.get_latest_reliability_map(
                asset_type, min_count=int(self.settings.calibration_min_score_band_samples)
            )
            if reliability_map:
                calibrated = apply_reliability_map(reliability_map, upside_probability_pct)
                if calibrated is not None:
                    upside_probability_pct = calibrated
                    methodology = "pattern_recognition_calibrated"

        if is_bullish_buy and upside_probability_pct is not None:
            friction_pct = self.repository._friction_bps_for_asset_type(asset_type) / 100.0
            expected_value = expected_value_after_friction(
                upside_probability_pct=upside_probability_pct,
                entry_price=price,
                target_price=range_high,
                invalidation_price=range_low,
                friction_pct=friction_pct,
            )
            if expected_value is not None and expected_value <= float(self.settings.proof_min_expected_value_pct):
                return None

        return WeeklyPatternPrediction(
            horizon="1w",
            horizon_label="1 week",
            pattern_name=pattern.pattern_name,
            directional_bias=pattern.directional_bias,
            range_low=range_low,
            range_high=range_high,
            upside_probability_pct=upside_probability_pct,
            historical_hit_rate_pct=blended_stats.hit_rate_pct,
            avg_forward_1w_return_pct=blended_stats.avg_forward_return_pct,
            sample_size=blended_stats.sample_size,
            data_quality=data_quality,
            daily_bars_stale=daily_bars_stale,
            daily_bars_source=daily_bars_source,
            forward_days=self.settings.weekly_forward_days,
            hold_return_tolerance_pct=self.settings.weekly_hold_return_tolerance_pct,
            evidence_basis=evidence.evidence_basis,
            real_money_trust_blocked=evidence.real_money_trust_blocked,
            pattern_gate_checks=list(evidence.checks),
            methodology=methodology,
        )
