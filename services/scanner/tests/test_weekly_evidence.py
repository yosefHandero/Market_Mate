import unittest

from app.config import Settings
from app.core.weekly_backtest import PatternBacktestStats
from app.core.weekly_evidence import evaluate_weekly_pattern_evidence


class WeeklyEvidenceTests(unittest.TestCase):
    def test_historical_only_keeps_real_money_trust_blocked(self) -> None:
        settings = Settings(
            weekly_pattern_gate_min_historical_samples=10,
            weekly_pattern_gate_min_backfilled_samples=10,
            weekly_pattern_gate_min_live_forward_samples=5,
            weekly_pattern_gate_min_out_of_sample_samples=5,
        )
        verdict = evaluate_weekly_pattern_evidence(
            stats_by_source={
                "historical": PatternBacktestStats("uptrend_ma_stack", 40, 60.0, 0.5),
                "backfilled_replay": PatternBacktestStats("uptrend_ma_stack", 25, 58.0, 0.4),
                "live_paper_forward": PatternBacktestStats("uptrend_ma_stack", 0, None, None),
                "out_of_sample": PatternBacktestStats("uptrend_ma_stack", 0, None, None),
            },
            settings=settings,
        )
        self.assertTrue(verdict.real_money_trust_blocked)
        self.assertEqual(verdict.evidence_basis, "historical_only")
        self.assertTrue(verdict.pattern_has_enough_historical_samples)

    def test_backfilled_only_calibration_keeps_real_money_trust_blocked(self) -> None:
        settings = Settings(
            weekly_pattern_gate_min_historical_samples=10,
            weekly_pattern_gate_min_backfilled_samples=10,
            weekly_pattern_gate_min_live_forward_samples=5,
            weekly_pattern_gate_min_out_of_sample_samples=5,
        )
        verdict = evaluate_weekly_pattern_evidence(
            stats_by_source={
                "historical": PatternBacktestStats("uptrend_ma_stack", 0, None, None),
                "backfilled_replay": PatternBacktestStats("uptrend_ma_stack", 40, 70.0, 0.9),
                "live_paper_forward": PatternBacktestStats("uptrend_ma_stack", 0, None, None),
                "out_of_sample": PatternBacktestStats("uptrend_ma_stack", 0, None, None),
            },
            settings=settings,
        )
        self.assertTrue(verdict.real_money_trust_blocked)
        self.assertTrue(verdict.pattern_has_enough_backfilled_replay_samples)
        self.assertEqual(verdict.evidence_basis, "historical_only")

    def test_oos_missing_keeps_trust_blocked_even_with_strong_live_forward(self) -> None:
        settings = Settings(
            weekly_pattern_gate_min_live_forward_samples=5,
            weekly_pattern_gate_min_out_of_sample_samples=5,
            weekly_pattern_gate_min_win_rate=50.0,
            weekly_pattern_gate_min_avg_return=0.0,
        )
        verdict = evaluate_weekly_pattern_evidence(
            stats_by_source={
                "historical": PatternBacktestStats("uptrend_ma_stack", 40, 60.0, 0.5),
                "backfilled_replay": PatternBacktestStats("uptrend_ma_stack", 25, 58.0, 0.4),
                "live_paper_forward": PatternBacktestStats("uptrend_ma_stack", 30, 70.0, 0.8),
                "out_of_sample": PatternBacktestStats("uptrend_ma_stack", 0, None, None),
            },
            settings=settings,
        )
        self.assertTrue(verdict.real_money_trust_blocked)

    def test_live_forward_and_oos_can_clear_real_money_trust_block(self) -> None:
        settings = Settings(
            weekly_pattern_gate_min_historical_samples=10,
            weekly_pattern_gate_min_backfilled_samples=10,
            weekly_pattern_gate_min_live_forward_samples=5,
            weekly_pattern_gate_min_out_of_sample_samples=5,
            weekly_pattern_gate_min_win_rate=50.0,
            weekly_pattern_gate_min_avg_return=0.0,
        )
        verdict = evaluate_weekly_pattern_evidence(
            stats_by_source={
                "historical": PatternBacktestStats("uptrend_ma_stack", 40, 60.0, 0.5),
                "backfilled_replay": PatternBacktestStats("uptrend_ma_stack", 25, 58.0, 0.4),
                "live_paper_forward": PatternBacktestStats("uptrend_ma_stack", 8, 62.0, 0.6),
                "out_of_sample": PatternBacktestStats("uptrend_ma_stack", 6, 55.0, 0.2),
            },
            settings=settings,
        )
        self.assertFalse(verdict.real_money_trust_blocked)
        self.assertEqual(verdict.evidence_basis, "live_forward_proven")


if __name__ == "__main__":
    unittest.main()
