"""Paired champion-vs-challenger comparison over identical scan opportunities.

This is the promotion ruler. When two policies decided on the same scans, the
honest comparison is per-scan paired differences, not two separate point
estimates: pairing removes the shared market noise that dominates unpaired
comparisons, and the confidence interval on the mean difference accounts for
the uncertainty that a point estimate hides.

Semantics
    Each pair is one scan opportunity both policies saw. A policy that
    abstained on an opportunity contributes a return of 0 for it (abstention
    earns nothing and loses nothing). Pairs where BOTH policies abstained are
    identical behavior and carry no information about relative skill, so they
    are excluded from inference; their count is still reported.

Promotion rule (no shortcuts)
    A challenger is superior only when there are at least ``min_pairs``
    informative pairs AND the 95% confidence interval over resolution-week
    clusters lies entirely above zero. Paper-only deployment reduces deployment
    risk, not evidentiary uncertainty, so no relaxed calendar- or
    point-estimate-based path exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime


# Two-sided 95% Student-t critical values by degrees of freedom (1..30), then a
# normal-approximation tail. Self-contained so the brain stays dependency-free.
_T_CRIT_95 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)


def t_critical_95(df: int) -> float:
    """Two-sided 95% Student-t critical value for ``df`` degrees of freedom."""
    if df <= 0:
        return float("inf")
    if df <= len(_T_CRIT_95):
        return _T_CRIT_95[df - 1]
    if df <= 60:
        return 2.021  # conservative bridge between t(30) and the normal tail
    return 1.96


def _iso_week_id(value: date) -> str:
    iso = value.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def _resolution_week_id(value: str | date | datetime | None) -> tuple[str, bool]:
    if value is None:
        return "unknown", True
    if isinstance(value, datetime):
        return _iso_week_id(value.date()), False
    if isinstance(value, date):
        return _iso_week_id(value), False
    raw = str(value).strip()
    if not raw:
        return "unknown", True
    try:
        return _iso_week_id(date.fromisoformat(raw[:10])), False
    except ValueError:
        return raw, False


@dataclass(frozen=True)
class PairedOutcome:
    """One scan opportunity both policies saw.

    ``None`` return means the policy abstained on this opportunity."""

    key: str
    champion_return_pct: float | None
    challenger_return_pct: float | None
    resolution_week: str | date | datetime | None = None

    def informative(self) -> bool:
        return self.champion_return_pct is not None or self.challenger_return_pct is not None


@dataclass(frozen=True)
class PairedComparisonResult:
    n_pairs_total: int
    n_pairs_informative: int
    n_both_abstained: int
    n_resolution_clusters: int
    n_missing_resolution_week: int
    resolution_cluster_metadata_complete: bool
    n_champion_active: int
    n_challenger_active: int
    n_disagreements: int
    mean_diff_pct: float | None
    cluster_mean_diff_pct: float | None
    diff_stdev_pct: float | None
    diff_ci95_low_pct: float | None
    diff_ci95_high_pct: float | None
    t_stat: float | None
    challenger_win_fraction_pct: float | None
    min_pairs_required: int
    sufficient_pairs: bool
    sufficient_resolution_clusters: bool
    challenger_superior: bool
    challenger_inferior: bool
    summary: str


def compare_paired(
    pairs: list[PairedOutcome],
    *,
    min_pairs: int = 40,
) -> PairedComparisonResult:
    """Paired comparison of challenger vs champion on identical opportunities.

    Differences are challenger minus champion, abstention counted as 0.0.
    Both-abstain pairs are excluded from inference (identical behavior).
    ``challenger_superior`` requires enough informative pairs and a clustered
    95% CI over resolution-week means entirely above zero;
    ``challenger_inferior`` is the symmetric statement below zero.
    """
    informative = [p for p in pairs if p.informative()]
    n_total = len(pairs)
    n_informative = len(informative)
    n_both_abstained = n_total - n_informative
    n_champion_active = sum(1 for p in informative if p.champion_return_pct is not None)
    n_challenger_active = sum(1 for p in informative if p.challenger_return_pct is not None)
    n_disagreements = sum(
        1
        for p in informative
        if (p.champion_return_pct is None) != (p.challenger_return_pct is None)
    )

    diffs = [
        (p.challenger_return_pct or 0.0) - (p.champion_return_pct or 0.0)
        for p in informative
    ]
    required_pairs = max(int(min_pairs), 2)
    sufficient = n_informative >= required_pairs
    clustered_diffs: dict[str, list[float]] = {}
    n_missing_resolution_week = 0
    for pair, diff in zip(informative, diffs):
        cluster_id, missing = _resolution_week_id(pair.resolution_week)
        if missing:
            n_missing_resolution_week += 1
            continue
        clustered_diffs.setdefault(cluster_id, []).append(diff)
    cluster_means = [
        sum(cluster_diffs) / len(cluster_diffs)
        for _, cluster_diffs in sorted(clustered_diffs.items())
    ]
    n_resolution_clusters = len(cluster_means)
    metadata_complete = n_missing_resolution_week == 0
    sufficient_resolution_clusters = n_resolution_clusters >= 2

    mean_diff: float | None = None
    cluster_mean_diff: float | None = None
    stdev: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    t_stat: float | None = None
    win_fraction: float | None = None

    if diffs:
        mean_diff = sum(diffs) / len(diffs)
        non_tied = [d for d in diffs if abs(d) > 1e-12]
        if non_tied:
            win_fraction = round(
                sum(1 for d in non_tied if d > 0) / len(non_tied) * 100.0, 2
            )
        if metadata_complete and sufficient_resolution_clusters:
            cluster_mean_diff = sum(cluster_means) / len(cluster_means)
            variance = sum((d - cluster_mean_diff) ** 2 for d in cluster_means) / (
                len(cluster_means) - 1
            )
            stdev = math.sqrt(variance)
            se = stdev / math.sqrt(len(cluster_means))
            crit = t_critical_95(len(cluster_means) - 1)
            if se > 0:
                ci_low = cluster_mean_diff - crit * se
                ci_high = cluster_mean_diff + crit * se
                t_stat = cluster_mean_diff / se
            else:
                # All resolution-week means identical: the interval collapses.
                ci_low = ci_high = cluster_mean_diff
                t_stat = None

    challenger_superior = bool(
        sufficient and metadata_complete and ci_low is not None and ci_low > 0.0
    )
    challenger_inferior = bool(
        sufficient and metadata_complete and ci_high is not None and ci_high < 0.0
    )

    if n_informative == 0:
        summary = "No informative pairs: the policies never disagreed with a position taken."
    elif not sufficient:
        summary = (
            f"Only {n_informative} informative pairs; need {required_pairs} before the "
            "paired comparison can support any promotion judgment."
        )
    elif not metadata_complete:
        summary = (
            f"{n_missing_resolution_week} informative pair(s) lacked a resolution week; "
            "clustered paired inference cannot support any promotion judgment."
        )
    elif not sufficient_resolution_clusters:
        summary = (
            f"Only {n_resolution_clusters} informative resolution-week cluster; need at "
            "least 2 before clustered paired inference can support any promotion judgment."
        )
    elif challenger_superior:
        summary = (
            f"Challenger is superior: mean per-pair edge {mean_diff:+.4f}pp; "
            f"resolution-week clustered mean {cluster_mean_diff:+.4f}pp with 95% CI "
            f"[{ci_low:+.4f}, {ci_high:+.4f}] over {n_informative} pairs across "
            f"{n_resolution_clusters} resolution weeks."
        )
    elif challenger_inferior:
        summary = (
            f"Challenger is inferior: mean per-pair edge {mean_diff:+.4f}pp; "
            f"resolution-week clustered mean {cluster_mean_diff:+.4f}pp with 95% CI "
            f"[{ci_low:+.4f}, {ci_high:+.4f}] over {n_informative} pairs across "
            f"{n_resolution_clusters} resolution weeks."
        )
    else:
        summary = (
            f"Inconclusive: mean per-pair edge {mean_diff:+.4f}pp; "
            f"resolution-week clustered mean {cluster_mean_diff:+.4f}pp with 95% CI "
            f"[{ci_low:+.4f}, {ci_high:+.4f}] over {n_informative} pairs across "
            f"{n_resolution_clusters} resolution weeks straddles zero."
        )
    return PairedComparisonResult(
        n_pairs_total=n_total,
        n_pairs_informative=n_informative,
        n_both_abstained=n_both_abstained,
        n_resolution_clusters=n_resolution_clusters,
        n_missing_resolution_week=n_missing_resolution_week,
        resolution_cluster_metadata_complete=metadata_complete,
        n_champion_active=n_champion_active,
        n_challenger_active=n_challenger_active,
        n_disagreements=n_disagreements,
        mean_diff_pct=round(mean_diff, 4) if mean_diff is not None else None,
        cluster_mean_diff_pct=(
            round(cluster_mean_diff, 4) if cluster_mean_diff is not None else None
        ),
        diff_stdev_pct=round(stdev, 4) if stdev is not None else None,
        diff_ci95_low_pct=round(ci_low, 4) if ci_low is not None else None,
        diff_ci95_high_pct=round(ci_high, 4) if ci_high is not None else None,
        t_stat=round(t_stat, 4) if t_stat is not None else None,
        challenger_win_fraction_pct=win_fraction,
        min_pairs_required=int(min_pairs),
        sufficient_pairs=sufficient,
        sufficient_resolution_clusters=sufficient_resolution_clusters,
        challenger_superior=challenger_superior,
        challenger_inferior=challenger_inferior,
        summary=summary,
    )
