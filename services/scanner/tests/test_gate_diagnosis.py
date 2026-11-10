"""Gate explanations distinguish missing measurements from measured bad results."""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from app.config import Settings
from app.models.scan import SignalOutcomeORM
from app.services.repository import ScanRepository


class GateDiagnosisTests(unittest.TestCase):
    def gate(self, returns):
        repo = ScanRepository()
        repo.settings = Settings(_env_file=None, trade_gate_horizon="1h")
        rows = [
            SignalOutcomeORM(signal="BUY", entry_price=100, price_after_1h=100 + value,
                             generated_at=datetime(2026, 10, 25, 12), raw_score=55)
            for value in returns
        ]
        with patch("app.services.repository.select_hourly_buy_evidence", return_value={
            "Recent completed": rows, "Historical completed": [], "Historical replay": [],
        }):
            return repo.evaluate_signal_gate(asset_type="stock", signal="BUY", score_band="60-69", horizon="1h", observed_at=datetime(2026, 10, 26, 14, tzinfo=timezone.utc))

    def test_missing_returns_are_unavailable_not_measured_zero(self):
        gate = self.gate([])
        self.assertFalse(gate.passed)
        self.assertEqual(gate.signal_count, 0)
        self.assertIsNone(gate.signal_win_rate)
        self.assertIsNone(gate.signal_avg_return)
        checks = {check.name: check for check in gate.checks}
        self.assertIn("unavailable", checks["win_rate"].detail)
        self.assertIn("unavailable", checks["avg_return"].detail)
        self.assertEqual([check.name for check in gate.checks if not check.passed], ["sample_size", "win_rate", "avg_return"])

    def test_measured_zero_remains_a_measured_performance_failure(self):
        gate = self.gate([0.0] * 20)
        checks = {check.name: check for check in gate.checks}
        self.assertTrue(checks["sample_size"].passed)
        self.assertIn("0.00%", checks["win_rate"].detail)
        self.assertIn("0.0000%", checks["avg_return"].detail)
        self.assertNotIn("unavailable", checks["win_rate"].detail)
        self.assertFalse(gate.passed)

    def test_historical_shape_has_enough_samples_but_fails_both_performance_gates(self):
        # Synthetic replay of the historical figures, not current market evidence.
        gate = self.gate([0.3] * 9 + [-0.2391] * 26)
        self.assertEqual((gate.signal_count, gate.signal_win_rate, gate.signal_avg_return), (35, 25.71, -0.1005))
        self.assertEqual([check.name for check in gate.checks if not check.passed], ["win_rate", "avg_return"])
        self.assertFalse(gate.passed)


if __name__ == "__main__":
    unittest.main()
