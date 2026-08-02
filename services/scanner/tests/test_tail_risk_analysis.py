from __future__ import annotations

import unittest

from scripts.buy_evidence_analysis import max_drawdown_pct, tail_risk_summary, verdict


class TailRiskAnalysisTests(unittest.TestCase):
    def test_max_drawdown_on_losing_sequence(self) -> None:
        drawdown = max_drawdown_pct([2.0, -3.0, -1.0, 1.0])
        self.assertIsNotNone(drawdown)
        self.assertLess(drawdown or 0.0, 0.0)

    def test_tail_risk_summary_includes_worst_decile(self) -> None:
        summary = tail_risk_summary([-5.0, -3.0, -2.0, -1.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["n"], 10)
        self.assertLess(summary["worst_decile_mean"], 0.0)

    def test_verdict_requires_1w_when_present(self) -> None:
        ok = {"mean_adj": 0.5, "min_sample_met": True}
        bad = {"mean_adj": -0.5, "min_sample_met": True}
        self.assertIn("NOT real-money ready", verdict(ok, ok, bad))
        self.assertIn("positive", verdict(ok, ok, ok))


if __name__ == "__main__":
    unittest.main()
