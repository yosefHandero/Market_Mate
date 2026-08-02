from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.core.weekly_backtest import PatternBacktestStats
from app.schemas import GateCheck, SampleSource


CALIBRATION_SOURCES = frozenset({"historical", "backfilled_replay"})
TRUST_SOURCES = frozenset({"live_paper_forward", "out_of_sample"})


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


def evaluate_weekly_pattern_evidence(
    *,
    stats_by_source: dict[SampleSource, PatternBacktestStats],
    settings: Settings | None = None,
    asset_type: str | None = None,
    signal: str | None = None,
) -> WeeklyEvidenceVerdict:
    settings = settings or get_settings()
    historical = _stats_for_source(stats_by_source, "historical")
    backfilled = _stats_for_source(stats_by_source, "backfilled_replay")
    live_forward = _stats_for_source(stats_by_source, "live_paper_forward")
    out_of_sample = _stats_for_source(stats_by_source, "out_of_sample")

    # Crypto BUY evidence is poorer/underpowered, so it must clear a higher live-forward
    # sample floor before real-money trust can be considered (agent.md 5: judge BUY/SELL
    # and stock/crypto separately). Stricter only; never loosens the base requirement.
    min_live_forward = settings.weekly_pattern_gate_min_live_forward_samples
    if (asset_type or "").strip().lower() == "crypto" and (signal or "").strip().upper() == "BUY":
        min_live_forward = max(min_live_forward, settings.trade_gate_crypto_buy_min_evaluated_count)

    checks = [
        GateCheck(
            name="pattern_has_enough_historical_samples",
            passed=historical.sample_size >= settings.weekly_pattern_gate_min_historical_samples,
            detail=(
                f"historical samples {historical.sample_size}; "
                f"need {settings.weekly_pattern_gate_min_historical_samples}"
            ),
        ),
        GateCheck(
            name="pattern_has_enough_backfilled_replay_samples",
            passed=backfilled.sample_size >= settings.weekly_pattern_gate_min_backfilled_samples,
            detail=(
                f"backfilled_replay samples {backfilled.sample_size}; "
                f"need {settings.weekly_pattern_gate_min_backfilled_samples}"
            ),
        ),
        GateCheck(
            name="pattern_has_enough_live_paper_forward_samples",
            passed=live_forward.sample_size >= min_live_forward,
            detail=(
                f"live_paper_forward samples {live_forward.sample_size}; "
                f"need {min_live_forward}"
            ),
        ),
        GateCheck(
            name="pattern_has_enough_out_of_sample_samples",
            passed=out_of_sample.sample_size >= settings.weekly_pattern_gate_min_out_of_sample_samples,
            detail=(
                f"out_of_sample samples {out_of_sample.sample_size}; "
                f"need {settings.weekly_pattern_gate_min_out_of_sample_samples}"
            ),
        ),
    ]

    live_or_oos_ready = (
        live_forward.sample_size >= min_live_forward
        and out_of_sample.sample_size >= settings.weekly_pattern_gate_min_out_of_sample_samples
    )
    live_performance_ok = (
        (live_forward.hit_rate_pct or 0.0) >= settings.weekly_pattern_gate_min_win_rate
        and (live_forward.avg_forward_return_pct or 0.0) >= settings.weekly_pattern_gate_min_avg_return
        and (out_of_sample.hit_rate_pct or 0.0) >= settings.weekly_pattern_gate_min_win_rate
        and (out_of_sample.avg_forward_return_pct or 0.0) >= settings.weekly_pattern_gate_min_avg_return
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
