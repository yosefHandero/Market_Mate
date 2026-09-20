from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings, get_settings
from app.brain.weekly_backtest import PatternBacktestStats
from app.schemas import GateCheck, SampleSource


CALIBRATION_SOURCES = frozenset({"historical", "backfilled_replay"})
# "out_of_sample" is the legacy stored spelling of the live holdout track;
# "live_holdout" is the current one. Both are trust-only, never calibration.
TRUST_SOURCES = frozenset({"live_paper_forward", "out_of_sample", "live_holdout"})


@dataclass(frozen=True)
class WeeklyEvidenceVerdict:
    pattern_has_enough_historical_samples: bool
    pattern_has_enough_backfilled_replay_samples: bool
    pattern_has_enough_live_paper_forward_samples: bool
    pattern_has_enough_out_of_sample_samples: bool
    real_money_trust_blocked: bool
    evidence_basis: str
    checks: tuple[GateCheck, ...]
    summary: str


def _stats_for_source(
    stats_by_source: dict[SampleSource, PatternBacktestStats],
    source: SampleSource,
) -> PatternBacktestStats:
    return stats_by_source.get(
        source,
        PatternBacktestStats(pattern_name="none", sample_size=0, hit_rate_pct=None, avg_forward_return_pct=None),
    )


def _merge_holdout_stats(
    stats_by_source: dict[SampleSource, PatternBacktestStats],
) -> PatternBacktestStats:
    """Combine legacy ``out_of_sample`` and current ``live_holdout`` trust rows."""
    parts = [
        _stats_for_source(stats_by_source, "out_of_sample"),
        _stats_for_source(stats_by_source, "live_holdout"),  # type: ignore[arg-type]
    ]
    total = sum(p.sample_size for p in parts)
    if total <= 0:
        return PatternBacktestStats(
            pattern_name="none", sample_size=0, hit_rate_pct=None, avg_forward_return_pct=None
        )
    weighted_hits = 0.0
    weighted_ret = 0.0
    ret_n = 0
    name = "none"
    for part in parts:
        if part.sample_size <= 0:
            continue
        name = part.pattern_name or name
        if part.hit_rate_pct is not None:
            weighted_hits += (part.hit_rate_pct / 100.0) * part.sample_size
        if part.avg_forward_return_pct is not None:
            weighted_ret += part.avg_forward_return_pct * part.sample_size
            ret_n += part.sample_size
    return PatternBacktestStats(
        pattern_name=name,
        sample_size=total,
        hit_rate_pct=round(weighted_hits / total * 100.0, 2) if total else None,
        avg_forward_return_pct=round(weighted_ret / ret_n, 4) if ret_n else None,
    )


def _gate_int(settings: Any, brain_name: str, settings_name: str, default: int) -> int:
    if hasattr(settings, brain_name):
        return int(getattr(settings, brain_name))
    if hasattr(settings, settings_name):
        return int(getattr(settings, settings_name))
    return default


def _gate_float(settings: Any, brain_name: str, settings_name: str, default: float) -> float:
    if hasattr(settings, brain_name):
        return float(getattr(settings, brain_name))
    if hasattr(settings, settings_name):
        return float(getattr(settings, settings_name))
    return default


def evaluate_weekly_pattern_evidence(
    *,
    stats_by_source: dict[SampleSource, PatternBacktestStats],
    settings: Settings | None = None,
    asset_type: str | None = None,
    signal: str | None = None,
) -> WeeklyEvidenceVerdict:
    settings = settings or get_settings()
    min_historical = _gate_int(
        settings, "pattern_gate_min_historical_samples", "weekly_pattern_gate_min_historical_samples", 30
    )
    min_backfilled = _gate_int(
        settings, "pattern_gate_min_backfilled_samples", "weekly_pattern_gate_min_backfilled_samples", 20
    )
    min_live_forward = _gate_int(
        settings, "pattern_gate_min_live_forward_samples", "weekly_pattern_gate_min_live_forward_samples", 20
    )
    min_oos = _gate_int(
        settings, "pattern_gate_min_out_of_sample_samples", "weekly_pattern_gate_min_out_of_sample_samples", 10
    )
    min_win = _gate_float(settings, "pattern_gate_min_win_rate", "weekly_pattern_gate_min_win_rate", 52.0)
    min_avg = _gate_float(settings, "pattern_gate_min_avg_return", "weekly_pattern_gate_min_avg_return", 0.10)
    historical = _stats_for_source(stats_by_source, "historical")
    backfilled = _stats_for_source(stats_by_source, "backfilled_replay")
    live_forward = _stats_for_source(stats_by_source, "live_paper_forward")
    out_of_sample = _merge_holdout_stats(stats_by_source)

    # Crypto BUY evidence is poorer/underpowered, so it must clear a higher live-forward
    # sample floor before real-money trust can be considered. Stricter only.
    crypto_buy_floor = _gate_int(
        settings, "pattern_gate_min_live_forward_samples", "trade_gate_crypto_buy_min_evaluated_count", 30
    )
    if (asset_type or "").strip().lower() == "crypto" and (signal or "").strip().upper() == "BUY":
        min_live_forward = max(min_live_forward, crypto_buy_floor)

    checks = [
        GateCheck(
            name="pattern_has_enough_historical_samples",
            passed=historical.sample_size >= min_historical,
            detail=f"historical samples {historical.sample_size}; need {min_historical}",
        ),
        GateCheck(
            name="pattern_has_enough_backfilled_replay_samples",
            passed=backfilled.sample_size >= min_backfilled,
            detail=f"backfilled_replay samples {backfilled.sample_size}; need {min_backfilled}",
        ),
        GateCheck(
            name="pattern_has_enough_live_paper_forward_samples",
            passed=live_forward.sample_size >= min_live_forward,
            detail=f"live_paper_forward samples {live_forward.sample_size}; need {min_live_forward}",
        ),
        GateCheck(
            name="pattern_has_enough_out_of_sample_samples",
            passed=out_of_sample.sample_size >= min_oos,
            detail=f"out_of_sample samples {out_of_sample.sample_size}; need {min_oos}",
        ),
    ]

    live_or_oos_ready = (
        live_forward.sample_size >= min_live_forward and out_of_sample.sample_size >= min_oos
    )
    live_performance_ok = (
        (live_forward.hit_rate_pct or 0.0) >= min_win
        and (live_forward.avg_forward_return_pct or 0.0) >= min_avg
        and (out_of_sample.hit_rate_pct or 0.0) >= min_win
        and (out_of_sample.avg_forward_return_pct or 0.0) >= min_avg
    )
    real_money_trust_blocked = not (live_or_oos_ready and live_performance_ok)
    checks.append(
        GateCheck(
            name="real_money_trust_blocked",
            passed=not real_money_trust_blocked,
            detail=(
                "Real-money trust remains blocked until live paper forward and out-of-sample "
                "samples meet count and performance thresholds."
                if real_money_trust_blocked
                else "Live forward and out-of-sample evidence is sufficient for real-money trust review."
            ),
        )
    )

    calibration_ready = checks[0].passed or checks[1].passed
    if live_forward.sample_size > 0 or out_of_sample.sample_size > 0:
        evidence_basis = "live_forward_proven" if not real_money_trust_blocked else "mixed"
    elif calibration_ready:
        evidence_basis = "historical_only"
    else:
        evidence_basis = "insufficient"

    if not real_money_trust_blocked:
        summary = "Weekly pattern evidence is live-forward proven for real-money trust review."
    elif calibration_ready:
        summary = (
            "Weekly pattern calibration is available from historical/backfilled samples; "
            "real-money trust remains blocked pending live forward proof."
        )
    else:
        summary = "Weekly pattern evidence is still maturing; historical calibration samples are insufficient."

    return WeeklyEvidenceVerdict(
        pattern_has_enough_historical_samples=checks[0].passed,
        pattern_has_enough_backfilled_replay_samples=checks[1].passed,
        pattern_has_enough_live_paper_forward_samples=checks[2].passed,
        pattern_has_enough_out_of_sample_samples=checks[3].passed,
        real_money_trust_blocked=real_money_trust_blocked,
        evidence_basis=evidence_basis,
        checks=tuple(checks),
        summary=summary,
    )
