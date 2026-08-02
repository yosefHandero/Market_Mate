import unittest
from datetime import datetime, timedelta, timezone

from scripts.buy_evidence_analysis import (
    bootstrap_mean_ci,
    concentration_report,
    leave_one_symbol_out_summary,
    mean_adj_values,
    split_out_of_sample,
)


class BuyEvidenceAnalysisTests(unittest.TestCase):
    def _row(self, ticker: str, generated_at: datetime, return_1h: float | None = 1.0):
        return {
            "ticker": ticker,
            "asset_type": "stock",
            "generated_at": generated_at,
            "return_after_1h": return_1h,
        }

    def test_split_out_of_sample_midpoint(self) -> None:
        rows = [self._row("AAPL", datetime(2026, 1, d, tzinfo=timezone.utc)) for d in range(1, 5)]
        in_sample, out_sample = split_out_of_sample(rows, mode="midpoint")
        self.assertEqual(len(in_sample), 2)
        self.assertEqual(len(out_sample), 2)

    def test_split_out_of_sample_wf_holdout(self) -> None:
        rows = [
            self._row("AAPL", datetime(2026, 1, 1, tzinfo=timezone.utc)),
            self._row("MSFT", datetime(2026, 1, 10, tzinfo=timezone.utc)),
            self._row("NVDA", datetime(2026, 1, 20, tzinfo=timezone.utc)),
        ]
        in_sample, out_sample = split_out_of_sample(rows, mode="wf_holdout", wf_holdout_days=7)
        self.assertEqual(len(in_sample), 2)
        self.assertEqual(len(out_sample), 1)

    def test_concentration_report(self) -> None:
        rows = [
            self._row("AAPL", datetime(2026, 1, 1, tzinfo=timezone.utc)),
            self._row("AAPL", datetime(2026, 1, 2, tzinfo=timezone.utc)),
            self._row("MSFT", datetime(2026, 1, 3, tzinfo=timezone.utc)),
        ]
        report = concentration_report(rows)
        self.assertEqual(report[0][0], "AAPL")
        self.assertEqual(report[0][1], 2)
        self.assertAlmostEqual(report[0][2], 66.67, places=1)

    def test_leave_one_symbol_out_summary(self) -> None:
        rows = [
            self._row("AAPL", datetime(2026, 1, 1, tzinfo=timezone.utc), 2.0),
            self._row("MSFT", datetime(2026, 1, 2, tzinfo=timezone.utc), 0.0),
        ]
        summaries = leave_one_symbol_out_summary(rows, "1h", "base")
        self.assertEqual(len(summaries), 2)
        by_ticker = {item[0]: item[2] for item in summaries}
        self.assertAlmostEqual(by_ticker["AAPL"], -0.07, places=2)
        self.assertAlmostEqual(by_ticker["MSFT"], 1.93, places=2)

    def test_bootstrap_mean_ci_returns_bounds(self) -> None:
        values = mean_adj_values(
            [
                self._row("AAPL", datetime(2026, 1, 1, tzinfo=timezone.utc), 2.0),
                self._row("MSFT", datetime(2026, 1, 2, tzinfo=timezone.utc), 0.5),
                self._row("NVDA", datetime(2026, 1, 3, tzinfo=timezone.utc), -1.0),
            ],
            "1h",
            "base",
        )
        low, high = bootstrap_mean_ci(values, iterations=200)
        self.assertIsNotNone(low)
        self.assertIsNotNone(high)
        self.assertLessEqual(low, high)


if __name__ == "__main__":
    unittest.main()
