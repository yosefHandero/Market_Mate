#!/usr/bin/env python3
"""BUY-evidence-after-friction analysis (tracked, reproducible).

Reads stored signal outcomes and reports whether BUY (and SELL, for contrast) is
trustworthy AFTER trading costs, split by asset type and horizon, with
out-of-sample (walk-forward) windows, false-positive rates, and tail/worst-case
loss. This is read-only analysis: it does not loosen any threshold and does not
generate or force any signals.

Replicates the backend validation math (services/scanner/app/services/repository.py):
  win        : return_pct > 0
  false pos  : return_pct <= 0
  friction   : subtract (bps * mult) / 100 from the percent return
               stock = 5 + 2 + 0 = 7 bps; crypto = 12 + 6 + 10 = 28 bps
               scenarios: base x1.0, stressed x1.5, worst x2.5
  out-of-sample: sort by generated_at, split at midpoint (older half = in-sample).

Usage:
  python scripts/buy_evidence_analysis.py [--db PATH] [--min-sample N]

Default DB resolves to services/scanner/market_mate.db relative to this file, so
it can be run from anywhere. The DB itself stays gitignored.
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

STOCK_BPS = 5 + 2 + 0
CRYPTO_BPS = 12 + 6 + 10
MULT = {"base": 1.0, "stressed": 1.5, "worst": 2.5}
HORIZONS = ("15m", "1h", "1d", "1w")
SCENARIOS = ("base", "stressed", "worst")


def default_db_path() -> Path:
    # scripts/buy_evidence_analysis.py -> services/scanner/market_mate.db
    return Path(__file__).resolve().parent.parent / "market_mate.db"


def friction_pct(asset_type: str, scenario: str) -> float:
    bps = CRYPTO_BPS if asset_type == "crypto" else STOCK_BPS
    return (bps * MULT[scenario]) / 100.0


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = pct / 100.0 * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac, 4)


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


def tail_risk_summary(adj_returns: list[float]) -> dict | None:
    if not adj_returns:
        return None
    sorted_adj = sorted(adj_returns)
    tail_n = max(1, len(sorted_adj) // 10)
    return {
        "n": len(sorted_adj),
        "worst": round(min(sorted_adj), 4),
        "p10": _percentile(sorted_adj, 10.0),
        "worst_decile_mean": round(mean(sorted_adj[:tail_n]), 4),
        "max_drawdown": max_drawdown_pct(adj_returns),
        "mean_stressed": None,
    }


def summarize(rows, horizon: str, scenario: str, min_sample: int) -> dict | None:
    col = f"return_after_{horizon}"
    gross: list[float] = []
    adj: list[float] = []
    for r in rows:
        v = r[col]
        if v is None:
            continue
        gross.append(v)
        adj.append(round(v - friction_pct(r["asset_type"], scenario), 4))
    n = len(gross)
    if n == 0:
        return None
    wins = [g for g in gross if g > 0]
    fps = [g for g in gross if g <= 0]
    adj_wins = [a for a in adj if a > 0]
    adj_sorted = sorted(adj)
    # Worst-decile mean: average of the worst 10% post-friction outcomes (tail loss).
    tail_n = max(1, n // 10)
    worst_decile_mean = round(mean(adj_sorted[:tail_n]), 4)
    return {
        "n": n,
        "win_rate": round(len(wins) / n * 100, 2),
        "fp_rate": round(len(fps) / n * 100, 2),
        "mean_gross": round(mean(gross), 4),
        "median_gross": round(median(gross), 4),
        "mean_adj": round(mean(adj), 4),
        "median_adj": round(median(adj), 4),
        "adj_win_rate": round(len(adj_wins) / n * 100, 2),
        "worst": round(min(gross), 4),
        "worst_adj": round(min(adj), 4),
        "p05_adj": _percentile(adj_sorted, 5.0),
        "worst_decile_mean_adj": worst_decile_mean,
        "min_sample_met": n >= min_sample,
    }


def fetch_exit_window_rows(con, *, asset_type: str | None = None):
    tables = {
        row[0]
        for row in con.execute("select name from sqlite_master where type='table'").fetchall()
    }
    if "prediction_snapshots" not in tables:
        return []
    columns = {row[1] for row in con.execute("pragma table_info(prediction_snapshots)").fetchall()}
    if "protected_return_pct" not in columns:
        return []
    q = (
        "select asset_type, protected_return_pct, hold_return_pct, exit_window_helped "
        "from prediction_snapshots where exit_window_status='resolved' "
        "and protected_return_pct is not null and hold_return_pct is not null"
    )
    p: list = []
    if asset_type:
        q += " and asset_type=?"
        p.append(asset_type)
    q += " order by generated_at"
    return con.execute(q, p).fetchall()


def exit_window_adj_returns(rows, *, use_protected: bool, scenario: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        raw = row["protected_return_pct"] if use_protected else row["hold_return_pct"]
        if raw is None:
            continue
        values.append(round(float(raw) - friction_pct(row["asset_type"], scenario), 4))
    return values


def fetch(con, signal: str | None = None, asset_type: str | None = None):
    q = "select * from signal_outcomes where 1=1"
    p: list = []
    if signal:
        q += " and signal=?"
        p.append(signal)
    if asset_type:
        q += " and asset_type=?"
        p.append(asset_type)
    q += " order by generated_at"
    return con.execute(q, p).fetchall()


def line(label: str, s: dict | None) -> None:
    if s is None:
        print(f"  {label:26s}  (no evaluated outcomes)")
        return
    print(
        f"  {label:26s}  n={s['n']:4d}  win%={s['win_rate']:6.2f}  fp%={s['fp_rate']:6.2f}  "
        f"mean_adj={s['mean_adj']:+.3f}  med_adj={s['median_adj']:+.3f}  "
        f"worst_adj={s['worst_adj']:+.3f}  tail10%={s['worst_decile_mean_adj']:+.3f}  "
        f"sample_ok={s['min_sample_met']}"
    )


def line_tail(label: str, summary: dict | None, *, stressed_mean: float | None = None) -> None:
    if summary is None:
        print(f"  {label:26s}  (no evaluated outcomes)")
        return
    stressed = f"  stressed_mean={stressed_mean:+.3f}" if stressed_mean is not None else ""
    print(
        f"  {label:26s}  n={summary['n']:4d}  worst={summary['worst']:+.3f}  "
        f"p10={summary['p10']:+.3f}  tail10%={summary['worst_decile_mean']:+.3f}  "
        f"max_dd={summary['max_drawdown']:+.3f}{stressed}"
    )


def verdict(buy_oos_1h: dict | None, buy_oos_1d: dict | None, buy_oos_1w: dict | None = None) -> str:
    def positive(s: dict | None) -> bool:
        return s is not None and s["mean_adj"] > 0 and s["min_sample_met"]

    if positive(buy_oos_1h) and positive(buy_oos_1d) and (buy_oos_1w is None or positive(buy_oos_1w)):
        return (
            "BUY out-of-sample expectancy is positive after friction at required horizons "
            "(1h, 1d, and 1w when available)."
        )
    return (
        "BUY is NOT real-money ready: out-of-sample post-friction expectancy is not "
        "positive (with sufficient samples) at required horizons. Keep BUY paper / "
        "manual-review only."
    )


def split_out_of_sample(rows, *, mode: str = "midpoint", wf_holdout_days: int = 7):
    if not rows:
        return [], []
    if mode == "wf_holdout":
        latest = rows[-1]["generated_at"]
        if isinstance(latest, str):
            latest = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        cutoff = latest - timedelta(days=wf_holdout_days)
        in_sample = [row for row in rows if row["generated_at"] < cutoff]
        out_sample = [row for row in rows if row["generated_at"] >= cutoff]
        return in_sample, out_sample
    mid = max(len(rows) // 2, 1)
    return rows[:mid], rows[mid:]


def concentration_report(rows) -> list[tuple[str, int, float]]:
    if not rows:
        return []
    counts: dict[str, int] = {}
    for row in rows:
        ticker = str(row["ticker"])
        counts[ticker] = counts.get(ticker, 0) + 1
    total = len(rows)
    return [
        (ticker, count, round(count / total * 100, 2))
        for ticker, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]


def mean_adj_values(rows, horizon: str, scenario: str = "base") -> list[float]:
    col = f"return_after_{horizon}"
    values: list[float] = []
    for row in rows:
        raw = row[col]
        if raw is None:
            continue
        values.append(round(raw - friction_pct(row["asset_type"], scenario), 4))
    return values


def bootstrap_mean_ci(values: list[float], *, iterations: int = 1000, alpha: float = 0.05) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    import random

    rng = random.Random(42)
    means: list[float] = []
    for _ in range(iterations):
        sample = [values[rng.randrange(len(values))] for _ in range(len(values))]
        means.append(mean(sample))
    means.sort()
    lower_idx = max(int((alpha / 2) * len(means)), 0)
    upper_idx = min(int((1 - alpha / 2) * len(means)) - 1, len(means) - 1)
    return round(means[lower_idx], 4), round(means[upper_idx], 4)


def leave_one_symbol_out_summary(rows, horizon: str, scenario: str = "base") -> list[tuple[str, int, float | None]]:
    tickers = sorted({str(row["ticker"]) for row in rows})
    summaries: list[tuple[str, int, float | None]] = []
    for ticker in tickers:
        subset = [row for row in rows if str(row["ticker"]) != ticker]
        values = mean_adj_values(subset, horizon, scenario)
        if not values:
            summaries.append((ticker, 0, None))
            continue
        summaries.append((ticker, len(values), round(mean(values), 4)))
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=default_db_path(), help="Path to market_mate.db")
    parser.add_argument("--min-sample", type=int, default=30, help="Minimum evaluated sample size")
    parser.add_argument(
        "--oos-mode",
        choices=("midpoint", "wf_holdout"),
        default="midpoint",
        help="Out-of-sample split: midpoint half or last N days holdout (matches API WF_HOLDOUT_DAYS).",
    )
    parser.add_argument(
        "--wf-holdout-days",
        type=int,
        default=7,
        help="Holdout window when --oos-mode=wf_holdout.",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Database not found at {args.db}. Pass --db PATH to point at a scanner DB.")
        return 1

    con = sqlite3.connect(str(args.db))
    con.row_factory = sqlite3.Row

    print("=== signal counts ===")
    for r in con.execute(
        "select signal, count(*) c from signal_outcomes group by signal order by c desc"
    ):
        print(f"  {r['signal']:6s} {r['c']}")
    print("  asset split:")
    for r in con.execute("select asset_type, count(*) c from signal_outcomes group by asset_type"):
        print(f"    {r['asset_type']}: {r['c']}")

    for horizon in HORIZONS:
        print(f"\n=== HORIZON {horizon} ===")
        for signal in ("BUY", "SELL", "HOLD"):
            rows = fetch(con, signal=signal)
            print(f" [{signal}] all assets")
            for sc in SCENARIOS:
                line(f"friction={sc}", summarize(rows, horizon, sc, args.min_sample))
            for at in ("stock", "crypto"):
                line(
                    f"{at} (base)",
                    summarize(fetch(con, signal=signal, asset_type=at), horizon, "base", args.min_sample),
                )

    print(f"\n=== BUY out-of-sample / walk-forward (base friction, mode={args.oos_mode}) ===")
    buy = fetch(con, signal="BUY")
    buy_in, buy_out = split_out_of_sample(
        buy,
        mode=args.oos_mode,
        wf_holdout_days=args.wf_holdout_days,
    )
    oos = {}
    for horizon in ("1h", "1d", "1w"):
        in_s = summarize(buy_in, horizon, "base", args.min_sample)
        out_s = summarize(buy_out, horizon, "base", args.min_sample)
        if horizon == "1w":
            print(f" [{horizon}]")
            line("in_sample", in_s)
            line("out_of_sample base", out_s)
            line("out_of_sample stressed", summarize(buy_out, horizon, "stressed", args.min_sample))
        else:
            print(f" [{horizon}]")
            line("in_sample", in_s)
            line("out_of_sample", out_s)
        oos[horizon] = out_s

    print("\n=== BUY out-of-sample by asset type (1h, base friction) ===")
    for at in ("stock", "crypto"):
        rows = fetch(con, signal="BUY", asset_type=at)
        rows_in, rows_out = split_out_of_sample(
            rows,
            mode=args.oos_mode,
            wf_holdout_days=args.wf_holdout_days,
        )
        line(f"{at} in_sample", summarize(rows_in, "1h", "base", args.min_sample))
        line(f"{at} out_of_sample", summarize(rows_out, "1h", "base", args.min_sample))

    print("\n=== BUY out-of-sample by asset type (1w, base + stressed friction) ===")
    for at in ("stock", "crypto"):
        rows = fetch(con, signal="BUY", asset_type=at)
        rows_in, rows_out = split_out_of_sample(
            rows,
            mode=args.oos_mode,
            wf_holdout_days=args.wf_holdout_days,
        )
        line(f"{at} 1w in_sample base", summarize(rows_in, "1w", "base", args.min_sample))
        line(f"{at} 1w out_of_sample base", summarize(rows_out, "1w", "base", args.min_sample))
        line(f"{at} 1w out_of_sample stressed", summarize(rows_out, "1w", "stressed", args.min_sample))

    print("\n=== BUY 1w tail-risk (base friction, stock/crypto separate) ===")
    for at in ("stock", "crypto"):
        rows = fetch(con, signal="BUY", asset_type=at)
        base_adj = mean_adj_values(rows, "1w", "base")
        stressed_adj = mean_adj_values(rows, "1w", "stressed")
        summary = tail_risk_summary(base_adj)
        stressed_mean = round(mean(stressed_adj), 4) if stressed_adj else None
        line_tail(f"{at} BUY 1w", summary, stressed_mean=stressed_mean)

    print("\n=== Exit-window 1w tail-risk (protected vs hold, stressed friction) ===")
    exit_rows = fetch_exit_window_rows(con)
    if not exit_rows:
        print("  (no resolved exit-window snapshots yet)")
    else:
        for at in ("stock", "crypto"):
            asset_rows = fetch_exit_window_rows(con, asset_type=at)
            protected = exit_window_adj_returns(asset_rows, use_protected=True, scenario="stressed")
            hold = exit_window_adj_returns(asset_rows, use_protected=False, scenario="stressed")
            line_tail(f"{at} exit protected", tail_risk_summary(protected))
            line_tail(f"{at} exit hold", tail_risk_summary(hold))

    print("\n=== concentration (BUY 1h resolved) ===")
    buy_1h_values = mean_adj_values(buy, "1h", "base")
    for ticker, count, pct in concentration_report(buy)[:8]:
        print(f"  {ticker:8s}  n={count:4d}  share={pct:5.1f}%")
    if buy_1h_values:
        ci_low, ci_high = bootstrap_mean_ci(buy_1h_values)
        print(
            f"  BUY 1h mean_adj={mean(buy_1h_values):+.4f}%  "
            f"95% bootstrap CI [{ci_low:+.4f}, {ci_high:+.4f}]  n={len(buy_1h_values)}"
        )

    print("\n=== BUY 1h leave-one-symbol-out mean_adj ===")
    for ticker, n, excluded_mean in leave_one_symbol_out_summary(buy, "1h", "base")[:12]:
        if excluded_mean is None:
            print(f"  exclude {ticker:8s}  (no remaining samples)")
        else:
            print(f"  exclude {ticker:8s}  n={n:4d}  mean_adj={excluded_mean:+.4f}%")

    print("\n=== verdict ===")
    print(" " + verdict(oos.get("1h"), oos.get("1d"), oos.get("1w")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
