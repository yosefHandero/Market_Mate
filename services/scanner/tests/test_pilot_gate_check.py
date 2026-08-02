import unittest
from datetime import datetime, timedelta, timezone

from scripts.pilot_gate_check import (
    Benchmark,
    Snapshot,
    bootstrap_median_ci,
    evaluate_asset,
    wilson_bounds,
)


def _bars(count: int, *, last_day: datetime, start: float = 100.0, drift: float = 0.1):
    dates = []
    closes = []
    for offset in reversed(range(count)):
        day = last_day - timedelta(days=offset)
        idx = count - 1 - offset
        dates.append(day)
        closes.append(start + drift * idx)
    return dates, closes


def _snap(
    ticker: str,
    generated_at: datetime,
    ret: float | None,
    *,
    asset_type: str = "stock",
    pattern: str = "uptrend_ma_stack",
    upside: float | None = 60.0,
    friction_bps: float = 7.0,
    status: str = "resolved",
) -> Snapshot:
    return Snapshot(
        ticker=ticker,
        asset_type=asset_type,
        generated_at=generated_at,
        status=status,
        selection_status="selected",
        hold_return_pct=ret,
        friction_bps=friction_bps,
        pattern_name=pattern,
        upside_probability_pct=upside,
        resolved_late=False,
    )


class StatHelperTests(unittest.TestCase):
    def test_wilson_bounds_tighten_with_n(self) -> None:
        lo_small, hi_small = wilson_bounds(8, 10)
        lo_big, hi_big = wilson_bounds(80, 100)
        self.assertLess(lo_small, 80.0)
        self.assertGreater(lo_big, lo_small)
        self.assertLess(hi_big, hi_small)
        self.assertEqual(wilson_bounds(0, 0), (None, None))

    def test_bootstrap_median_ci_positive_sample_excludes_zero(self) -> None:
        values = [1.5] * 80
        lo, hi = bootstrap_median_ci(values)
        self.assertIsNotNone(lo)
        self.assertGreater(lo, 0.0)

    def test_bootstrap_median_ci_needs_two(self) -> None:
        self.assertEqual(bootstrap_median_ci([1.0]), (None, None))


class EvaluateAssetTests(unittest.TestCase):
    def _gate(self, report, name):
        return next(g for g in report.gates if g.name == name)

    def test_strong_asset_passes_core_statistical_gates(self) -> None:
        last_day = datetime(2026, 6, 1, tzinfo=timezone.utc)
        # Benchmark drifts up gently so strategy (larger positive returns) still beats it.
        bench = Benchmark(*_bars(400, last_day=last_day, drift=0.02))
        snapshots = []
        base = datetime(2025, 1, 6, tzinfo=timezone.utc)
        # 120 winners spread across a year -> strong hit rate, positive after friction.
        for i in range(120):
            gen = base + timedelta(days=3 * i)
            ret = 2.0 if i % 5 else -0.5  # ~80% win rate, clearly positive median
            snapshots.append(_snap(f"SYM{i % 8}", gen, ret, upside=62.0))
        holdout_ref = {"upside_hit_rate_pct": 80.0, "resolved_count": 120}

        report = evaluate_asset(
            "stock",
            snapshots,
            bench,
            holdout_ref,
            holdout_matches=True,
            forward_days=7,
            total_resolved_selected=150,
        )

        self.assertEqual(self._gate(report, "samples_overall_100").status, "PASS")
        self.assertEqual(self._gate(report, "samples_asset_60").status, "PASS")
        self.assertEqual(self._gate(report, "median_after_friction_ci").status, "PASS")
        self.assertEqual(self._gate(report, "stressed_friction_mean_positive").status, "PASS")
        self.assertEqual(self._gate(report, "wilson_hit_rate_lb").status, "PASS")
        self.assertEqual(self._gate(report, "edge_vs_benchmark").status, "PASS")
        self.assertEqual(self._gate(report, "campaign_halves_positive").status, "PASS")

    def test_losing_asset_fails_return_gates(self) -> None:
        last_day = datetime(2026, 6, 1, tzinfo=timezone.utc)
        bench = Benchmark(*_bars(400, last_day=last_day, drift=0.05))
        base = datetime(2025, 1, 6, tzinfo=timezone.utc)
        snapshots = [
            _snap(f"SYM{i % 8}", base + timedelta(days=3 * i), -1.0, upside=60.0)
            for i in range(80)
        ]
        report = evaluate_asset(
            "stock",
            snapshots,
            bench,
            {"upside_hit_rate_pct": 20.0, "resolved_count": 80},
            holdout_matches=True,
            forward_days=7,
            total_resolved_selected=80,
        )
        self.assertEqual(self._gate(report, "median_after_friction_ci").status, "FAIL")
        self.assertEqual(self._gate(report, "wilson_hit_rate_lb").status, "FAIL")
        self.assertFalse(report.eligible)

    def test_empty_asset_is_insufficient_not_eligible(self) -> None:
        bench = Benchmark([], [])
        report = evaluate_asset(
            "crypto",
            [],
            bench,
            None,
            holdout_matches=False,
            forward_days=7,
            total_resolved_selected=0,
        )
        self.assertFalse(report.eligible)
        self.assertTrue(all(g.status != "PASS" for g in report.gates if g.required))


if __name__ == "__main__":
    unittest.main()
