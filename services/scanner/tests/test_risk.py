from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from app.schemas import SignalOutcomePerformanceBucket, SignalOutcomeSummary
from app.services.risk import RiskService


class _FakeRepo:
    def __init__(self) -> None:
        self.latest_context = SimpleNamespace(
            run_id="run-123",
            symbol="AAPL",
            signal="BUY",
            raw_score=68.0,
            calibrated_confidence=72.0,
            calibration_source="signal",
            score_band="60-69",
            signal_generated_at=datetime.now(timezone.utc),
            last_updated=datetime.now(timezone.utc),
        )

    def get_latest_signal_context(self, symbol: str):
        return self.latest_context if symbol == "AAPL" else None

    def confidence_bucket_for(self, confidence: float) -> str:
        if confidence >= 60:
            return "60-74"
        if confidence >= 45:
            return "45-59"
        return "0-44"

    def get_signal_outcome_summary(self, asset_type=None) -> SignalOutcomeSummary:
        def bucket(key: str, count: int, win_rate: float, avg_return: float) -> SignalOutcomePerformanceBucket:
            return SignalOutcomePerformanceBucket(
                key=key,
                total_signals=count,
                evaluated_15m_count=0,
                evaluated_1h_count=count,
                evaluated_1d_count=0,
                win_rate_15m=None,
                avg_return_15m=None,
                win_rate_1h=win_rate,
                avg_return_1h=avg_return,
                win_rate_1d=None,
                avg_return_1d=None,
            )

        return SignalOutcomeSummary(
            total_signals=25,
            pending_15m_count=0,
            pending_1h_count=0,
            pending_1d_count=0,
            overall=bucket("overall", 25, 60.0, 0.2),
            by_signal=[bucket("BUY", 25, 66.0, 0.25)],
            by_confidence_bucket=[],
            by_signal_confidence_bucket=[],
            by_signal_score_bucket=[bucket("BUY:60-69", 5, 75.0, 0.35)],
        )


class RiskServiceTests(unittest.TestCase):
    def test_signal_level_fallback_allows_when_band_is_still_maturing(self) -> None:
        service = RiskService()
        service.repo = _FakeRepo()
        service.settings.trade_gate_min_evaluated_count = 20
        service.settings.trade_gate_min_win_rate = 55.0
        service.settings.trade_gate_min_avg_return = 0.15
        service.settings.trade_gate_enabled = True

        eligibility = service.evaluate_trade(
            ticker="AAPL",
            side="buy",
            qty=1,
            latest_price=190.0,
        )

        self.assertTrue(eligibility.allowed)
        self.assertIn("signal-level validation", eligibility.reason)
        self.assertEqual(eligibility.raw_score, 68.0)
        self.assertEqual(eligibility.confidence, 72.0)
        self.assertEqual(eligibility.signal_run_id, "run-123")


if __name__ == "__main__":
    unittest.main()
