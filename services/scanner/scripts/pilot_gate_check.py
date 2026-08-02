#!/usr/bin/env python3
"""Pilot-gate check: evaluate the real-money graduation criteria per asset class.

Read-only. This script does NOT change any threshold, place any order, or write to
the database. It answers one question: for the frozen evidence campaign, does the
untouched live-forward sample clear every graduation gate in docs/completion-report.md
for stocks and for crypto, evaluated separately?

It intentionally reports ``INSUFFICIENT`` (which never passes) whenever the sample is
too small or a required reference is missing, so running it today - with zero campaign
predictions - correctly returns "not ready" rather than a false green.

What it evaluates (per asset class, from the active/target campaign only):
  * Sample floors: >=100 resolved selected overall, >=60 per asset, >=30 per pattern
  * >=2 market regimes with >=20 samples each and non-negative after-friction mean each
  * Median after-friction return > 0 with a bootstrap 90% CI that excludes 0
  * Stressed-friction mean > 0
  * After-friction edge vs the benchmark (SPY for stocks, BTC for crypto) and vs a
    simple SMA(50) momentum baseline on that benchmark
  * Wilson 95% lower-bound hit rate > 50%
  * Calibration gap <= 10 points in the probability bins actually used
  * Both campaign halves after-friction positive
  * Live hit rate inside the walk-forward holdout Wilson interval (same fingerprint)
  * Ops integrity (campaign-wide): >=95% expected windows executed, <2% unresolved
    past expiry, single frozen fingerprint, immutability trigger present + hashes set
Advisory (reported, not a hard gate): per-symbol concentration; tail loss / drawdown.

Usage:
  python scripts/pilot_gate_check.py [--db PATH] [--campaign CAMPAIGN_ID] [--json]

Exit code is 0 only if at least one asset class is ELIGIBLE (all required gates PASS)
and campaign-wide ops integrity passes; otherwise 1. Eligibility here is a
statistical precondition for a *separately reviewed* manual pilot, never an
instruction to trade. The app stays paper-only; any real order is placed manually.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median

# --- Graduation thresholds (mirror docs/completion-report.md) ----------------
MIN_TOTAL_SELECTED_RESOLVED = 100
MIN_PER_ASSET = 60
MIN_PER_PATTERN = 30
MIN_REGIMES = 2
MIN_SAMPLES_PER_REGIME = 20
MIN_CALIBRATION_BAND_SAMPLES = 10
MAX_CALIBRATION_GAP_PCT = 10.0
MIN_WILSON_HIT_RATE_LB_PCT = 50.0
WINDOW_EXECUTION_MIN_PCT = 95.0
UNRESOLVED_EXPIRY_MAX_PCT = 2.0
FRICTION_STRESS_MULT = 1.5
FORWARD_DAYS_DEFAULT = 7
MOMENTUM_SMA_DAYS = 50
REGIME_LOOKBACK_BARS = 120
REGIME_SMA_BARS = 100
REGIME_SLOPE_BARS = 60
# Advisory-only concentration flags (personal risk decision, not a hard S gate).
CONCENTRATION_TOP1_WARN_PCT = 35.0
CONCENTRATION_TOP3_WARN_PCT = 60.0

BENCHMARK_SYMBOL = {"stock": "SPY", "crypto": "BTC/USD"}

PASS = "PASS"
FAIL = "FAIL"
INSUFFICIENT = "INSUFFICIENT"
REVIEW = "REVIEW"  # advisory: surfaced for the human, not a blocking gate

_REQUIRED_STATUSES = {PASS}


def default_db_path() -> Path:
    return Path(__file__).resolve().parent.parent / "market_mate.db"


# --- statistics helpers ------------------------------------------------------

def wilson_bounds(successes: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """Wilson score interval (percent). Returns (lower, upper)."""
    if n <= 0:
        return None, None
    phat = successes / n
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    lower = (centre - margin) / denom
    upper = (centre + margin) / denom
    return round(lower * 100, 4), round(upper * 100, 4)


def bootstrap_median_ci(
    values: list[float], *, iterations: int = 2000, alpha: float = 0.10, seed: int = 42
) -> tuple[float | None, float | None]:
    """Percentile bootstrap CI for the median (default 90% => alpha 0.10)."""
    if len(values) < 2:
        return None, None
    rng = random.Random(seed)
    n = len(values)
    medians: list[float] = []
    for _ in range(iterations):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        medians.append(median(sample))
    medians.sort()
    lo_idx = max(int((alpha / 2) * len(medians)), 0)
    hi_idx = min(int((1 - alpha / 2) * len(medians)), len(medians) - 1)
    return round(medians[lo_idx], 4), round(medians[hi_idx], 4)


def max_drawdown_pct(returns: list[float]) -> float | None:
    if not returns:
        return None
    peak = 0.0
    cumulative = 0.0
    worst = 0.0
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return round(worst, 4)


def worst_decile_mean(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    tail_n = max(1, len(ordered) // 10)
    return round(mean(ordered[:tail_n]), 4)


# --- data model --------------------------------------------------------------

@dataclass
class Snapshot:
    ticker: str
    asset_type: str
    generated_at: datetime
    status: str
    selection_status: str
    hold_return_pct: float | None
    friction_bps: float
    pattern_name: str | None
    upside_probability_pct: float | None
    resolved_late: bool

    def after_friction(self, mult: float = 1.0) -> float | None:
        if self.hold_return_pct is None:
            return None
        return round(self.hold_return_pct - (self.friction_bps * mult) / 100.0, 6)


@dataclass
class GateResult:
    name: str
    status: str
    detail: str
    required: bool = True


@dataclass
class AssetReport:
    asset_type: str
    resolved_selected: int = 0
    gates: list[GateResult] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str, *, required: bool = True) -> None:
        self.gates.append(GateResult(name=name, status=status, detail=detail, required=required))

    @property
    def eligible(self) -> bool:
        required = [g for g in self.gates if g.required]
        return bool(required) and all(g.status in _REQUIRED_STATUSES for g in required)


# --- DB access ---------------------------------------------------------------

def _parse_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def resolve_campaign(con: sqlite3.Connection, campaign_id: str | None) -> sqlite3.Row | None:
    if campaign_id:
        return con.execute(
            "select * from evidence_campaigns where campaign_id=?", (campaign_id,)
        ).fetchone()
    return con.execute(
        "select * from evidence_campaigns where status='active' "
        "order by started_at desc limit 1"
    ).fetchone()


def load_snapshots(con: sqlite3.Connection, campaign_id: str, asset_type: str) -> list[Snapshot]:
    rows = con.execute(
        "select ticker, asset_type, generated_at, status, selection_status, "
        "hold_return_pct, expected_friction_bps, pattern_name, pattern_metadata_json, "
        "resolved_late from prediction_snapshots "
        "where campaign_id=? and asset_type=? and selection_status in "
        "('selected','accepted_outside_top_n') order by generated_at",
        (campaign_id, asset_type),
    ).fetchall()
    out: list[Snapshot] = []
    for row in rows:
        upside = None
        raw_meta = row["pattern_metadata_json"]
        if raw_meta:
            try:
                meta = json.loads(raw_meta)
                upside = meta.get("upside_probability_pct")
            except (json.JSONDecodeError, AttributeError):
                upside = None
        out.append(
            Snapshot(
                ticker=str(row["ticker"]),
                asset_type=str(row["asset_type"]),
                generated_at=_parse_dt(row["generated_at"]) or datetime.min.replace(tzinfo=timezone.utc),
                status=str(row["status"]),
                selection_status=str(row["selection_status"]),
                hold_return_pct=(
                    float(row["hold_return_pct"]) if row["hold_return_pct"] is not None else None
                ),
                friction_bps=float(row["expected_friction_bps"] or 0.0),
                pattern_name=row["pattern_name"],
                upside_probability_pct=(float(upside) if upside is not None else None),
                resolved_late=bool(row["resolved_late"]),
            )
        )
    return out


def load_benchmark_series(con: sqlite3.Connection, symbol: str) -> tuple[list[datetime], list[float]]:
    rows = con.execute(
        "select bar_date, close from daily_bar_history where symbol=? and close is not null "
        "order by bar_date",
        (symbol,),
    ).fetchall()
    dates: list[datetime] = []
    closes: list[float] = []
    for row in rows:
        parsed = _parse_dt(row["bar_date"])
        if parsed is None:
            continue
        dates.append(parsed)
        closes.append(float(row["close"]))
    return dates, closes


# --- benchmark / regime ------------------------------------------------------

class Benchmark:
    """Forward-return and regime helper over a daily close series."""

    def __init__(self, dates: list[datetime], closes: list[float]) -> None:
        self.dates = dates
        self.closes = closes

    @property
    def available(self) -> bool:
        return len(self.dates) > REGIME_LOOKBACK_BARS

    def _index_on_or_before(self, when: datetime) -> int | None:
        idx = bisect_right(self.dates, when) - 1
        return idx if idx >= 0 else None

    def forward_return_pct(self, start: datetime, forward_days: int) -> float | None:
        i0 = self._index_on_or_before(start)
        i1 = self._index_on_or_before(start + timedelta(days=forward_days))
        if i0 is None or i1 is None or i1 <= i0:
            return None
        c0 = self.closes[i0]
        c1 = self.closes[i1]
        if c0 <= 0:
            return None
        return round((c1 / c0 - 1.0) * 100.0, 6)

    def momentum_forward_return_pct(self, start: datetime, forward_days: int) -> float | None:
        """Momentum baseline: take the benchmark forward return only when the
        benchmark closed above its SMA(50) at entry; otherwise flat (0%)."""
        i0 = self._index_on_or_before(start)
        if i0 is None or i0 < MOMENTUM_SMA_DAYS:
            return None
        sma = mean(self.closes[i0 - MOMENTUM_SMA_DAYS + 1 : i0 + 1])
        if self.closes[i0] < sma:
            return 0.0
        return self.forward_return_pct(start, forward_days)

    def regime(self, when: datetime) -> str:
        idx = self._index_on_or_before(when)
        if idx is None or idx < REGIME_LOOKBACK_BARS:
            return "unknown"
        sma = mean(self.closes[idx - REGIME_SMA_BARS + 1 : idx + 1])
        recent = self.closes[idx]
        older = self.closes[idx - REGIME_SLOPE_BARS]
        if recent > sma and recent > older:
            return "bull"
        if recent < sma and recent < older:
            return "bear"
        return "chop"


# --- walk-forward holdout reference ------------------------------------------

def wf_holdout_reference(
    con: sqlite3.Connection, asset_type: str, campaign_fingerprint: str | None
) -> tuple[dict | None, bool]:
    """Return (holdout metric row, fingerprint_matches) for the latest WF run.

    fingerprint_matches is False when the stored run predates the current engine
    (NULL fingerprint) or was computed under a different config than the campaign.
    """
    row = con.execute(
        "select config_fingerprint, metrics_json from walk_forward_runs "
        "order by created_at desc limit 1"
    ).fetchone()
    if row is None or not row["metrics_json"]:
        return None, False
    try:
        metrics = json.loads(row["metrics_json"])
    except json.JSONDecodeError:
        return None, False
    holdout = next(
        (
            r
            for r in metrics.get("by_asset_track", [])
            if r.get("asset_type") == asset_type and r.get("track") == "holdout"
        ),
        None,
    )
    run_fp = row["config_fingerprint"]
    matches = bool(run_fp) and bool(campaign_fingerprint) and run_fp == campaign_fingerprint
    return holdout, matches


# --- per-asset evaluation ----------------------------------------------------

def evaluate_asset(
    asset_type: str,
    snapshots: list[Snapshot],
    benchmark: Benchmark,
    holdout_ref: dict | None,
    holdout_matches: bool,
    forward_days: int,
    total_resolved_selected: int,
) -> AssetReport:
    report = AssetReport(asset_type=asset_type)

    resolved = [s for s in snapshots if s.status == "resolved" and s.hold_return_pct is not None]
    report.resolved_selected = len(resolved)
    afret = [s.after_friction() for s in resolved]
    afret = [v for v in afret if v is not None]
    afret_stressed = [s.after_friction(FRICTION_STRESS_MULT) for s in resolved]
    afret_stressed = [v for v in afret_stressed if v is not None]

    # 1) Sample floors.
    report.add(
        "samples_overall_100",
        PASS if total_resolved_selected >= MIN_TOTAL_SELECTED_RESOLVED else INSUFFICIENT,
        f"overall resolved selected={total_resolved_selected} (need >={MIN_TOTAL_SELECTED_RESOLVED})",
    )
    report.add(
        "samples_asset_60",
        PASS if len(resolved) >= MIN_PER_ASSET else INSUFFICIENT,
        f"{asset_type} resolved selected={len(resolved)} (need >={MIN_PER_ASSET})",
    )

    # Per-pattern floor: every relied-on pattern needs >=30. "Relied-on" = any
    # pattern actually present; if none reach 30 the gate is insufficient.
    pattern_counts: dict[str, int] = {}
    for s in resolved:
        key = s.pattern_name or "(unnamed)"
        pattern_counts[key] = pattern_counts.get(key, 0) + 1
    qualifying = {p: c for p, c in pattern_counts.items() if c >= MIN_PER_PATTERN}
    if not pattern_counts:
        report.add("samples_pattern_30", INSUFFICIENT, "no resolved patterns yet")
    else:
        top = sorted(pattern_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
        top_desc = ", ".join(f"{p}={c}" for p, c in top)
        report.add(
            "samples_pattern_30",
            PASS if qualifying else INSUFFICIENT,
            f"patterns>=30: {len(qualifying)}; top: {top_desc}",
        )

    # 2) Regime coverage.
    if not benchmark.available:
        report.add("regime_coverage", INSUFFICIENT, f"no {BENCHMARK_SYMBOL[asset_type]} bar history")
    else:
        regime_returns: dict[str, list[float]] = {}
        for s in resolved:
            regime = benchmark.regime(s.generated_at)
            if regime == "unknown":
                continue
            val = s.after_friction()
            if val is None:
                continue
            regime_returns.setdefault(regime, []).append(val)
        covered = {r: v for r, v in regime_returns.items() if len(v) >= MIN_SAMPLES_PER_REGIME}
        all_non_negative = all(mean(v) >= 0 for v in covered.values()) if covered else False
        detail = "; ".join(f"{r}: n={len(v)} mean_af={mean(v):+.3f}" for r, v in sorted(regime_returns.items()))
        ok = len(covered) >= MIN_REGIMES and all_non_negative
        status = PASS if ok else INSUFFICIENT if len(covered) < MIN_REGIMES else FAIL
        report.add("regime_coverage", status, detail or "no regime-classified samples")

    # 3) Median after-friction > 0 with bootstrap 90% CI excluding 0.
    if len(afret) < 2:
        report.add("median_after_friction_ci", INSUFFICIENT, f"n={len(afret)} (need >=2 for CI)")
    else:
        med = median(afret)
        lo, hi = bootstrap_median_ci(afret)
        excludes_zero = lo is not None and lo > 0
        status = PASS if (med > 0 and excludes_zero) else FAIL
        report.add(
            "median_after_friction_ci",
            status,
            f"median_af={med:+.4f}%  90%CI=[{lo:+.4f},{hi:+.4f}]  n={len(afret)}",
        )

    # 4) Stressed-friction mean > 0.
    if not afret_stressed:
        report.add("stressed_friction_mean_positive", INSUFFICIENT, "no resolved samples")
    else:
        m = mean(afret_stressed)
        report.add(
            "stressed_friction_mean_positive",
            PASS if m > 0 else FAIL,
            f"stressed mean_af={m:+.4f}%  n={len(afret_stressed)}",
        )

    # 5) Edge vs benchmark (SPY/BTC) and vs momentum baseline, after friction.
    if not benchmark.available or not resolved:
        report.add("edge_vs_benchmark", INSUFFICIENT, "no benchmark bars or no samples")
        report.add("edge_vs_momentum", INSUFFICIENT, "no benchmark bars or no samples")
    else:
        paired_strat: list[float] = []
        paired_bench: list[float] = []
        paired_momo: list[float] = []
        for s in resolved:
            bench = benchmark.forward_return_pct(s.generated_at, forward_days)
            momo = benchmark.momentum_forward_return_pct(s.generated_at, forward_days)
            strat = s.after_friction()
            if bench is None or strat is None:
                continue
            fr = (s.friction_bps) / 100.0
            paired_strat.append(strat)
            paired_bench.append(round(bench - fr, 6))
            if momo is not None:
                paired_momo.append(round(momo - fr, 6))
        if len(paired_strat) < 2:
            report.add("edge_vs_benchmark", INSUFFICIENT, f"paired n={len(paired_strat)}")
        else:
            edge = mean(paired_strat) - mean(paired_bench)
            report.add(
                "edge_vs_benchmark",
                PASS if edge > 0 else FAIL,
                f"edge_af vs {BENCHMARK_SYMBOL[asset_type]}={edge:+.4f}%  n={len(paired_strat)}",
            )
        if len(paired_momo) < 2:
            report.add("edge_vs_momentum", INSUFFICIENT, f"paired n={len(paired_momo)}")
        else:
            strat_for_momo = paired_strat[: len(paired_momo)]
            edge_m = mean(strat_for_momo) - mean(paired_momo)
            report.add(
                "edge_vs_momentum",
                PASS if edge_m > 0 else FAIL,
                f"edge_af vs SMA{MOMENTUM_SMA_DAYS} momentum={edge_m:+.4f}%  n={len(paired_momo)}",
            )

    # 6) Wilson 95% lower-bound hit rate > 50%.
    wins = sum(1 for s in resolved if (s.hold_return_pct or 0.0) > 0)
    lb, _ = wilson_bounds(wins, len(resolved))
    if lb is None:
        report.add("wilson_hit_rate_lb", INSUFFICIENT, "no resolved samples")
    else:
        report.add(
            "wilson_hit_rate_lb",
            PASS if lb > MIN_WILSON_HIT_RATE_LB_PCT else FAIL,
            f"hit={wins}/{len(resolved)} ({wins / len(resolved) * 100:.1f}%)  wilson_lb95={lb:.2f}% "
            f"(need >{MIN_WILSON_HIT_RATE_LB_PCT})",
        )

    # 7) Calibration gap <= 10 points in used bins.
    calib_pairs = [
        (s.upside_probability_pct, 1.0 if (s.hold_return_pct or 0.0) > 0 else 0.0)
        for s in resolved
        if s.upside_probability_pct is not None
    ]
    if not calib_pairs:
        report.add("calibration_gap", INSUFFICIENT, "no predictions carry upside_probability_pct")
    else:
        bands: dict[int, list[tuple[float, float]]] = {}
        for prob, realized in calib_pairs:
            band = min(int(prob // 10), 9)
            bands.setdefault(band, []).append((prob, realized))
        used = {b: v for b, v in bands.items() if len(v) >= MIN_CALIBRATION_BAND_SAMPLES}
        if not used:
            report.add(
                "calibration_gap",
                INSUFFICIENT,
                f"no probability band has >={MIN_CALIBRATION_BAND_SAMPLES} samples",
            )
        else:
            gaps = {
                b: abs(mean(p for p, _ in v) - mean(r for _, r in v) * 100.0)
                for b, v in used.items()
            }
            worst = max(gaps.values())
            report.add(
                "calibration_gap",
                PASS if worst <= MAX_CALIBRATION_GAP_PCT else FAIL,
                f"worst used-bin gap={worst:.2f}pts over {len(used)} bins (need <={MAX_CALIBRATION_GAP_PCT})",
            )

    # 8) Both campaign halves after-friction positive.
    if len(resolved) < 4:
        report.add("campaign_halves_positive", INSUFFICIENT, f"n={len(resolved)} (need >=4)")
    else:
        ordered = sorted(resolved, key=lambda s: s.generated_at)
        mid = len(ordered) // 2
        first = [s.after_friction() for s in ordered[:mid]]
        second = [s.after_friction() for s in ordered[mid:]]
        first = [v for v in first if v is not None]
        second = [v for v in second if v is not None]
        if not first or not second:
            report.add("campaign_halves_positive", INSUFFICIENT, "a half has no resolved returns")
        else:
            m1, m2 = mean(first), mean(second)
            report.add(
                "campaign_halves_positive",
                PASS if (m1 > 0 and m2 > 0) else FAIL,
                f"half1 mean_af={m1:+.4f}% (n={len(first)}), half2 mean_af={m2:+.4f}% (n={len(second)})",
            )

    # 9) Live hit rate inside walk-forward holdout Wilson interval (same fingerprint).
    if holdout_ref is None:
        report.add(
            "live_inside_wf_holdout_ci",
            INSUFFICIENT,
            "no walk-forward holdout row for this asset",
        )
    elif not holdout_matches:
        report.add(
            "live_inside_wf_holdout_ci",
            INSUFFICIENT,
            "latest walk-forward run fingerprint does not match the campaign; "
            "run POST /proof/walkforward/run under the current config first",
        )
    elif not resolved:
        report.add("live_inside_wf_holdout_ci", INSUFFICIENT, "no live resolved samples")
    else:
        ho_rate = holdout_ref.get("upside_hit_rate_pct")
        ho_n = int(holdout_ref.get("resolved_count") or 0)
        if ho_rate is None or ho_n <= 0:
            report.add("live_inside_wf_holdout_ci", INSUFFICIENT, "holdout row missing hit-rate/count")
        else:
            ho_lo, ho_hi = wilson_bounds(int(round(ho_rate / 100.0 * ho_n)), ho_n)
            live_rate = wins / len(resolved) * 100.0
            inside = ho_lo is not None and ho_hi is not None and ho_lo <= live_rate <= ho_hi
            report.add(
                "live_inside_wf_holdout_ci",
                PASS if inside else FAIL,
                f"live_hit={live_rate:.1f}%  holdout_ci=[{ho_lo:.1f},{ho_hi:.1f}] (n_ho={ho_n})",
            )

    # Advisory: concentration (per-symbol), tail loss, drawdown. Not hard gates.
    if resolved:
        counts: dict[str, int] = {}
        for s in resolved:
            counts[s.ticker] = counts.get(s.ticker, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        top1 = ranked[0][1] / len(resolved) * 100.0
        top3 = sum(c for _, c in ranked[:3]) / len(resolved) * 100.0
        concentrated = top1 > CONCENTRATION_TOP1_WARN_PCT or top3 > CONCENTRATION_TOP3_WARN_PCT
        report.add(
            "concentration_advisory",
            REVIEW,
            f"top1={ranked[0][0]} {top1:.1f}%, top3={top3:.1f}%"
            + ("  [flag: concentrated]" if concentrated else ""),
            required=False,
        )
        report.add(
            "tail_drawdown_advisory",
            REVIEW,
            f"worst_af={min(afret):+.3f}%  worst_decile_mean_af={worst_decile_mean(afret):+.3f}%  "
            f"max_drawdown_af={max_drawdown_pct(afret):+.3f}%",
            required=False,
        )

    return report


# --- campaign-wide ops integrity ---------------------------------------------

def evaluate_ops_integrity(
    con: sqlite3.Connection, campaign: sqlite3.Row
) -> list[GateResult]:
    gates: list[GateResult] = []
    started = _parse_dt(campaign["started_at"])

    # Window execution rate over the campaign lifetime.
    win_rows = con.execute(
        "select status, count(*) c from scan_windows where expected_start >= ? group by status",
        (started.isoformat() if started else "1970-01-01",),
    ).fetchall()
    win_counts = {str(r["status"]): int(r["c"]) for r in win_rows}
    executed = win_counts.get("executed", 0)
    missed = win_counts.get("missed", 0)
    considered = executed + missed
    if considered == 0:
        gates.append(GateResult("window_execution_95pct", INSUFFICIENT, "no closed windows in campaign yet"))
    else:
        pct = executed / considered * 100.0
        gates.append(
            GateResult(
                "window_execution_95pct",
                PASS if pct >= WINDOW_EXECUTION_MIN_PCT else FAIL,
                f"executed {executed}/{considered} ({pct:.1f}%, need >={WINDOW_EXECUTION_MIN_PCT}%)",
            )
        )

    # Unresolved-past-expiry rate among campaign selected predictions.
    rows = con.execute(
        "select status, count(*) c from prediction_snapshots where campaign_id=? "
        "and selection_status in ('selected','accepted_outside_top_n') group by status",
        (campaign["campaign_id"],),
    ).fetchall()
    status_counts = {str(r["status"]): int(r["c"]) for r in rows}
    resolved = status_counts.get("resolved", 0)
    missed_pred = status_counts.get("missed", 0)
    total_terminal = resolved + missed_pred
    if total_terminal == 0:
        gates.append(GateResult("unresolved_expiry_under_2pct", INSUFFICIENT, "no terminal predictions yet"))
    else:
        pct = missed_pred / total_terminal * 100.0
        gates.append(
            GateResult(
                "unresolved_expiry_under_2pct",
                PASS if pct < UNRESOLVED_EXPIRY_MAX_PCT else FAIL,
                f"missed {missed_pred}/{total_terminal} ({pct:.2f}%, need <{UNRESOLVED_EXPIRY_MAX_PCT}%)",
            )
        )

    # Fingerprint frozen: campaign active and its predictions all share its fingerprint.
    mismatched = con.execute(
        "select count(*) from prediction_snapshots where campaign_id=? "
        "and ifnull(config_fingerprint,'') <> ?",
        (campaign["campaign_id"], campaign["config_fingerprint"] or ""),
    ).fetchone()[0]
    frozen_ok = str(campaign["status"]) == "active" and int(mismatched) == 0
    gates.append(
        GateResult(
            "fingerprint_frozen",
            PASS if frozen_ok else FAIL,
            f"status={campaign['status']}  mismatched_predictions={mismatched}",
        )
    )

    # Immutability: trigger present and every campaign row carries a record_hash.
    trigger = con.execute(
        "select count(*) from sqlite_master where type='trigger' "
        "and name='trg_prediction_snapshots_immutable_core'"
    ).fetchone()[0]
    null_hash = con.execute(
        "select count(*) from prediction_snapshots where campaign_id=? and record_hash is null",
        (campaign["campaign_id"],),
    ).fetchone()[0]
    integrity_ok = int(trigger) == 1 and int(null_hash) == 0
    gates.append(
        GateResult(
            "prediction_immutability",
            PASS if integrity_ok else FAIL,
            f"trigger_present={bool(trigger)}  null_hash_rows={null_hash}",
        )
    )
    return gates


# --- reporting ---------------------------------------------------------------

def _fmt_gate(g: GateResult) -> str:
    tag = {PASS: "PASS", FAIL: "FAIL", INSUFFICIENT: "INSUFF", REVIEW: "INFO "}.get(g.status, g.status)
    req = "" if g.required else " (advisory)"
    return f"    [{tag}] {g.name}{req}: {g.detail}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=default_db_path(), help="Path to market_mate.db")
    parser.add_argument("--campaign", type=str, default=None, help="Campaign id (default: active campaign)")
    parser.add_argument("--forward-days", type=int, default=FORWARD_DAYS_DEFAULT, help="Forward horizon (days)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Database not found at {args.db}. Pass --db PATH.")
        return 1

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    campaign = resolve_campaign(con, args.campaign)
    if campaign is None:
        print("No matching evidence campaign found. A campaign opens on the first scan.")
        return 1

    total_resolved_selected = con.execute(
        "select count(*) from prediction_snapshots where campaign_id=? and status='resolved' "
        "and selection_status in ('selected','accepted_outside_top_n')",
        (campaign["campaign_id"],),
    ).fetchone()[0]

    ops_gates = evaluate_ops_integrity(con, campaign)
    ops_ok = all(g.status == PASS for g in ops_gates)

    asset_reports: list[AssetReport] = []
    for asset_type in ("stock", "crypto"):
        snapshots = load_snapshots(con, campaign["campaign_id"], asset_type)
        dates, closes = load_benchmark_series(con, BENCHMARK_SYMBOL[asset_type])
        benchmark = Benchmark(dates, closes)
        holdout_ref, holdout_matches = wf_holdout_reference(
            con, asset_type, campaign["config_fingerprint"]
        )
        asset_reports.append(
            evaluate_asset(
                asset_type,
                snapshots,
                benchmark,
                holdout_ref,
                holdout_matches,
                args.forward_days,
                int(total_resolved_selected),
            )
        )

    con.close()

    eligible_assets = [r.asset_type for r in asset_reports if r.eligible and ops_ok]
    overall_ready = bool(eligible_assets)

    if args.json:
        payload = {
            "campaign_id": campaign["campaign_id"],
            "campaign_status": campaign["status"],
            "config_fingerprint": campaign["config_fingerprint"],
            "total_resolved_selected": int(total_resolved_selected),
            "ops_integrity": {
                "ok": ops_ok,
                "gates": [g.__dict__ for g in ops_gates],
            },
            "assets": [
                {
                    "asset_type": r.asset_type,
                    "resolved_selected": r.resolved_selected,
                    "eligible": r.eligible and ops_ok,
                    "gates": [g.__dict__ for g in r.gates],
                }
                for r in asset_reports
            ],
            "eligible_assets": eligible_assets,
            "verdict": "ELIGIBLE_FOR_REVIEW" if overall_ready else "NOT_READY",
        }
        print(json.dumps(payload, indent=2))
        return 0 if overall_ready else 1

    print("=== Pilot-gate check (read-only; not a trade instruction) ===")
    print(f"campaign: {campaign['campaign_id']}  status={campaign['status']}")
    print(f"config_fingerprint: {campaign['config_fingerprint']}")
    print(f"total resolved selected predictions: {total_resolved_selected}")
    print()
    print("--- Campaign-wide ops integrity (must all PASS) ---")
    for g in ops_gates:
        print(_fmt_gate(g))
    print(f"    => ops integrity: {'PASS' if ops_ok else 'NOT PASS'}")
    print()
    for r in asset_reports:
        print(f"--- {r.asset_type.upper()} (resolved selected={r.resolved_selected}) ---")
        for g in r.gates:
            print(_fmt_gate(g))
        print(f"    => {r.asset_type} eligibility: {'ELIGIBLE' if (r.eligible and ops_ok) else 'NOT ELIGIBLE'}")
        print()
    print("=== Verdict ===")
    if overall_ready:
        print(f"  ELIGIBLE FOR SEPARATE REVIEW - asset class(es): {', '.join(eligible_assets)}")
        print("  This is a statistical precondition only. A small manual real-money pilot")
        print("  remains a separate, human decision. The app stays paper-only.")
    else:
        print("  NOT READY - one or more required gates did not PASS (or evidence is insufficient).")
        print("  Continue dry-run collection under the frozen campaign.")
    return 0 if overall_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
