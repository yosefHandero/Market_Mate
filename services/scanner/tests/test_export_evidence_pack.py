import unittest
from types import SimpleNamespace

from scripts import export_evidence_pack as export_module


class ExportEvidencePackTests(unittest.TestCase):
    def test_exit_bar_requires_paper_submissions_and_gate_consistency(self) -> None:
        result = export_module._evaluate_exit_bar(
            readyz={"ready": True, "scan_fresh": True},
            validation_summary={
                "by_signal_and_gate": [
                    {"key": "BUY:passed", "evaluated_count": 20},
                    {"key": "SELL:passed", "evaluated_count": 20},
                    {"key": "BUY:blocked", "evaluated_count": 10},
                    {"key": "SELL:blocked", "evaluated_count": 10},
                ]
            },
            threshold_sweep={"recommendation": {"evidence_status": "ready"}},
            performance_report={"baseline": {"passes_baseline": True}},
            execution_alignment={
                "taken_trades": {"total_signals": 4},
                "skipped_or_watched": {"total_signals": 4},
                "blocked_previews": {"total_signals": 4},
                "journal_took": {"total_signals": 4},
            },
            gate_consistency={"mismatch_count": 1},
            paper_lifecycle={"submitted_count": 0},
        )

        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["paper_submissions_present"])
        self.assertFalse(result["checks"]["gate_consistency_ok"])

    def test_evidence_policy_exports_thresholds_and_minimum_proof_targets(self) -> None:
        settings = SimpleNamespace(
            validation_primary_horizon="1h",
            trust_recent_window_days=14,
            trade_gate_min_evaluated_count=20,
            trade_gate_min_win_rate=55.0,
            trade_gate_min_avg_return=0.15,
            calibration_min_signal_samples=20,
            calibration_min_score_band_samples=10,
            outcome_baseline_min_evaluated_per_horizon=20,
            outcome_baseline_min_mean_return_pct=0.0,
            stock_slippage_bps=5.0,
            stock_spread_bps=2.0,
            stock_fee_bps=0.0,
            crypto_slippage_bps=12.0,
            crypto_spread_bps=6.0,
            crypto_fee_bps=10.0,
        )
        trust_snapshot = SimpleNamespace(
            window=SimpleNamespace(start="2026-03-01T00:00:00Z", end="2026-03-15T00:00:00Z")
        )

        result = export_module._evidence_policy(settings=settings, trust_snapshot=trust_snapshot)

        self.assertEqual(result["primary_horizon"], "1h")
        self.assertEqual(result["thresholds"]["trade_gate_min_evaluated_count"], 20)
        self.assertEqual(result["minimum_proof_targets"]["passed_buy_signals"], 100)
        self.assertIn("core_data_only_variant", result["required_benchmarks"])

    def test_paper_trading_ops_summary_requires_operator_review_when_checks_fail(self) -> None:
        result = export_module._paper_trading_ops_summary(
            readyz={
                "ready": False,
                "scan_fresh": False,
                "scheduler_running": False,
                "trust_evidence_ready": False,
                "pending_due_15m_count": 2,
                "pending_due_1h_count": 0,
                "pending_due_1d_count": 0,
            },
            execution_alignment={
                "taken_trades": {"total_signals": 1},
                "skipped_or_watched": {"total_signals": 2},
                "blocked_previews": {"total_signals": 3},
                "journal_took": {"total_signals": 1},
            },
            gate_consistency={"mismatch_count": 1},
        )

        self.assertTrue(result["checklist"]["critical_pending_due"])
        self.assertFalse(result["checklist"]["gate_consistency_ok"])
        self.assertTrue(result["operator_review_required"])


if __name__ == "__main__":
    unittest.main()
