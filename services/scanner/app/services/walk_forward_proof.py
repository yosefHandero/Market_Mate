from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import subprocess
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from uuid import uuid4

from app.brain.calibration import (
    build_reliability_map,
    calibrated_mean_abs_gap_pct,
    reliability_map_to_payload,
)
from app.brain.config import RulerConfig, WeeklyPolicyConfig
from app.brain.contracts import BrainDecision, DecisionPolicy, MarketSnapshot, SymbolSnapshot
from app.brain.identity import RULER_VERSION, ruler_fingerprint
from app.brain.evaluation.stats import (
    calibration_band as _calibration_band,
    confidence_discrimination_pct as _confidence_discrimination_pct,
    max_drawdown_pct as _max_drawdown_pct,
    mean as _mean,
    percentile as _percentile,
    spearman_ic as _spearman_ic,
    wilson_lower_bound_pct as _wilson_lower_bound_pct,
    worst_decile_mean as _worst_decile_mean,
)
from app.brain.candidate_quality import (
    atr_pct as _atr_pct,
    buy_candidate_reject_reason,
    historical_buy_hold_avg_return as _historical_buy_hold_avg_return,
    momentum_from_bars as _momentum_from_bars,
    momentum_pct as _momentum_pct,
    relative_strength_vs_market as _relative_strength_vs_market,
    rsi as _rsi,
    sma as _sma,
    volume_confirmed as _volume_confirmed,
)
from app.brain.gates import expected_value_after_friction
from app.brain.probability import compute_upside_probability
from app.brain.structural_prediction import (
    build_structural_prediction,
    evaluate_exit_window_outcome_with_disambiguation,
    evaluate_prediction_accuracy,
)
from app.brain.weekly_backtest import summarize_pattern_stats, walk_forward_pattern_samples
from app.brain.weekly_bar_utils import (
    bars_as_of,
    close_price,
    forward_close_after,
    parse_bar_timestamp,
    sorted_bars,
)
from app.brain.weekly_patterns import detect_weekly_pattern, project_weekly_range
from app.brain.policies import WeeklyProbabilityPolicy
from app.config import Settings, get_settings
from app.core.decision_presentation import build_exit_window
from app.schemas import GateCheck, WeeklyPatternPrediction
from app.services.historical_bar_store import BarCoverage, HistoricalBarStore
from app.services.repository import ScanRepository
from app.services.walk_forward_repository import WalkForwardRepository

logger = logging.getLogger(__name__)

# Bump when the walk-forward engine's computation changes in a way that makes old
# metrics incomparable. Part of the run manifest for auditable, versioned reruns.
# v2: ruler hardening - non-overlapping eval schedule (proof_eval_step_days),
# Brier + missingness metrics, opportunity-matched buy-and-hold benchmark,
# trials ledger, survivorship/adjustment caveats, ruler-identity stamping.
WALK_FORWARD_ENGINE_VERSION = "wf-engine-v2"

# Evidence-relevant settings whose change should invalidate comparability of runs.
# Kept explicit (not "all settings") so trivial, non-evidence tweaks do not churn
# the fingerprint. Mirrors the campaign fingerprint intent in Phase 4.
_FINGERPRINT_SETTING_KEYS = (
    "proof_target_years",
    "proof_min_years",
    "proof_max_years",
    "proof_holdout_months",
    "proof_validation_months",
    "proof_step_days",
    "proof_eval_step_days",
    "proof_top_n_per_asset",
    "proof_min_pattern_samples",
    "proof_min_expected_value_pct",
    "proof_atr_target_mult",
    "proof_atr_stop_mult",
    "proof_min_volume_median_ratio",
    "weekly_forward_days",
    "weekly_forward_tolerance_days",
    "weekly_hold_return_tolerance_pct",
    "stock_slippage_bps",
    "stock_spread_bps",
    "stock_fee_bps",
    "crypto_slippage_bps",
    "crypto_spread_bps",
    "crypto_fee_bps",
)


def config_fingerprint(settings: Settings) -> str:
    """Stable SHA-256 over evidence-relevant settings + the engine version.

    Two runs with an identical fingerprint are comparable; a change to any listed
    setting yields a new fingerprint so incomparable results never mix.
    """
    payload: dict[str, Any] = {"engine_version": WALK_FORWARD_ENGINE_VERSION}
    for key in _FINGERPRINT_SETTING_KEYS:
        payload[key] = getattr(settings, key, None)
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def code_commit() -> str | None:
    """Best-effort current git commit for provenance; None outside a checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = (result.stdout or "").strip()
    return commit or None


_TRADING_DAYS_PER_MONTH = 21
_MARKET_BENCHMARK = {"stock": "SPY", "crypto": "BTC/USD"}
_REJECTION_REASONS = (
    "below_sma50",
    "rsi_overbought",
    "insufficient_pattern_samples",
    "pattern_edge_below_min",
    "nonpositive_expectancy",
    "no_edge_vs_buy_hold",
    "volume_not_confirmed",
    "expected_value_below_min",
)
# Stored sample_source → display track label used in metrics/verdicts.
# "validation" is the tuning-side segment between research and holdout; it is
# never used for the pilot verdict (holdout only).
_SAMPLE_SOURCE_TRACK = {
    "historical": "research",
    "validation": "validation",
    "out_of_sample": "holdout",
}


def _track_label_from_sample_source(sample_source: str | None) -> str | None:
    return _SAMPLE_SOURCE_TRACK.get(str(sample_source or "").strip())


def _rejection_bucket(
    tracker: dict[tuple[str, str], dict[str, Any]] | None,
    *,
    asset_type: str,
    sample_source: str,
) -> dict[str, Any] | None:
    if tracker is None:
        return None
    track = _track_label_from_sample_source(sample_source)
    if track is None:
        return None
    key = (asset_type, track)
    if key not in tracker:
        tracker[key] = {
            "attempted": 0,
            "accepted": 0,
            "reasons": {reason: 0 for reason in _REJECTION_REASONS},
        }
    return tracker[key]


def _record_candidate_attempt(
    tracker: dict[tuple[str, str], dict[str, Any]] | None,
    *,
    asset_type: str,
    sample_source: str,
) -> None:
    bucket = _rejection_bucket(tracker, asset_type=asset_type, sample_source=sample_source)
    if bucket is not None:
        bucket["attempted"] = int(bucket.get("attempted", 0)) + 1


def _record_candidate_acceptance(
    tracker: dict[tuple[str, str], dict[str, Any]] | None,
    *,
    asset_type: str,
    sample_source: str,
) -> None:
    bucket = _rejection_bucket(tracker, asset_type=asset_type, sample_source=sample_source)
    if bucket is not None:
        bucket["accepted"] = int(bucket.get("accepted", 0)) + 1


def _record_candidate_rejection(
    tracker: dict[tuple[str, str], dict[str, Any]] | None,
    *,
    asset_type: str,
    sample_source: str,
    reason: str,
) -> None:
    bucket = _rejection_bucket(tracker, asset_type=asset_type, sample_source=sample_source)
    if bucket is None:
        return
    reasons = bucket.setdefault("reasons", {})
    reasons[reason] = int(reasons.get(reason, 0)) + 1


def _rejection_diagnostic_rows(
    tracker: dict[tuple[str, str], dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (asset_type, track), bucket in sorted(tracker.items()):
        attempted = int(bucket.get("attempted", 0))
        accepted = int(bucket.get("accepted", 0))
        reasons = dict(bucket.get("reasons", {}))
        total_rejected = sum(int(reasons.get(reason, 0)) for reason in reasons)
        reason_names = list(_REJECTION_REASONS)
        reason_names.extend(sorted(reason for reason in reasons if reason not in _REJECTION_REASONS))
        total_rejection_rate = (
            round(total_rejected / attempted * 100.0, 4) if attempted else None
        )
        for reason in reason_names:
            rejected = int(reasons.get(reason, 0))
            rows.append(
                {
                    "asset_type": asset_type,
                    "track": track,
                    "reject_reason": reason,
                    "attempted_count": attempted,
                    "accepted_count": accepted,
                    "rejected_count": rejected,
                    "total_rejected_count": total_rejected,
                    "rejection_rate_pct": round(rejected / attempted * 100.0, 4) if attempted else None,
                    "total_rejection_rate_pct": total_rejection_rate,
                }
            )
    return rows


def _record_candidate_filter_diagnostic(
    tracker: dict[tuple[str, str, str, str], dict[str, Any]] | None,
    *,
    asset_type: str,
    sample_source: str,
    pattern_name: str,
    reject_reason: str,
    return_pct: float | None,
    benchmark_return_pct: float | None,
    scan_repository: ScanRepository,
) -> None:
    if tracker is None:
        return
    track = _track_label_from_sample_source(sample_source)
    if track is None:
        return
    key = (asset_type, track, pattern_name, reject_reason)
    bucket = tracker.setdefault(
        key,
        {
            "sample_count": 0,
            "resolved_count": 0,
            "hit_count": 0,
            "after_friction": [],
            "after_friction_stressed": [],
            "edge_vs_benchmark": [],
        },
    )
    bucket["sample_count"] = int(bucket.get("sample_count", 0)) + 1
    if return_pct is None:
        return

    bucket["resolved_count"] = int(bucket.get("resolved_count", 0)) + 1
    if return_pct > 0:
        bucket["hit_count"] = int(bucket.get("hit_count", 0)) + 1

    after_friction = scan_repository._apply_friction_to_return(
        return_pct, asset_type=asset_type, scenario="base"
    )
    if after_friction is not None:
        bucket.setdefault("after_friction", []).append(after_friction)
    after_friction_stressed = scan_repository._apply_friction_to_return(
        return_pct, asset_type=asset_type, scenario="stressed"
    )
    if after_friction_stressed is not None:
        bucket.setdefault("after_friction_stressed", []).append(after_friction_stressed)

    if benchmark_return_pct is None or after_friction is None:
        return
    benchmark_after_friction = scan_repository._apply_friction_to_return(
        benchmark_return_pct, asset_type=asset_type, scenario="base"
    )
    if benchmark_after_friction is not None:
        bucket.setdefault("edge_vs_benchmark", []).append(
            round(after_friction - benchmark_after_friction, 4)
        )


def _candidate_filter_diagnostic_rows(
    tracker: dict[tuple[str, str, str, str], dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (asset_type, track, pattern_name, reject_reason), bucket in sorted(tracker.items()):
        sample_count = int(bucket.get("sample_count", 0))
        resolved_count = int(bucket.get("resolved_count", 0))
        hit_count = int(bucket.get("hit_count", 0))
        rows.append(
            {
                "asset_type": asset_type,
                "track": track,
                "pattern_name": pattern_name,
                "reject_reason": reject_reason,
                "sample_count": sample_count,
                "resolved_count": resolved_count,
                "hit_rate_pct": (
                    round(hit_count / resolved_count * 100.0, 4)
                    if resolved_count
                    else None
                ),
                "avg_return_after_friction_pct": _mean(
                    list(bucket.get("after_friction", []))
                ),
                "avg_return_after_friction_stressed_pct": _mean(
                    list(bucket.get("after_friction_stressed", []))
                ),
                "edge_vs_benchmark_pct": _mean(
                    list(bucket.get("edge_vs_benchmark", []))
                ),
            }
        )
    return rows


def _record_selection_stage_diagnostic(
    tracker: dict[tuple[str, str, str, str], dict[str, Any]] | None,
    *,
    asset_type: str,
    sample_source: str,
    pattern_name: str,
    selection_stage: str,
    return_pct: float | None,
    benchmark_return_pct: float | None,
    scan_repository: ScanRepository,
) -> None:
    _record_candidate_filter_diagnostic(
        tracker,
        asset_type=asset_type,
        sample_source=sample_source,
        pattern_name=pattern_name,
        reject_reason=selection_stage,
        return_pct=return_pct,
        benchmark_return_pct=benchmark_return_pct,
        scan_repository=scan_repository,
    )


def _selection_stage_diagnostic_rows(
    tracker: dict[tuple[str, str, str, str], dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (asset_type, track, pattern_name, selection_stage), bucket in sorted(tracker.items()):
        sample_count = int(bucket.get("sample_count", 0))
        resolved_count = int(bucket.get("resolved_count", 0))
        hit_count = int(bucket.get("hit_count", 0))
        rows.append(
            {
                "asset_type": asset_type,
                "track": track,
                "pattern_name": pattern_name,
                "selection_stage": selection_stage,
                "sample_count": sample_count,
                "resolved_count": resolved_count,
                "hit_rate_pct": (
                    round(hit_count / resolved_count * 100.0, 4)
                    if resolved_count
                    else None
                ),
                "avg_return_after_friction_stressed_pct": _mean(
                    list(bucket.get("after_friction_stressed", []))
                ),
                "edge_vs_benchmark_pct": _mean(
                    list(bucket.get("edge_vs_benchmark", []))
                ),
            }
        )
    return rows


def _forward_return(
    bars: list[dict[str, Any]],
    *,
    as_of: datetime,
    forward_days: int,
    tolerance_days: int,
) -> float | None:
    usable = bars_as_of(bars, as_of)
    closes = [close_price(bar) for bar in usable if close_price(bar) > 0]
    if not closes:
        return None
    entry = closes[-1]
    future = forward_close_after(bars, as_of=as_of, forward_days=forward_days, tolerance_days=tolerance_days)
    if future is None or entry <= 0:
        return None
    return (future - entry) / entry * 100.0


def _volatility_regime_from_closes(closes: list[float]) -> str:
    recent = [value for value in closes[-15:] if value > 0]
    if len(recent) < 2:
        return "normal"
    moves = [
        abs(recent[index] - recent[index - 1]) / recent[index - 1] * 100.0
        for index in range(1, len(recent))
        if recent[index - 1] > 0
    ]
    if not moves:
        return "normal"
    avg_move = sum(moves) / len(moves)
    if avg_move < 1.0:
        return "low"
    if avg_move < 2.0:
        return "normal"
    if avg_move < 3.5:
        return "elevated"
    if avg_move < 5.0:
        return "high"
    return "extreme"


def _benchmark_regime(market_bars: list[dict[str, Any]] | None, as_of: datetime) -> str:
    """Classify the market regime at as_of using benchmark 50/200-day SMAs.

    bull  = price > SMA50 > SMA200, bear = price < SMA50 < SMA200, else chop.
    Returns "unknown" when the benchmark lacks enough history to classify, so
    unclassifiable periods are never miscounted as a passed regime.
    """
    if not market_bars:
        return "unknown"
    visible = bars_as_of(market_bars, as_of)
    closes = [close_price(bar) for bar in visible if close_price(bar) > 0]
    if len(closes) < 200:
        return "unknown"
    price = closes[-1]
    sma50 = _sma(closes, 50)
    sma200 = _sma(closes, 200)
    if sma50 is None or sma200 is None:
        return "unknown"
    if price > sma50 > sma200:
        return "bull"
    if price < sma50 < sma200:
        return "bear"
    return "chop"


class WalkForwardProofService:
    """Historical walk-forward proof engine.

    Stands at old dates using only prior daily data (no lookahead), makes the same
    top-candidate weekly predictions it would make live, resolves them one week
    forward, and reports upside accuracy, calibration, exit-window accuracy,
    after-friction return, and tail risk. Strictly separated from live-forward proof.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        bar_store: HistoricalBarStore | None = None,
        repository: WalkForwardRepository | None = None,
        scan_repository: ScanRepository | None = None,
        replay_policy: DecisionPolicy | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.bar_store = bar_store or HistoricalBarStore(settings=self.settings)
        self.repository = repository or WalkForwardRepository()
        self.scan_repository = scan_repository or ScanRepository()
        if replay_policy is not None and not replay_policy.replayable:
            raise ValueError("Walk-forward proof can only evaluate replayable DecisionPolicy instances.")
        self.replay_policy = replay_policy

    def _policy_identity(self) -> dict[str, Any]:
        policy = self.replay_policy or WeeklyProbabilityPolicy(
            config=WeeklyPolicyConfig.from_settings(self.settings),
            reliability_maps={},
            extra_stats={},
        )
        learned_fingerprint = None
        learned_json = None
        learned_fingerprint_fn = getattr(policy, "learned_artifacts_fingerprint", None)
        if callable(learned_fingerprint_fn):
            learned_fingerprint = learned_fingerprint_fn()
        learned_identity_fn = getattr(policy, "learned_artifact_identity", None)
        if callable(learned_identity_fn):
            learned_json = json.dumps(learned_identity_fn(), sort_keys=True, default=str)
        return {
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "decision_fingerprint": policy.fingerprint(),
            "learned_artifacts_fingerprint": learned_fingerprint,
            "learned_artifacts_json": learned_json,
        }

    # --- date selection -------------------------------------------------

    def select_replay_dates(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        step_days: int,
    ) -> list[datetime]:
        dates: list[datetime] = []
        cursor = window_start
        step = max(1, int(step_days))
        while cursor <= window_end:
            dates.append(cursor)
            cursor += timedelta(days=step)
        return dates

    def _window(
        self, *, years: int, forward_days: int
    ) -> tuple[datetime, datetime, datetime, datetime]:
        now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        tolerance = int(self.settings.weekly_forward_tolerance_days)
        context_min_days = int(self.settings.proof_lookback_context_months_min) * 30
        window_end = now - timedelta(days=forward_days + tolerance + 1)
        window_start = now - timedelta(days=int(years * 365)) + timedelta(days=context_min_days)
        holdout_start = now - timedelta(days=int(self.settings.proof_holdout_months) * 30)
        # Validation sits immediately before the holdout. Tuning is permitted on
        # research+validation; the holdout is never used to tune, only to verdict.
        validation_start = holdout_start - timedelta(
            days=int(self.settings.proof_validation_months) * 30
        )
        return window_start, window_end, holdout_start, validation_start

    def _track_for(
        self,
        as_of: datetime,
        holdout_start: datetime,
        validation_start: datetime | None = None,
    ) -> str:
        """Assign the research / validation / holdout sample_source for as_of.

        Holdout is the final segment (never used for tuning). Validation sits
        immediately before holdout and may be used with research for tuning.
        Everything earlier is research.
        """
        if as_of >= holdout_start:
            return "out_of_sample"
        if validation_start is not None and as_of >= validation_start:
            return "validation"
        return "historical"

    # --- prediction (no-lookahead) --------------------------------------

    def build_prediction_at(
        self,
        *,
        symbol: str,
        asset_type: str,
        bars: list[dict[str, Any]],
        as_of: datetime,
        market_bars: list[dict[str, Any]] | None = None,
        sample_source: str = "historical",
        rejection_tracker: dict[tuple[str, str], dict[str, Any]] | None = None,
        candidate_filter_tracker: dict[tuple[str, str, str, str], dict[str, Any]] | None = None,
        selection_stage_tracker: dict[tuple[str, str, str, str], dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Build a BUY candidate prediction using only bars on or before as_of.

        Returns None when there is not enough prior context, the detected pattern is
        not a BUY, or point-in-time pattern samples are too few to rank a candidate.
        """
        context_min_bars = max(
            int(self.settings.proof_lookback_context_months_min) * _TRADING_DAYS_PER_MONTH,
            40,
        )
        context_max_bars = max(
            int(self.settings.proof_lookback_context_months_max) * _TRADING_DAYS_PER_MONTH,
            context_min_bars,
        )
        usable = bars_as_of(bars, as_of)
        if len(usable) < context_min_bars:
            return None
        pattern = detect_weekly_pattern(usable, as_of=as_of)
        if pattern is None or pattern.decision_signal != "BUY":
            return None

        closes = [close_price(bar) for bar in usable if close_price(bar) > 0]
        if len(closes) < 20:
            return None
        _record_candidate_attempt(
            rejection_tracker, asset_type=asset_type, sample_source=sample_source
        )
        entry_price = closes[-1]
        context_closes = closes[-context_max_bars:]
        outcome_cache: tuple[float | None, float | None] | None = None

        def candidate_outcome() -> tuple[float | None, float | None]:
            nonlocal outcome_cache
            if outcome_cache is not None:
                return outcome_cache
            forward_days = int(self.settings.weekly_forward_days)
            tolerance_days = int(self.settings.weekly_forward_tolerance_days)
            return_pct = _forward_return(
                bars,
                as_of=as_of,
                forward_days=forward_days,
                tolerance_days=tolerance_days,
            )
            benchmark_return_pct = _forward_return(
                market_bars or [],
                as_of=as_of,
                forward_days=forward_days,
                tolerance_days=tolerance_days,
            )
            outcome_cache = (return_pct, benchmark_return_pct)
            return outcome_cache

        def record_filter_outcome(reject_reason: str) -> None:
            if candidate_filter_tracker is None:
                return
            return_pct, benchmark_return_pct = candidate_outcome()
            _record_candidate_filter_diagnostic(
                candidate_filter_tracker,
                asset_type=asset_type,
                sample_source=sample_source,
                pattern_name=pattern.pattern_name,
                reject_reason=reject_reason,
                return_pct=return_pct,
                benchmark_return_pct=benchmark_return_pct,
                scan_repository=self.scan_repository,
            )

        def record_selection_stage(selection_stage: str) -> None:
            if selection_stage_tracker is None:
                return
            return_pct, benchmark_return_pct = candidate_outcome()
            _record_selection_stage_diagnostic(
                selection_stage_tracker,
                asset_type=asset_type,
                sample_source=sample_source,
                pattern_name=pattern.pattern_name,
                selection_stage=selection_stage,
                return_pct=return_pct,
                benchmark_return_pct=benchmark_return_pct,
                scan_repository=self.scan_repository,
            )

        atr_pct = _atr_pct(usable, int(self.settings.proof_atr_lookback_days))
        momentum = _momentum_pct(closes, int(self.settings.proof_momentum_lookback_days))

        warmup = min(60, max(20, len(usable) // 3))
        samples = walk_forward_pattern_samples(
            usable,
            sample_source="historical",
            warmup_bars=warmup,
            step_days=int(self.settings.proof_step_days),
            forward_days=int(self.settings.weekly_forward_days),
            tolerance_days=int(self.settings.weekly_forward_tolerance_days),
            hold_return_tolerance_pct=float(self.settings.weekly_hold_return_tolerance_pct),
        )
        stats = summarize_pattern_stats(samples, pattern_name=pattern.pattern_name)
        reject_reason = buy_candidate_reject_reason(
            bars=usable,
            closes=closes,
            entry_price=entry_price,
            as_of=as_of,
            settings=self.settings,
            stats=stats,
            warmup_bars=warmup,
            step_days=int(self.settings.proof_step_days),
        )
        if reject_reason is not None:
            _record_candidate_rejection(
                rejection_tracker,
                asset_type=asset_type,
                sample_source=sample_source,
                reason=reject_reason,
            )
            record_filter_outcome(reject_reason)
            record_selection_stage("rejected")
            return None

        relative_strength = _relative_strength_vs_market(
            usable,
            market_bars,
            as_of=as_of,
            lookback=int(self.settings.proof_momentum_lookback_days),
        )
        upside = compute_upside_probability(
            hit_rate_pct=stats.hit_rate_pct,
            sample_size=stats.sample_size,
            directional_bias=pattern.directional_bias,
            shrinkage_k=float(self.settings.upside_prob_shrinkage_k),
            trend_strength_pct=momentum,
            relative_strength_pct=relative_strength,
        )
        if upside is None:
            return None
        data_quality = self._data_quality(len(usable))
        confidence = self._evidence_confidence(
            sample_size=stats.sample_size,
            data_quality=data_quality,
            hit_rate_pct=stats.hit_rate_pct,
        )

        range_low, range_high = project_weekly_range(
            price=entry_price, pattern=pattern, closes=context_closes
        )
        weekly_prediction = WeeklyPatternPrediction(
            pattern_name=pattern.pattern_name,
            directional_bias=pattern.directional_bias,
            range_low=range_low,
            range_high=range_high,
            upside_probability_pct=upside,
            historical_hit_rate_pct=stats.hit_rate_pct,
            avg_forward_1w_return_pct=stats.avg_forward_return_pct,
            sample_size=stats.sample_size,
            data_quality=data_quality,
            forward_days=int(self.settings.weekly_forward_days),
            evidence_basis="historical_only",
            real_money_trust_blocked=True,
        )
        volatility_regime = _volatility_regime_from_closes(closes)
        structural = build_structural_prediction(
            price=entry_price,
            decision_signal="BUY",
            volatility_regime=volatility_regime,
            horizon="1w",
            asset_type=asset_type,
            atr_pct=atr_pct,
            atr_target_mult=float(self.settings.proof_atr_target_mult),
            atr_stop_mult=float(self.settings.proof_atr_stop_mult),
        )
        exit_window = build_exit_window(
            price=entry_price,
            weekly_prediction=weekly_prediction,
            price_prediction=structural,
            decision_signal="BUY",
            evidence_quality="moderate" if stats.sample_size >= 30 else "low",
            data_quality=data_quality,
            forward_days=int(self.settings.weekly_forward_days),
        )
        estimated_exit_price = exit_window.estimated_exit_price if exit_window else range_high
        invalidation_level = exit_window.invalidation_level if exit_window else range_low
        # Expected-value gate: skip candidates whose reward/risk fails to clear friction.
        friction_pct = self.scan_repository._friction_bps_for_asset_type(asset_type) / 100.0
        expected_value = expected_value_after_friction(
            upside_probability_pct=upside,
            entry_price=entry_price,
            target_price=estimated_exit_price,
            invalidation_price=invalidation_level,
            friction_pct=friction_pct,
        )
        if expected_value is not None and expected_value <= float(self.settings.proof_min_expected_value_pct):
            _record_candidate_rejection(
                rejection_tracker,
                asset_type=asset_type,
                sample_source=sample_source,
                reason="expected_value_below_min",
            )
            record_filter_outcome("expected_value_below_min")
            record_selection_stage("rejected")
            return None

        _record_candidate_acceptance(
            rejection_tracker, asset_type=asset_type, sample_source=sample_source
        )
        record_filter_outcome("accepted")
        forward_days = int(self.settings.weekly_forward_days)
        return {
            "as_of": as_of,
            "asset_type": asset_type,
            "ticker": symbol.upper(),
            "selection_rank": 0,
            "sample_source": sample_source,
            "pattern_name": pattern.pattern_name,
            "decision_signal": "BUY",
            "confidence": round(confidence, 4),
            "upside_probability_pct": upside,
            "historical_hit_rate_pct": stats.hit_rate_pct,
            "sample_size": stats.sample_size,
            "entry_price": round(entry_price, 6),
            "projected_range_low": range_low,
            "projected_range_high": range_high,
            "estimated_exit_price": estimated_exit_price,
            "invalidation_level": invalidation_level,
            "stop_growing_signal": exit_window.stop_growing_signal if exit_window else None,
            "horizon": "1w",
            "forward_days": forward_days,
            "expected_friction_bps": round(
                self.scan_repository._friction_bps_for_asset_type(asset_type), 4
            ),
            "generated_at": as_of,
            "resolve_due_at": as_of + timedelta(days=forward_days),
            "status": "pending",
            "policy_id": "weekly_probability",
        }

    def _data_quality(self, bar_count: int) -> str:
        if bar_count >= self.settings.weekly_daily_lookback_bars_preferred:
            return "ok"
        if bar_count >= self.settings.weekly_daily_lookback_bars_min:
            return "low"
        return "degraded"

    def _snapshot_for_policy(
        self,
        *,
        as_of: datetime,
        bars_by_symbol: dict[str, list[dict[str, Any]]],
        asset_by_symbol: dict[str, str],
        market_bars: dict[str, list[dict[str, Any]]],
    ) -> MarketSnapshot:
        symbols: list[SymbolSnapshot] = []
        for symbol, bars in sorted(bars_by_symbol.items()):
            usable = bars_as_of(bars, as_of)
            if not usable:
                continue
            asset_type = asset_by_symbol.get(symbol) or HistoricalBarStore.resolve_asset_type(symbol)
            symbols.append(
                SymbolSnapshot(
                    symbol=symbol,
                    asset_type=asset_type,  # type: ignore[arg-type]
                    daily_bars=usable,
                    data_quality=self._data_quality(len(usable)),
                    daily_bars_stale=False,
                    daily_bars_source="historical_bar_store",
                )
            )
        benchmarks = {
            "SPY": bars_as_of(market_bars.get("stock") or [], as_of),
            "BTC/USD": bars_as_of(market_bars.get("crypto") or [], as_of),
        }
        return MarketSnapshot(
            as_of=as_of,
            symbols=tuple(symbols),
            benchmark_daily_bars=benchmarks,
            universe_source="current_watchlist",
        )

    def _prediction_from_policy_decision(
        self,
        decision: BrainDecision,
        *,
        sample_source: str,
    ) -> dict[str, Any] | None:
        """Convert a replayable policy BUY into the stored WF prediction shape."""
        if decision.action != "BUY" or decision.exit_plan is None:
            return None
        entry_price = float(decision.exit_plan.entry_price or 0.0)
        if entry_price <= 0:
            return None
        upside = decision.p_up_calibrated
        if upside is None:
            return None
        sample_sizes = decision.evidence_basis.sample_sizes or {}
        sample_size = int((decision.diagnostics or {}).get("sample_size") or max(sample_sizes.values(), default=0))
        range_low = (
            float(decision.exit_plan.stop_price)
            if decision.exit_plan.stop_price is not None
            else entry_price
        )
        range_high = (
            float(decision.exit_plan.target_price)
            if decision.exit_plan.target_price is not None
            else entry_price
        )
        forward_days = int(decision.exit_plan.horizon_days or self.settings.weekly_forward_days)
        return {
            "as_of": decision.as_of,
            "asset_type": decision.asset_type,
            "ticker": decision.symbol.upper(),
            "selection_rank": 0,
            "sample_source": sample_source,
            "pattern_name": decision.pattern_name or decision.policy_id,
            "decision_signal": "BUY",
            "confidence": round(float(upside), 4),
            "upside_probability_pct": round(float(upside), 4),
            "historical_hit_rate_pct": decision.evidence_basis.historical_hit_rate_pct,
            "sample_size": sample_size,
            "entry_price": round(entry_price, 6),
            "projected_range_low": round(range_low, 6),
            "projected_range_high": round(range_high, 6),
            "estimated_exit_price": round(range_high, 6),
            "invalidation_level": round(range_low, 6),
            "stop_growing_signal": None,
            "horizon": "1w",
            "forward_days": forward_days,
            "expected_friction_bps": round(
                self.scan_repository._friction_bps_for_asset_type(decision.asset_type), 4
            ),
            "generated_at": decision.as_of,
            "resolve_due_at": decision.as_of + timedelta(days=forward_days),
            "status": "pending",
            "policy_id": decision.policy_id,
            "policy_version": decision.policy_version,
            "decision_fingerprint": decision.decision_fingerprint,
        }

    def _policy_predictions_at(
        self,
        *,
        policy: DecisionPolicy,
        as_of: datetime,
        sample_source: str,
        bars_by_symbol: dict[str, list[dict[str, Any]]],
        asset_by_symbol: dict[str, str],
        market_bars: dict[str, list[dict[str, Any]]],
    ) -> dict[str, list[dict[str, Any]]]:
        snapshot = self._snapshot_for_policy(
            as_of=as_of,
            bars_by_symbol=bars_by_symbol,
            asset_by_symbol=asset_by_symbol,
            market_bars=market_bars,
        )
        by_asset: dict[str, list[dict[str, Any]]] = {"stock": [], "crypto": []}
        learned_fingerprint = None
        learned_fingerprint_fn = getattr(policy, "learned_artifacts_fingerprint", None)
        if callable(learned_fingerprint_fn):
            learned_fingerprint = learned_fingerprint_fn()
        for decision in policy.decide_all(snapshot):
            prediction = self._prediction_from_policy_decision(
                decision,
                sample_source=sample_source,
            )
            if prediction is not None:
                prediction["learned_artifacts_fingerprint"] = learned_fingerprint
                by_asset.setdefault(prediction["asset_type"], []).append(prediction)
        return by_asset

    def _evidence_confidence(
        self,
        *,
        sample_size: int,
        data_quality: str,
        hit_rate_pct: float | None,
    ) -> float:
        """Confidence = evidence strength, distinct from the upside probability.

        Grows with sample size (shrunk), scaled by data quality and how far the
        pattern edge sits above coin-flip. Two candidates with the same P(up) can
        differ in confidence when one rests on far more/cleaner evidence.
        """
        n = float(max(0, sample_size))
        k = max(0.0, float(self.settings.proof_confidence_shrinkage_k))
        sample_factor = n / (n + k) if (n + k) > 0 else 0.0
        dq_mult = {"ok": 1.0, "low": 0.85, "degraded": 0.6}.get(data_quality, 0.6)
        edge = 0.5 if hit_rate_pct is None else max(0.2, min(1.0, 0.5 + (float(hit_rate_pct) - 50.0) / 50.0))
        return round(100.0 * sample_factor * dq_mult * edge, 2)

    # --- resolution -----------------------------------------------------

    def resolve_prediction(
        self,
        prediction: dict[str, Any],
        *,
        bars: list[dict[str, Any]],
    ) -> dict[str, Any]:
        as_of = prediction["as_of"]
        forward_days = int(prediction.get("forward_days", self.settings.weekly_forward_days))
        tolerance = int(self.settings.weekly_forward_tolerance_days)
        entry = float(prediction["entry_price"])
        future_price = forward_close_after(
            bars, as_of=as_of, forward_days=forward_days, tolerance_days=tolerance
        )
        if future_price is None or entry <= 0:
            prediction["status"] = "pending"
            return prediction

        return_pct = round(((future_price - entry) / entry) * 100.0, 4)
        accuracy = evaluate_prediction_accuracy(
            decision_signal="BUY",
            range_low=float(prediction.get("projected_range_low") or entry),
            range_high=float(prediction.get("projected_range_high") or entry),
            price_at_horizon=future_price,
        )
        forward_bars = self._forward_path(bars, as_of=as_of, forward_days=forward_days, tolerance=tolerance)
        friction_pct = self.scan_repository._friction_bps_for_asset_type(prediction["asset_type"]) / 100.0
        exit_outcome = evaluate_exit_window_outcome_with_disambiguation(
            entry_price=entry,
            estimated_exit_price=prediction.get("estimated_exit_price"),
            invalidation_level=prediction.get("invalidation_level"),
            price_at_horizon=future_price,
            decision_signal="BUY",
            bars=forward_bars,
            finer_bars_by_index=self._finer_bars_by_index(forward_bars),
            friction_pct=friction_pct,
        )
        prediction.update(
            {
                "status": "resolved",
                "price_after_1w": round(future_price, 6),
                "return_after_1w": return_pct,
                "in_range": accuracy.in_range,
                "accuracy_outcome": accuracy.outcome,
                "exit_window_status": exit_outcome.exit_window_status,
                "exit_hit": exit_outcome.exit_hit,
                "invalidation_hit": exit_outcome.invalidation_hit,
                "protected_return_pct": exit_outcome.protected_return_pct,
                "hold_return_pct": exit_outcome.hold_return_pct,
                "exit_window_helped": exit_outcome.exit_window_helped,
                "exit_conflict": exit_outcome.exit_conflict,
                "evaluated_at": datetime.now(timezone.utc),
            }
        )
        return prediction

    def _finer_bars_by_index(
        self, forward_bars: list[dict[str, Any]]
    ) -> dict[int, list[dict[str, Any]]] | None:
        """Finer (intraday) bars per daily bar index for exit/stop disambiguation.

        The historical proof store holds daily bars only, so no finer resolution is
        available and this returns None. On a daily bar that touches both the exit and
        the invalidation level the resolver then keeps its fail-closed default
        (assume invalidation) rather than optimistically crediting the exit.
        """
        return None

    def _forward_path(
        self,
        bars: list[dict[str, Any]],
        *,
        as_of: datetime,
        forward_days: int,
        tolerance: int,
    ) -> list[dict[str, Any]]:
        comparable = as_of.astimezone(timezone.utc) if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        end = comparable + timedelta(days=forward_days + tolerance)
        path: list[dict[str, Any]] = []
        for bar in sorted_bars(bars):
            parsed = parse_bar_timestamp(bar.get("t"))
            if comparable < parsed <= end:
                path.append(bar)
        return path

    # --- run orchestration ----------------------------------------------

    async def run(
        self,
        *,
        symbols: list[str] | None = None,
        years: int | None = None,
        step_days: int | None = None,
        top_n_per_asset: int | None = None,
        force_refresh: bool = False,
        persist: bool = True,
    ) -> tuple[str, dict[str, Any]]:
        target_years = int(years or self.settings.proof_effective_years)
        # The ruler's evaluation schedule (replay-date step), distinct from the
        # policy's own nested sampling step (proof_step_days).
        step = int(step_days or self.settings.proof_eval_step_days)
        top_n = max(3, min(5, int(top_n_per_asset or self.settings.proof_effective_top_n_per_asset)))
        forward_days = int(self.settings.weekly_forward_days)
        tolerance_days = int(self.settings.weekly_forward_tolerance_days)

        resolved_symbols = symbols or (
            self.settings.watchlist_items + self.settings.crypto_watchlist_items
        )
        resolved_symbols = [s.upper() for s in resolved_symbols]
        # SPY/QQQ are benchmarks, excluded from candidate ranking like the live scan.
        resolved_symbols = [s for s in resolved_symbols if s not in {"SPY", "QQQ"}]

        window_start, window_end, holdout_start, validation_start = self._window(
            years=target_years, forward_days=forward_days
        )
        as_of_dates = self.select_replay_dates(
            window_start=window_start, window_end=window_end, step_days=step
        )
        # Overlap invariant: consecutive evaluated predictions must not share any
        # part of the forward resolution window (forward days + tolerance). We
        # record status rather than hard-failing so a deliberately overlapping
        # research run stays possible but is labelled.
        overlap_status = (
            "non_overlapping" if step >= forward_days + tolerance_days else "overlapping"
        )

        bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
        asset_by_symbol: dict[str, str] = {}
        coverage: list[dict[str, Any]] = []
        for symbol in resolved_symbols:
            asset_type = HistoricalBarStore.resolve_asset_type(symbol)
            asset_by_symbol[symbol] = asset_type
            cover: BarCoverage = await self.bar_store.ensure_history(
                symbol, asset_type=asset_type, years=target_years, force_refresh=force_refresh
            )
            coverage.append(cover.as_dict())
            bars_by_symbol[symbol] = sorted_bars(
                self.bar_store.load_bars(symbol, asset_type=asset_type)
            )

        market_bars = await self._load_market_bars(
            target_years=target_years,
            force_refresh=force_refresh,
            asset_types=set(asset_by_symbol.values()),
        )
        policy_identity = self._policy_identity()

        predictions: list[dict[str, Any]] = []
        rejection_tracker: dict[tuple[str, str], dict[str, Any]] = {}
        candidate_filter_tracker: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        selection_stage_tracker: dict[tuple[str, str, str, str], dict[str, Any]] = {}

        def record_selection_stage_for_prediction(
            prediction: dict[str, Any], selection_stage: str
        ) -> None:
            asset_type = str(prediction["asset_type"])
            bars = bars_by_symbol.get(str(prediction["ticker"])) or []
            as_of = prediction["as_of"]
            return_pct = _forward_return(
                bars,
                as_of=as_of,
                forward_days=forward_days,
                tolerance_days=int(self.settings.weekly_forward_tolerance_days),
            )
            benchmark_return_pct = _forward_return(
                market_bars.get(asset_type) or [],
                as_of=as_of,
                forward_days=forward_days,
                tolerance_days=int(self.settings.weekly_forward_tolerance_days),
            )
            _record_selection_stage_diagnostic(
                selection_stage_tracker,
                asset_type=asset_type,
                sample_source=str(prediction.get("sample_source") or ""),
                pattern_name=str(prediction.get("pattern_name") or "unknown"),
                selection_stage=selection_stage,
                return_pct=return_pct,
                benchmark_return_pct=benchmark_return_pct,
                scan_repository=self.scan_repository,
            )

        for as_of in as_of_dates:
            track = self._track_for(as_of, holdout_start, validation_start)
            if self.replay_policy is not None:
                by_asset = self._policy_predictions_at(
                    policy=self.replay_policy,
                    as_of=as_of,
                    sample_source=track,
                    bars_by_symbol=bars_by_symbol,
                    asset_by_symbol=asset_by_symbol,
                    market_bars=market_bars,
                )
            else:
                by_asset = {"stock": [], "crypto": []}
                for symbol in resolved_symbols:
                    bars = bars_by_symbol.get(symbol) or []
                    if not bars:
                        continue
                    asset_type = asset_by_symbol[symbol]
                    prediction = self.build_prediction_at(
                        symbol=symbol,
                        asset_type=asset_type,
                        bars=bars,
                        as_of=as_of,
                        market_bars=market_bars.get(asset_type),
                        sample_source=track,
                        rejection_tracker=rejection_tracker,
                        candidate_filter_tracker=candidate_filter_tracker,
                        selection_stage_tracker=selection_stage_tracker,
                    )
                    if prediction is None:
                        continue
                    prediction["sample_source"] = track
                    prediction["policy_id"] = policy_identity["policy_id"]
                    prediction["policy_version"] = policy_identity["policy_version"]
                    prediction["decision_fingerprint"] = policy_identity["decision_fingerprint"]
                    prediction["learned_artifacts_fingerprint"] = policy_identity[
                        "learned_artifacts_fingerprint"
                    ]
                    by_asset.setdefault(prediction["asset_type"], []).append(prediction)

            for asset_type, candidates in by_asset.items():
                candidates.sort(
                    key=lambda item: (
                        -float(item["upside_probability_pct"] or 0.0),
                        -float(item["confidence"]),
                        -int(item["sample_size"]),
                        item["ticker"],
                    )
                )
                selected = candidates[:top_n]
                for prediction in candidates[top_n:]:
                    record_selection_stage_for_prediction(
                        prediction, "accepted_not_selected"
                    )
                for rank, prediction in enumerate(selected, start=1):
                    record_selection_stage_for_prediction(
                        prediction, "selected_top_n"
                    )
                    prediction["selection_rank"] = rank
                    resolved = self.resolve_prediction(
                        prediction, bars=bars_by_symbol.get(prediction["ticker"], [])
                    )
                    predictions.append(resolved)

        benchmarks = self.compute_benchmarks(
            predictions=predictions,
            as_of_dates=as_of_dates,
            bars_by_symbol=bars_by_symbol,
            asset_by_symbol=asset_by_symbol,
            market_bars=market_bars,
            holdout_start=holdout_start,
            top_n=top_n,
            validation_start=validation_start,
        )
        crypto_history_ok = self._crypto_history_sufficient(coverage)
        metrics = self.compute_metrics(
            predictions,
            market_bars=market_bars,
            rejection_diagnostics=_rejection_diagnostic_rows(rejection_tracker),
            candidate_filter_diagnostics=_candidate_filter_diagnostic_rows(
                candidate_filter_tracker
            ),
            selection_stage_diagnostics=_selection_stage_diagnostic_rows(
                selection_stage_tracker
            ),
        )
        metrics["benchmarks"] = benchmarks
        self._merge_benchmark_edges(metrics, benchmarks)
        verdict = self.compute_verdict(metrics, crypto_history_ok=crypto_history_ok)

        # Data-quality QC over every symbol in the run universe. Issues degrade the
        # run verdict to keep dirty data from masquerading as clean evidence.
        qc_issues: list[str] = []
        quality_check = getattr(self.bar_store, "quality_check", None)
        if callable(quality_check):
            for symbol in resolved_symbols:
                qc_issues.extend(
                    quality_check(symbol, asset_type=asset_by_symbol.get(symbol))
                )
        data_quality_ok = len(qc_issues) == 0
        data_quality = {"ok": data_quality_ok, "issues": qc_issues[:100]}
        if not data_quality_ok:
            verdict["ready"] = False
            verdict["summary"] = (
                verdict.get("summary", "")
                + " Data-quality checks failed; verdict degraded until history is clean."
            ).strip()

        fingerprint = config_fingerprint(self.settings)
        commit = code_commit()
        ruler_config = RulerConfig.from_settings(self.settings)
        ruler_id = ruler_fingerprint(config_payload=ruler_config.payload())

        # Trials ledger: how many distinct configurations have been tried against
        # this history. Many trials inflate the chance that a passing verdict is
        # a multiple-testing artifact; the verdict must carry that context.
        try:
            prior_fingerprints = self.repository.count_distinct_fingerprints()
            prior_runs = self.repository.count_runs()
        except Exception:
            prior_fingerprints, prior_runs = 0, 0
        trials = {
            "distinct_config_fingerprints": prior_fingerprints
            + (0 if self.repository.fingerprint_seen(fingerprint) else 1),
            "total_runs": prior_runs + 1,
            "note": (
                "Every distinct configuration evaluated against this history is one "
                "trial. The more trials, the weaker any single passing verdict."
            ),
        }

        caveats = [
            (
                "Survivorship: the replay universe is the current watchlist; symbols "
                "that failed and were delisted or dropped are not represented, which "
                "biases historical results upward."
            ),
            (
                "Adjustment policy: stock bars are split-adjusted only (dividends not "
                "reinvested); crypto history may mix Alpaca and Polygon sources."
            ),
        ]

        manifest = {
            "config_fingerprint": fingerprint,
            "code_commit": commit,
            "engine_version": WALK_FORWARD_ENGINE_VERSION,
            "policy_id": policy_identity["policy_id"],
            "policy_version": policy_identity["policy_version"],
            "decision_fingerprint": policy_identity["decision_fingerprint"],
            "learned_artifacts_fingerprint": policy_identity["learned_artifacts_fingerprint"],
            "learned_artifacts_json": policy_identity["learned_artifacts_json"],
            "ruler_version": RULER_VERSION,
            "ruler_fingerprint": ruler_id,
            "validation_start": validation_start,
            "universe": resolved_symbols,
            "universe_source": "current_watchlist",
            "overlap_status": overlap_status,
            "data_quality": data_quality,
            "trials": trials,
            "caveats": caveats,
        }
        verdict["trials"] = trials
        verdict["caveats"] = caveats
        # Deterministic run id over the manifest + window so stored-bar reruns with
        # an identical configuration produce the same id (and thus identical rows).
        determinism_key = json.dumps(
            {
                "fingerprint": fingerprint,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "holdout_start": holdout_start.isoformat(),
                "step": step,
                "top_n": top_n,
                "universe": resolved_symbols,
            },
            sort_keys=True,
            default=str,
        )
        run_id = "wf-" + hashlib.sha256(determinism_key.encode("utf-8")).hexdigest()[:16]

        if persist and self.repository.tables_ready():
            self.repository.persist_run(
                run_id=run_id,
                params={
                    "target_years": target_years,
                    "step_days": step,
                    "top_n_per_asset": top_n,
                    "forward_days": forward_days,
                    "symbols": resolved_symbols,
                    "holdout_months": int(self.settings.proof_holdout_months),
                    "validation_months": int(self.settings.proof_validation_months),
                    "overlap_status": overlap_status,
                    "ruler_version": RULER_VERSION,
                    "ruler_fingerprint": ruler_id,
                },
                window_start=window_start,
                window_end=window_end,
                holdout_start=holdout_start,
                symbol_count=len(resolved_symbols),
                predictions=predictions,
                metrics=metrics,
                verdict=verdict,
                coverage=coverage,
                manifest=manifest,
            )

        summary = {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "holdout_start": holdout_start.isoformat(),
            "validation_start": validation_start.isoformat(),
            "target_years": target_years,
            "step_days": step,
            "forward_days": forward_days,
            "top_n_per_asset": top_n,
            "symbol_count": len(resolved_symbols),
            "prediction_count": len(predictions),
            "resolved_count": metrics.get("resolved_count", 0),
            "pending_count": metrics.get("pending_count", 0),
            "by_asset_track": metrics.get("by_asset_track", []),
            "calibration_buckets": metrics.get("calibration_buckets", []),
            "pattern_diagnostics": metrics.get("pattern_diagnostics", []),
            "rejection_diagnostics": metrics.get("rejection_diagnostics", []),
            "candidate_filter_diagnostics": metrics.get(
                "candidate_filter_diagnostics", []
            ),
            "selection_stage_diagnostics": metrics.get(
                "selection_stage_diagnostics", []
            ),
            "benchmarks": metrics.get("benchmarks", []),
            "coverage": coverage,
            "pilot_verdict": verdict,
            "config_fingerprint": fingerprint,
            "code_commit": commit,
            "engine_version": WALK_FORWARD_ENGINE_VERSION,
            "policy_id": policy_identity["policy_id"],
            "policy_version": policy_identity["policy_version"],
            "decision_fingerprint": policy_identity["decision_fingerprint"],
            "learned_artifacts_fingerprint": policy_identity["learned_artifacts_fingerprint"],
            "ruler_version": RULER_VERSION,
            "ruler_fingerprint": ruler_id,
            "universe": resolved_symbols,
            "universe_source": "current_watchlist",
            "data_quality_ok": data_quality_ok,
            "data_quality_issues": qc_issues[:100],
            "overlap_status": overlap_status,
            "trials": trials,
            "caveats": caveats,
            "note": metrics.get("note"),
        }
        return run_id, summary

    async def _load_market_bars(
        self, *, target_years: int, force_refresh: bool, asset_types: set[str] | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        market_bars: dict[str, list[dict[str, Any]]] = {}
        selected_asset_types = (
            set(_MARKET_BENCHMARK)
            if asset_types is None
            else {asset_type for asset_type in asset_types if asset_type in _MARKET_BENCHMARK}
        )
        for asset_type, symbol in _MARKET_BENCHMARK.items():
            if asset_type not in selected_asset_types:
                continue
            try:
                await self.bar_store.ensure_history(
                    symbol, asset_type=asset_type, years=target_years, force_refresh=force_refresh
                )
                market_bars[asset_type] = sorted_bars(
                    self.bar_store.load_bars(symbol, asset_type=asset_type)
                )
            except Exception:
                logger.warning("market_benchmark_load_failed", extra={"symbol": symbol}, exc_info=True)
                market_bars[asset_type] = []
        return market_bars

    def _crypto_history_sufficient(self, coverage: list[dict[str, Any]]) -> bool:
        crypto = [c for c in coverage if c.get("asset_type") == "crypto"]
        if not crypto:
            return True
        sufficient = sum(1 for c in crypto if c.get("sufficient"))
        return sufficient >= (len(crypto) / 2.0)


    # --- benchmarks -----------------------------------------------------

    def compute_benchmarks(
        self,
        *,
        predictions: list[dict[str, Any]],
        as_of_dates: list[datetime],
        bars_by_symbol: dict[str, list[dict[str, Any]]],
        asset_by_symbol: dict[str, str],
        market_bars: dict[str, list[dict[str, Any]]],
        holdout_start: datetime,
        top_n: int,
        validation_start: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Compare the pattern strategy to trivial baselines on identical dates + friction.

        Baselines: buy-and-hold (equal-weight universe), market (SPY/BTC), momentum-only
        (top-N by trailing momentum), SMA-cross (price>SMA20>SMA50), and random (seeded,
        averaged over many draws). All are weekly-rebalanced portfolios scored the same
        way as the pattern strategy so edge deltas are apples-to-apples.
        """
        forward_days = int(self.settings.weekly_forward_days)
        tolerance = int(self.settings.weekly_forward_tolerance_days)
        momentum_lookback = int(self.settings.proof_momentum_lookback_days)
        draws = max(1, int(self.settings.proof_benchmark_random_draws))
        # Opportunity matching: baselines may only hold symbols the strategy could
        # have considered at that date (enough visible history to warm up pattern
        # detection). Without this, buy-and-hold gets credit for symbols the
        # strategy was structurally unable to pick, making the edge unfairly hard
        # (or easy) depending on which symbols lack early history.
        eligibility_warmup = max(int(self.settings.weekly_daily_lookback_bars_min) // 4, 60)
        symbols_by_asset: dict[str, list[str]] = {"stock": [], "crypto": []}
        for symbol, asset_type in asset_by_symbol.items():
            symbols_by_asset.setdefault(asset_type, []).append(symbol)

        # Per-period pattern-strategy returns from the actual top picks,
        # keyed by (asset, track, as_of) then averaged to one value per period.
        strat_by_group: dict[tuple[str, str], list[float]] = {}
        strat_period_map: dict[tuple[str, str, Any], list[float]] = {}
        for prediction in predictions:
            if prediction.get("return_after_1w") is None:
                continue
            track = _track_label_from_sample_source(prediction.get("sample_source")) or "research"
            strat_period_map.setdefault((prediction["asset_type"], track, prediction["as_of"]), []).append(
                float(prediction["return_after_1w"])
            )
        for (asset_type, track, _as_of), rets in strat_period_map.items():
            strat_by_group.setdefault((asset_type, track), []).append(sum(rets) / len(rets))

        baseline_by_group: dict[tuple[str, str, str], list[float]] = {}

        def add(asset_type: str, track: str, strategy: str, value: float | None) -> None:
            if value is None:
                return
            baseline_by_group.setdefault((asset_type, track, strategy), []).append(value)

        for as_of in as_of_dates:
            track = _track_label_from_sample_source(
                self._track_for(as_of, holdout_start, validation_start)
            ) or "research"
            for asset_type, symbols in symbols_by_asset.items():
                if not symbols:
                    continue
                forwards: dict[str, float] = {}
                momentum: dict[str, float] = {}
                sma_ok: list[str] = []
                for symbol in symbols:
                    bars = bars_by_symbol.get(symbol) or []
                    fr = _forward_return(bars, as_of=as_of, forward_days=forward_days, tolerance_days=tolerance)
                    if fr is None:
                        continue
                    usable = bars_as_of(bars, as_of)
                    closes = [close_price(b) for b in usable if close_price(b) > 0]
                    if len(closes) < eligibility_warmup:
                        # Not in the strategy's opportunity set at this date.
                        continue
                    forwards[symbol] = fr
                    mom = _momentum_pct(closes, momentum_lookback)
                    if mom is not None:
                        momentum[symbol] = mom
                    sma20 = _sma(closes, 20)
                    sma50 = _sma(closes, 50)
                    if sma20 is not None and sma50 is not None and closes and closes[-1] > sma20 > sma50:
                        sma_ok.append(symbol)
                if not forwards:
                    continue
                add(asset_type, track, "buy_and_hold", sum(forwards.values()) / len(forwards))
                market_ret = _forward_return(
                    market_bars.get(asset_type) or [], as_of=as_of, forward_days=forward_days, tolerance_days=tolerance
                )
                add(asset_type, track, "market", market_ret)
                if momentum:
                    top_mom = sorted(momentum, key=lambda s: momentum[s], reverse=True)[:top_n]
                    add(asset_type, track, "momentum", sum(forwards[s] for s in top_mom) / len(top_mom))
                if sma_ok:
                    ranked = sorted(sma_ok, key=lambda s: momentum.get(s, 0.0), reverse=True)[:top_n]
                    add(asset_type, track, "sma_cross", sum(forwards[s] for s in ranked) / len(ranked))
                pool = list(forwards.keys())
                if pool:
                    rng = random.Random(f"{self.settings.proof_benchmark_random_seed}:{asset_type}:{as_of.isoformat()}")
                    draw_means: list[float] = []
                    take = min(top_n, len(pool))
                    for _ in range(draws):
                        picks = rng.sample(pool, take)
                        draw_means.append(sum(forwards[s] for s in picks) / len(picks))
                    add(asset_type, track, "random", sum(draw_means) / len(draw_means))

        rows: list[dict[str, Any]] = []
        for asset_type in ("stock", "crypto"):
            for track in ("research", "holdout"):
                strat_vals = strat_by_group.get((asset_type, track), [])
                if strat_vals:
                    rows.append(
                        self._benchmark_row(asset_type, track, "pattern", strat_vals)
                    )
                for strategy in ("buy_and_hold", "market", "momentum", "sma_cross", "random"):
                    vals = baseline_by_group.get((asset_type, track, strategy), [])
                    if vals:
                        rows.append(self._benchmark_row(asset_type, track, strategy, vals))
        return rows

    def _benchmark_row(
        self, asset_type: str, track: str, strategy: str, period_values: list[float]
    ) -> dict[str, Any]:
        after_friction = [
            self.scan_repository._apply_friction_to_return(v, asset_type=asset_type, scenario="base")
            for v in period_values
        ]
        after_friction = [v for v in after_friction if v is not None]
        return {
            "asset_type": asset_type,
            "track": track,
            "strategy": strategy,
            "periods": len(period_values),
            "avg_return_pct": _mean(period_values),
            "avg_return_after_friction_pct": _mean(after_friction),
        }

    def _merge_benchmark_edges(
        self, metrics: dict[str, Any], benchmarks: list[dict[str, Any]]
    ) -> None:
        lookup: dict[tuple[str, str, str], float | None] = {}
        for row in benchmarks:
            lookup[(row["asset_type"], row["track"], row["strategy"])] = row.get(
                "avg_return_after_friction_pct"
            )
        for metrics_row in metrics.get("by_asset_track", []):
            asset_type = metrics_row["asset_type"]
            track = metrics_row["track"]
            pattern = lookup.get((asset_type, track, "pattern"))
            for strategy in ("buy_and_hold", "market", "momentum", "sma_cross", "random"):
                baseline = lookup.get((asset_type, track, strategy))
                edge = (
                    round(pattern - baseline, 4)
                    if pattern is not None and baseline is not None
                    else None
                )
                metrics_row[f"edge_after_friction_vs_{strategy}_pct"] = edge

    def _pattern_diagnostic_rows(
        self, predictions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for prediction in predictions:
            track = _track_label_from_sample_source(prediction.get("sample_source"))
            if track is None:
                continue
            pattern_name = str(prediction.get("pattern_name") or "unknown")
            key = (str(prediction["asset_type"]), track, pattern_name)
            groups.setdefault(key, []).append(prediction)

        rows: list[dict[str, Any]] = []
        for (asset_type, track, pattern_name), group_all in sorted(groups.items()):
            resolved = [
                p
                for p in group_all
                if p.get("status") == "resolved" and p.get("return_after_1w") is not None
            ]
            metrics_row, _buckets = self._metrics_for_group(
                resolved,
                asset_type=asset_type,
                track_label=track,
            )
            probabilities = [
                float(p["upside_probability_pct"])
                for p in group_all
                if p.get("upside_probability_pct") is not None
            ]
            confidences = [
                float(p["confidence"]) for p in group_all if p.get("confidence") is not None
            ]
            rows.append(
                {
                    "asset_type": asset_type,
                    "track": track,
                    "pattern_name": pattern_name,
                    "prediction_count": len(group_all),
                    "resolved_count": len(resolved),
                    "upside_hit_rate_pct": metrics_row.get("upside_hit_rate_pct"),
                    "upside_hit_rate_lb95_pct": metrics_row.get("upside_hit_rate_lb95_pct"),
                    "avg_return_pct": metrics_row.get("avg_return_pct"),
                    "avg_return_after_friction_stressed_pct": metrics_row.get(
                        "avg_return_after_friction_stressed_pct"
                    ),
                    "information_coefficient": metrics_row.get("information_coefficient"),
                    "ic_t_stat": metrics_row.get("ic_t_stat"),
                    "confidence_discrimination_pct": metrics_row.get(
                        "confidence_discrimination_pct"
                    ),
                    "max_drawdown_pct": metrics_row.get("max_drawdown_pct"),
                    "avg_upside_probability_pct": _mean(probabilities),
                    "avg_confidence": _mean(confidences),
                }
            )
        return rows

    # --- metrics --------------------------------------------------------

    def compute_metrics(
        self,
        predictions: list[dict[str, Any]],
        *,
        market_bars: dict[str, list[dict[str, Any]]] | None = None,
        rejection_diagnostics: list[dict[str, Any]] | None = None,
        candidate_filter_diagnostics: list[dict[str, Any]] | None = None,
        selection_stage_diagnostics: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        market_bars = market_bars or {}
        resolved = [p for p in predictions if p.get("status") == "resolved" and p.get("return_after_1w") is not None]
        pending = [p for p in predictions if p.get("status") != "resolved" or p.get("return_after_1w") is None]

        by_asset_track: list[dict[str, Any]] = []
        calibration_buckets: list[dict[str, Any]] = []
        reliability_maps: dict[str, list[dict[str, float | int]]] = {}
        for asset_type in ("stock", "crypto"):
            research_pairs = [
                (float(p["upside_probability_pct"]), float(p["return_after_1w"]) > 0)
                for p in resolved
                if p["asset_type"] == asset_type
                and p.get("sample_source") == "historical"
                and p.get("upside_probability_pct") is not None
            ]
            reliability_map = build_reliability_map(research_pairs)
            if reliability_map:
                reliability_maps[asset_type] = reliability_map_to_payload(reliability_map)
            for track_key, track_label in (
                ("historical", "research"),
                ("validation", "validation"),
                ("out_of_sample", "holdout"),
            ):
                group_all = [
                    p
                    for p in predictions
                    if p["asset_type"] == asset_type and p.get("sample_source") == track_key
                ]
                group = [p for p in group_all if p in resolved]
                if not group_all:
                    continue
                metrics_row, buckets = self._metrics_for_group(
                    group,
                    asset_type=asset_type,
                    track_label=track_label,
                    market_bars=market_bars.get(asset_type),
                )
                metrics_row["prediction_count"] = len(group_all)
                metrics_row["pending_count"] = len(group_all) - len(group)
                # Missingness: selected predictions that never resolved (no usable
                # forward bar). A high rate silently biases every other metric, so
                # it is reported alongside them rather than hidden.
                metrics_row["missing_resolution_rate_pct"] = (
                    round((len(group_all) - len(group)) / len(group_all) * 100.0, 4)
                    if group_all
                    else None
                )
                # Calibrate holdout using only the earlier research window (no lookahead).
                if track_label == "holdout" and reliability_map:
                    holdout_pairs = [
                        (float(p["upside_probability_pct"]), float(p["return_after_1w"]) > 0)
                        for p in group
                        if p.get("upside_probability_pct") is not None
                    ]
                    metrics_row["calibrated_calibration_gap_pct"] = calibrated_mean_abs_gap_pct(
                        reliability_map, holdout_pairs
                    )
                else:
                    metrics_row["calibrated_calibration_gap_pct"] = None
                by_asset_track.append(metrics_row)
                calibration_buckets.extend(buckets)

        note = None
        if not resolved:
            note = "No resolved historical walk-forward predictions yet."
        return {
            "resolved_count": len(resolved),
            "pending_count": len(pending),
            "by_asset_track": by_asset_track,
            "calibration_buckets": calibration_buckets,
            "pattern_diagnostics": self._pattern_diagnostic_rows(predictions),
            "rejection_diagnostics": rejection_diagnostics or [],
            "candidate_filter_diagnostics": candidate_filter_diagnostics or [],
            "selection_stage_diagnostics": selection_stage_diagnostics or [],
            "reliability_maps": reliability_maps,
            "note": note,
        }

    def _metrics_for_group(
        self,
        group: list[dict[str, Any]],
        *,
        asset_type: str,
        track_label: str,
        market_bars: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        ordered = sorted(group, key=lambda item: item["as_of"])
        returns = [float(p["return_after_1w"]) for p in ordered]
        after_friction = [
            self.scan_repository._apply_friction_to_return(r, asset_type=asset_type, scenario="base")
            for r in returns
        ]
        after_friction = [v for v in after_friction if v is not None]
        after_friction_stressed = [
            self.scan_repository._apply_friction_to_return(r, asset_type=asset_type, scenario="stressed")
            for r in returns
        ]
        after_friction_stressed = [v for v in after_friction_stressed if v is not None]

        up_count = sum(1 for r in returns if r > 0)
        helped = [p for p in ordered if p.get("exit_window_helped") is not None]
        helped_count = sum(1 for p in helped if p.get("exit_window_helped"))
        protected = [float(p["protected_return_pct"]) for p in ordered if p.get("protected_return_pct") is not None]
        hold = [float(p["hold_return_pct"]) for p in ordered if p.get("hold_return_pct") is not None]

        # Exit-window same-bar conflict rate: of predictions where both an exit
        # target and a stop existed, how often the resolving daily bar touched both
        # (so the conservative "assume stop first" tie-break decided the outcome).
        conflict_eligible = [
            p
            for p in ordered
            if p.get("estimated_exit_price") is not None
            and p.get("invalidation_level") is not None
            and p.get("exit_conflict") is not None
        ]
        conflict_count = sum(1 for p in conflict_eligible if p.get("exit_conflict"))
        exit_conflict_rate_pct = (
            round(conflict_count / len(conflict_eligible) * 100.0, 4) if conflict_eligible else None
        )

        # Statistical solidity: Wilson lower bound on realized up-rate, Spearman IC
        # of the upside-probability signal vs realized return, and cross-regime edge.
        upside_hit_rate_lb95_pct = _wilson_lower_bound_pct(up_count, len(returns)) if returns else None
        edge_significant = (
            upside_hit_rate_lb95_pct is not None and upside_hit_rate_lb95_pct > 50.0
        )
        ic_pairs = [
            (float(p["upside_probability_pct"]), float(p["return_after_1w"]))
            for p in ordered
            if p.get("upside_probability_pct") is not None
        ]
        information_coefficient, ic_t_stat = _spearman_ic(ic_pairs)

        regime_returns: dict[str, list[float]] = {}
        for prediction in ordered:
            label = _benchmark_regime(market_bars, prediction["as_of"])
            regime_returns.setdefault(label, []).append(float(prediction["return_after_1w"]))
        regime_sample_counts = {label: len(vals) for label, vals in regime_returns.items()}
        regime_avg_return_pct = {
            label: round(sum(vals) / len(vals), 4) for label, vals in regime_returns.items() if vals
        }
        min_regime_samples = max(1, int(self.settings.proof_min_regime_samples))
        positive_regimes = [
            label
            for label, vals in regime_returns.items()
            if label in ("bull", "bear", "chop")
            and len(vals) >= min_regime_samples
            and sum(vals) / len(vals) > 0
        ]
        cross_regime_edge_ok = len(positive_regimes) >= 2

        sorted_returns = sorted(returns)
        # Calibration buckets by predicted upside probability.
        bands: dict[str, list[dict[str, Any]]] = {}
        for prediction in ordered:
            band = _calibration_band(prediction.get("upside_probability_pct"))
            bands.setdefault(band, []).append(prediction)
        bucket_rows: list[dict[str, Any]] = []
        gaps: list[float] = []
        for band, rows in sorted(bands.items()):
            predicted_values = [
                float(r["upside_probability_pct"]) for r in rows if r.get("upside_probability_pct") is not None
            ]
            realized_up = sum(1 for r in rows if float(r["return_after_1w"]) > 0)
            realized_rate = round(realized_up / len(rows) * 100.0, 4) if rows else None
            avg_predicted = _mean(predicted_values)
            gap = (
                round(abs(avg_predicted - realized_rate), 4)
                if avg_predicted is not None and realized_rate is not None
                else None
            )
            if gap is not None:
                gaps.append(gap)
            bucket_rows.append(
                {
                    "probability_band": band,
                    "asset_type": asset_type,
                    "track": track_label,
                    "evaluated_count": len(rows),
                    "avg_predicted_pct": avg_predicted,
                    "realized_up_rate_pct": realized_rate,
                    "reliability_gap_pct": gap,
                }
            )

        # Brier score of the stated probability against the realized direction:
        # mean((p/100 - outcome)^2) over resolved predictions that carried a
        # probability. Lower is better; 0.25 is the score of a coin-flip forecast.
        brier_terms = [
            (float(p["upside_probability_pct"]) / 100.0 - (1.0 if float(p["return_after_1w"]) > 0 else 0.0)) ** 2
            for p in ordered
            if p.get("upside_probability_pct") is not None
        ]
        brier_score = round(sum(brier_terms) / len(brier_terms), 4) if brier_terms else None

        # Derived view: hit rate recomputed after friction is deducted from the
        # canonical raw returns (raw outcomes stay canonical; this reinterprets).
        up_after_friction = sum(1 for r in after_friction if r > 0)
        metrics_row = {
            "asset_type": asset_type,
            "track": track_label,
            "resolved_count": len(ordered),
            "upside_hit_rate_pct": round(up_count / len(returns) * 100.0, 4) if returns else None,
            "upside_hit_rate_after_friction_pct": (
                round(up_after_friction / len(after_friction) * 100.0, 4) if after_friction else None
            ),
            "brier_score": brier_score,
            "avg_return_pct": _mean(returns),
            "avg_return_after_friction_pct": _mean(after_friction),
            "avg_return_after_friction_stressed_pct": _mean(after_friction_stressed),
            "calibration_mean_abs_gap_pct": _mean(gaps),
            "confidence_discrimination_pct": _confidence_discrimination_pct(ordered),
            "exit_window_helped_rate_pct": (
                round(helped_count / len(helped) * 100.0, 4) if helped else None
            ),
            "exit_conflict_rate_pct": exit_conflict_rate_pct,
            "upside_hit_rate_lb95_pct": upside_hit_rate_lb95_pct,
            "edge_significant": edge_significant,
            "information_coefficient": information_coefficient,
            "ic_t_stat": ic_t_stat,
            "regime_sample_counts": regime_sample_counts,
            "regime_avg_return_pct": regime_avg_return_pct,
            "cross_regime_edge_ok": cross_regime_edge_ok,
            "avg_protected_return_pct": _mean(protected),
            "avg_hold_return_pct": _mean(hold),
            "worst_return_pct": round(min(returns), 4) if returns else None,
            "p05_return_pct": _percentile(sorted_returns, 0.05),
            "worst_decile_mean_pct": _worst_decile_mean(returns),
            "max_drawdown_pct": _max_drawdown_pct(self._period_returns(ordered)),
        }
        return metrics_row, bucket_rows

    def _period_returns(self, ordered: list[dict[str, Any]]) -> list[float]:
        """Collapse overlapping same-date picks into one weekly-rebalanced portfolio
        return per period, ordered in time, so drawdown reflects a realistic
        equal-weight portfolio rather than serially compounding concurrent bets."""
        by_period: dict[Any, list[float]] = {}
        for prediction in ordered:
            by_period.setdefault(prediction["as_of"], []).append(float(prediction["return_after_1w"]))
        return [sum(v) / len(v) for _as_of, v in sorted(by_period.items(), key=lambda kv: kv[0])]

    # --- pilot-ready verdict (report-only) ------------------------------

    def compute_verdict(
        self, metrics: dict[str, Any], *, crypto_history_ok: bool = True
    ) -> dict[str, Any]:
        rows = {(row["asset_type"], row["track"]): row for row in metrics.get("by_asset_track", [])}
        checks: list[dict[str, Any]] = []
        by_asset: list[dict[str, Any]] = []

        overall_ready = True
        has_any_rows = bool(metrics.get("by_asset_track"))
        for asset_type in ("stock", "crypto"):
            research = rows.get((asset_type, "research"))
            holdout = rows.get((asset_type, "holdout"))
            asset_checks, asset_ready = self._asset_verdict_checks(
                asset_type=asset_type,
                research=research,
                holdout=holdout,
                history_ok=(crypto_history_ok if asset_type == "crypto" else True),
            )
            # Stock and crypto are judged independently and never merged.
            asset_has_rows = research is not None or holdout is not None
            asset_ready = asset_ready and asset_has_rows
            checks.extend(asset_checks)
            asset_summary = (
                f"Historical walk-forward evidence meets the tiny-pilot review bar for {asset_type}. "
                "Real-money trust remains blocked pending live-forward confirmation."
                if asset_ready
                else f"Historical walk-forward evidence does not yet meet the tiny-pilot review bar for {asset_type}."
            )
            by_asset.append(
                {
                    "asset_type": asset_type,
                    "ready": asset_ready,
                    "real_money_trust_blocked": True,
                    "summary": asset_summary,
                    "checks": asset_checks,
                }
            )
            overall_ready = overall_ready and asset_ready

        if not has_any_rows:
            overall_ready = False
            checks.append(
                GateCheck(
                    name="samples_available",
                    passed=False,
                    detail="No resolved historical walk-forward predictions available.",
                ).model_dump()
            )

        summary = (
            "Historical walk-forward evidence meets the tiny-pilot review bar for both asset classes. "
            "Real-money trust remains blocked pending live-forward and out-of-sample confirmation."
            if overall_ready
            else "Historical walk-forward evidence does not yet meet the tiny-pilot review bar."
        )
        return {
            "ready": overall_ready,
            "real_money_trust_blocked": True,
            "summary": summary,
            "checks": checks,
            "by_asset": by_asset,
        }

    def _asset_verdict_checks(
        self,
        *,
        asset_type: str,
        research: dict[str, Any] | None,
        holdout: dict[str, Any] | None,
        history_ok: bool = True,
    ) -> tuple[list[dict[str, Any]], bool]:
        settings = self.settings
        checks: list[dict[str, Any]] = []
        ready = True

        def add(name: str, passed: bool, detail: str) -> None:
            nonlocal ready
            checks.append(GateCheck(name=name, passed=passed, detail=detail).model_dump())
            ready = ready and passed

        if not history_ok:
            add(
                f"{asset_type}_history_sufficient",
                False,
                "Insufficient historical depth for this asset class; trust reduced, excluded from pass.",
            )

        total_predictions = (research or {}).get("prediction_count", 0) + (holdout or {}).get(
            "prediction_count", 0
        )
        add(
            f"{asset_type}_min_predictions",
            total_predictions >= settings.proof_pilot_min_predictions_per_asset,
            f"{total_predictions} predictions (min {settings.proof_pilot_min_predictions_per_asset}).",
        )

        if holdout is None:
            add(
                f"{asset_type}_holdout_available",
                False,
                "No held-out validation predictions for this asset class yet.",
            )
            return checks, ready

        hit = holdout.get("upside_hit_rate_pct")
        add(
            f"{asset_type}_holdout_upside_hit_rate",
            hit is not None and hit >= settings.proof_pilot_min_upside_hit_rate_pct,
            f"Holdout upside hit rate {hit} (min {settings.proof_pilot_min_upside_hit_rate_pct}).",
        )

        gap = holdout.get("calibration_mean_abs_gap_pct")
        add(
            f"{asset_type}_holdout_calibration_gap",
            gap is not None and gap <= settings.proof_pilot_max_calibration_gap_pct,
            f"Holdout calibration gap {gap} (max {settings.proof_pilot_max_calibration_gap_pct}).",
        )

        discrimination = holdout.get("confidence_discrimination_pct")
        add(
            f"{asset_type}_holdout_confidence_discrimination",
            discrimination is not None
            and discrimination >= settings.proof_pilot_min_confidence_discrimination_pct,
            f"Holdout confidence discrimination {discrimination} "
            f"(min {settings.proof_pilot_min_confidence_discrimination_pct}).",
        )

        after_friction = holdout.get("avg_return_after_friction_stressed_pct")
        add(
            f"{asset_type}_holdout_after_friction_return",
            after_friction is not None and after_friction >= settings.proof_pilot_min_after_friction_return_pct,
            f"Holdout stressed after-friction return {after_friction} "
            f"(min {settings.proof_pilot_min_after_friction_return_pct}).",
        )

        drawdown = holdout.get("max_drawdown_pct")
        add(
            f"{asset_type}_holdout_max_drawdown",
            drawdown is not None and drawdown <= settings.proof_pilot_max_drawdown_pct,
            f"Holdout max drawdown {drawdown} (max {settings.proof_pilot_max_drawdown_pct}).",
        )

        helped = holdout.get("exit_window_helped_rate_pct")
        add(
            f"{asset_type}_holdout_exit_window_helped",
            helped is not None and helped >= settings.proof_pilot_min_exit_window_helped_rate_pct,
            f"Holdout exit-window helped rate {helped} "
            f"(min {settings.proof_pilot_min_exit_window_helped_rate_pct}).",
        )

        edge = holdout.get("edge_after_friction_vs_buy_and_hold_pct")
        add(
            f"{asset_type}_holdout_edge_vs_buy_hold",
            edge is not None and edge >= settings.proof_pilot_min_edge_vs_buy_hold_pct,
            f"Holdout after-friction edge vs buy-and-hold {edge} "
            f"(min {settings.proof_pilot_min_edge_vs_buy_hold_pct}).",
        )

        # Statistical-solidity gates: the realized edge must be significant (not a
        # thin-sample fluke), the signal must carry real information, and the edge
        # must hold across more than one market regime.
        if settings.proof_pilot_require_edge_significant:
            lb95 = holdout.get("upside_hit_rate_lb95_pct")
            add(
                f"{asset_type}_holdout_edge_significant",
                bool(holdout.get("edge_significant")),
                f"Holdout upside-rate 95% lower bound {lb95} must exceed 50 (breakeven).",
            )

        ic = holdout.get("information_coefficient")
        ic_t = holdout.get("ic_t_stat")
        add(
            f"{asset_type}_holdout_information_coefficient",
            ic is not None
            and ic_t is not None
            and ic >= settings.proof_pilot_min_information_coefficient
            and ic_t >= settings.proof_pilot_min_ic_t_stat,
            f"Holdout information coefficient {ic} (min {settings.proof_pilot_min_information_coefficient}), "
            f"t-stat {ic_t} (min {settings.proof_pilot_min_ic_t_stat}).",
        )

        if settings.proof_pilot_require_cross_regime_edge:
            add(
                f"{asset_type}_holdout_cross_regime_edge",
                bool(holdout.get("cross_regime_edge_ok")),
                f"Holdout edge must be positive across >1 regime; "
                f"regime samples {holdout.get('regime_sample_counts')}, "
                f"avg returns {holdout.get('regime_avg_return_pct')}.",
            )
        return checks, ready
