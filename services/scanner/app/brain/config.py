"""Frozen decision-side and ruler-side configuration for the brain.

``WeeklyPolicyConfig`` and ``HybridPolicyConfig`` carry every settings-derived
constant that can change *produced decisions* for their respective policies;
their payloads feed :func:`app.brain.identity.decision_fingerprint`.
``RulerConfig`` carries the constants that only control *how stored evidence
is judged*; its payload feeds :func:`app.brain.identity.ruler_fingerprint` and
is stamped on evaluation outputs.

Constants that are still hardcoded inside brain modules (pattern thresholds,
projection band weights, regime-tilt caps) are represented in decision
identity by ``FEATURE_VERSION`` / policy code versions until they are lifted
into these configs; bumping those versions is mandatory when such constants
change (see BRAIN.md).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.brain.weekly_patterns import FEATURE_VERSION


@dataclass(frozen=True)
class WeeklyPolicyConfig:
    """Decision-relevant constants for the weekly probability policy."""

    feature_version: str = FEATURE_VERSION
    forward_days: int = 7
    forward_tolerance_days: int = 3
    hold_return_tolerance_pct: float = 1.0
    shrinkage_k: float = 20.0
    apply_calibration_map: bool = True
    apply_proof_candidate_filters: bool = True
    calibration_min_bin_samples: int = 10
    momentum_lookback_days: int = 63
    min_expected_value_pct: float = 0.0
    rsi_overbought: float = 80.0
    min_pattern_samples: int = 12
    min_pattern_edge_pct: float = 2.0
    require_buy_hold_baseline: bool = True
    volume_lookback_days: int = 20
    min_volume_median_ratio: float = 0.5
    sample_step_days: int = 7
    daily_lookback_bars_min: int = 250
    out_of_sample_holdout_ratio: float = 0.25
    pattern_gate_min_historical_samples: int = 30
    pattern_gate_min_backfilled_samples: int = 20
    pattern_gate_min_live_forward_samples: int = 20
    pattern_gate_min_out_of_sample_samples: int = 10
    pattern_gate_min_win_rate: float = 52.0
    pattern_gate_min_avg_return: float = 0.10
    # Friction enters the policy's EV gate, so it is decision identity.
    stock_friction_bps: float = 7.0
    crypto_friction_bps: float = 28.0
    # Abstention floors: Wilson 95% lower bound on historical hit rate must
    # clear 50%, and EV after friction must be strictly positive.
    min_wilson_lb_pct: float = 50.0
    # Policy-side EV floor is at least this even if host settings are 0.
    min_ev_floor_pct: float = 0.10

    @classmethod
    def from_settings(cls, settings: Any) -> "WeeklyPolicyConfig":
        return cls(
            forward_days=int(settings.weekly_forward_days),
            forward_tolerance_days=int(settings.weekly_forward_tolerance_days),
            hold_return_tolerance_pct=float(settings.weekly_hold_return_tolerance_pct),
            shrinkage_k=float(settings.upside_prob_shrinkage_k),
            apply_calibration_map=bool(settings.weekly_apply_calibration_map),
            apply_proof_candidate_filters=bool(settings.weekly_apply_proof_candidate_filters),
            calibration_min_bin_samples=int(settings.calibration_min_score_band_samples),
            momentum_lookback_days=int(settings.proof_momentum_lookback_days),
            min_expected_value_pct=float(settings.proof_min_expected_value_pct),
            rsi_overbought=float(settings.proof_rsi_overbought),
            min_pattern_samples=int(settings.proof_min_pattern_samples),
            min_pattern_edge_pct=float(settings.proof_min_pattern_edge_pct),
            require_buy_hold_baseline=bool(settings.proof_require_buy_hold_baseline),
            volume_lookback_days=int(settings.proof_volume_lookback_days),
            min_volume_median_ratio=float(settings.proof_min_volume_median_ratio),
            sample_step_days=int(settings.proof_step_days),
            daily_lookback_bars_min=int(settings.weekly_daily_lookback_bars_min),
            out_of_sample_holdout_ratio=float(settings.weekly_out_of_sample_holdout_ratio),
            pattern_gate_min_historical_samples=int(settings.weekly_pattern_gate_min_historical_samples),
            pattern_gate_min_backfilled_samples=int(settings.weekly_pattern_gate_min_backfilled_samples),
            pattern_gate_min_live_forward_samples=int(settings.weekly_pattern_gate_min_live_forward_samples),
            pattern_gate_min_out_of_sample_samples=int(settings.weekly_pattern_gate_min_out_of_sample_samples),
            pattern_gate_min_win_rate=float(settings.weekly_pattern_gate_min_win_rate),
            pattern_gate_min_avg_return=float(settings.weekly_pattern_gate_min_avg_return),
            stock_friction_bps=float(settings.stock_slippage_bps)
            + float(settings.stock_spread_bps)
            + float(settings.stock_fee_bps),
            crypto_friction_bps=float(settings.crypto_slippage_bps)
            + float(settings.crypto_spread_bps)
            + float(settings.crypto_fee_bps),
            min_wilson_lb_pct=float(getattr(settings, "brain_min_wilson_lb_pct", 50.0)),
            min_ev_floor_pct=max(float(settings.proof_min_expected_value_pct), 0.10),
        )

    def payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HybridPolicyConfig:
    """Decision-relevant constants for the legacy hybrid (intraday) policy."""

    strategy_variant: str = "layered-v4"
    buy_threshold: float = 52.0
    sell_threshold: float = 52.0
    signal_margin: float = 6.0
    crypto_buy_threshold: float = 52.0
    crypto_sell_threshold: float = 52.0
    crypto_signal_margin: float = 6.0
    news_trigger_abs_move_pct: float = 1.25
    sec_enhanced_enabled: bool = False
    marketdata_options_enabled: bool = False
    binance_enabled: bool = False
    deribit_enabled: bool = False
    fred_enabled: bool = False
    internal_breadth_enabled: bool = False
    defillama_enabled: bool = False

    @classmethod
    def from_settings(cls, settings: Any) -> "HybridPolicyConfig":
        return cls(
            strategy_variant=str(settings.scanner_strategy_variant),
            buy_threshold=float(settings.signal_buy_threshold),
            sell_threshold=float(settings.signal_sell_threshold),
            signal_margin=float(settings.signal_margin),
            crypto_buy_threshold=float(settings.signal_crypto_buy_threshold),
            crypto_sell_threshold=float(settings.signal_crypto_sell_threshold),
            crypto_signal_margin=float(settings.signal_crypto_margin),
            news_trigger_abs_move_pct=float(settings.news_trigger_abs_move_pct),
            sec_enhanced_enabled=bool(settings.sec_enhanced_enabled),
            marketdata_options_enabled=bool(settings.marketdata_options_enabled),
            binance_enabled=bool(settings.binance_enabled),
            deribit_enabled=bool(settings.deribit_enabled),
            fred_enabled=bool(settings.fred_enabled),
            internal_breadth_enabled=bool(settings.internal_breadth_enabled),
            defillama_enabled=bool(settings.defillama_enabled),
        )

    def payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RulerConfig:
    """How stored evidence is judged. Never rotates prediction campaigns."""

    validation_win_threshold_pct: float = 0.0
    validation_false_positive_threshold_pct: float = 0.0
    validation_min_sample_size: int = 30
    outcome_report_min_evaluated_per_horizon: int = 20
    outcome_baseline_min_evaluated_per_horizon: int = 20
    outcome_baseline_min_mean_return_pct: float = 0.0
    wf_holdout_days: int = 7
    proof_target_years: int = 3
    proof_min_years: int = 2
    proof_max_years: int = 5
    proof_holdout_months: int = 9
    proof_validation_months: int = 3
    proof_lookback_context_months_min: int = 6
    proof_lookback_context_months_max: int = 24
    # Walk-forward evaluation schedule (outer replay-date step). Ruler-side:
    # it controls how densely history is sampled for judging, not what any
    # policy serves.
    eval_step_days: int = 10
    proof_top_n_per_asset: int = 5
    benchmark_random_draws: int = 25
    benchmark_random_seed: int = 1729
    pilot_min_predictions_per_asset: int = 120
    pilot_min_upside_hit_rate_pct: float = 55.0
    pilot_max_calibration_gap_pct: float = 10.0
    pilot_min_after_friction_return_pct: float = 0.0
    pilot_max_drawdown_pct: float = 25.0
    pilot_min_exit_window_helped_rate_pct: float = 50.0
    pilot_min_confidence_discrimination_pct: float = 0.0
    pilot_min_information_coefficient: float = 0.02
    pilot_min_ic_t_stat: float = 2.0
    pilot_require_edge_significant: bool = True
    pilot_require_cross_regime_edge: bool = True
    pilot_min_edge_vs_buy_hold_pct: float = 0.0
    min_regime_samples: int = 8
    promotion_min_pairs: int = 40
    # Friction used when judging after-friction metrics (mirrors the decision-
    # side values but is stamped separately so evaluation is reproducible).
    stock_friction_bps: float = 7.0
    crypto_friction_bps: float = 28.0

    @classmethod
    def from_settings(cls, settings: Any) -> "RulerConfig":
        return cls(
            validation_win_threshold_pct=float(settings.validation_win_threshold_pct),
            validation_false_positive_threshold_pct=float(settings.validation_false_positive_threshold_pct),
            validation_min_sample_size=int(settings.validation_min_sample_size),
            outcome_report_min_evaluated_per_horizon=int(settings.outcome_report_min_evaluated_per_horizon),
            outcome_baseline_min_evaluated_per_horizon=int(settings.outcome_baseline_min_evaluated_per_horizon),
            outcome_baseline_min_mean_return_pct=float(settings.outcome_baseline_min_mean_return_pct),
            wf_holdout_days=int(settings.wf_holdout_days),
            proof_target_years=int(settings.proof_target_years),
            proof_min_years=int(settings.proof_min_years),
            proof_max_years=int(settings.proof_max_years),
            proof_holdout_months=int(settings.proof_holdout_months),
            proof_validation_months=int(settings.proof_validation_months),
            proof_lookback_context_months_min=int(settings.proof_lookback_context_months_min),
            proof_lookback_context_months_max=int(settings.proof_lookback_context_months_max),
            eval_step_days=int(getattr(settings, "proof_eval_step_days", 10)),
            proof_top_n_per_asset=int(settings.proof_top_n_per_asset),
            benchmark_random_draws=int(settings.proof_benchmark_random_draws),
            benchmark_random_seed=int(settings.proof_benchmark_random_seed),
            pilot_min_predictions_per_asset=int(settings.proof_pilot_min_predictions_per_asset),
            pilot_min_upside_hit_rate_pct=float(settings.proof_pilot_min_upside_hit_rate_pct),
            pilot_max_calibration_gap_pct=float(settings.proof_pilot_max_calibration_gap_pct),
            pilot_min_after_friction_return_pct=float(settings.proof_pilot_min_after_friction_return_pct),
            pilot_max_drawdown_pct=float(settings.proof_pilot_max_drawdown_pct),
            pilot_min_exit_window_helped_rate_pct=float(settings.proof_pilot_min_exit_window_helped_rate_pct),
            pilot_min_confidence_discrimination_pct=float(settings.proof_pilot_min_confidence_discrimination_pct),
            pilot_min_information_coefficient=float(settings.proof_pilot_min_information_coefficient),
            pilot_min_ic_t_stat=float(settings.proof_pilot_min_ic_t_stat),
            pilot_require_edge_significant=bool(settings.proof_pilot_require_edge_significant),
            pilot_require_cross_regime_edge=bool(settings.proof_pilot_require_cross_regime_edge),
            pilot_min_edge_vs_buy_hold_pct=float(settings.proof_pilot_min_edge_vs_buy_hold_pct),
            min_regime_samples=int(settings.proof_min_regime_samples),
            promotion_min_pairs=int(getattr(settings, "brain_promotion_min_pairs", 40)),
            stock_friction_bps=float(settings.stock_slippage_bps)
            + float(settings.stock_spread_bps)
            + float(settings.stock_fee_bps),
            crypto_friction_bps=float(settings.crypto_slippage_bps)
            + float(settings.crypto_spread_bps)
            + float(settings.crypto_fee_bps),
        )

    def payload(self) -> dict[str, Any]:
        return asdict(self)
