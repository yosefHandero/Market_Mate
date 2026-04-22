from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from app.schemas import SignalOutcomePerformanceBucket, SignalOutcomeSummary
from app.schemas import GateCheck
from app.services.risk import RiskService


class _FakeRepo:
    def __init__(self) -> None:
        self.latest_context = SimpleNamespace(
            signal_outcome_id=42,
            run_id="run-123",
            symbol="AAPL",
            asset_type="stock",
            signal="BUY",
            raw_score=68.0,
            calibrated_confidence=72.0,
            calibration_source="signal",
            score_band="60-69",
            signal_generated_at=datetime.now(timezone.utc),
            last_updated=datetime.now(timezone.utc),
            gate_passed=True,
            gate_reason="Locked scan gate passed.",
            gate_checks=[GateCheck(name="sample_size", passed=True, detail="25 vs 20 1h outcomes")],
            gate_evaluation_mode="scan_time_window_locked",
            evidence_basis="recent_window:14d:generated_at",
            trust_window_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
            trust_window_end=datetime(2026, 3, 15, tzinfo=timezone.utc),
            data_quality="ok",
            provider_status="ok",
            provider_warnings=[],
        )

    def get_latest_signal_context(self, symbol: str):
        return self.latest_context if symbol == "AAPL" else None

    def confidence_bucket_for(self, confidence: float) -> str:
        if confidence >= 60:
            return "60-74"
        if confidence >= 45:
            return "45-59"
        return "0-44"

    def get_latest_run_timestamp(self):
        return datetime.now(timezone.utc)

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

    def evaluate_signal_gate(self, *, asset_type, signal, score_band, horizon, observed_at=None):
        return SimpleNamespace(
            passed=True,
            reason="Stock signal passed signal-level evidence gates. Score-band bucket 60-69 is still maturing with 5 evaluated outcomes.",
            horizon=horizon,
            evidence_basis="recent_window:14d:generated_at",
            trust_window_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
            trust_window_end=datetime(2026, 3, 15, tzinfo=timezone.utc),
            signal_count=25,
            signal_win_rate=66.0,
            signal_avg_return=0.25,
            score_band_count=5,
            score_band_win_rate=75.0,
            score_band_avg_return=0.35,
            checks=[GateCheck(name="sample_size", passed=True, detail="25 vs 20 1h outcomes")],
        )

    def get_portfolio_guardrail_snapshot(self):
        return {
            "daily_notional": 0.0,
            "symbol_notional": {},
            "asset_type_notional": {},
            "resolved_trade_count": 0,
            "weighted_daily_return_pct": None,
            "loss_streak": 0,
            "max_drawdown_pct": 0.0,
            "horizon": "1h",
        }


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
        self.assertEqual(eligibility.reason, "Locked scan gate passed.")
        self.assertEqual(eligibility.raw_score, 68.0)
        self.assertEqual(eligibility.confidence, 72.0)
        self.assertEqual(eligibility.signal_outcome_id, 42)
        self.assertEqual(eligibility.signal_run_id, "run-123")
        self.assertEqual(eligibility.evidence_basis, "recent_window:14d:generated_at")
        self.assertEqual(eligibility.gate_evaluation_mode, "scan_time_window_locked")
        self.assertTrue(eligibility.latest_scan_fresh)
        self.assertTrue(eligibility.stored_gate_passed)

    def test_portfolio_guardrail_blocks_when_daily_notional_is_exceeded(self) -> None:
        service = RiskService()
        fake_repo = _FakeRepo()
        fake_repo.get_portfolio_guardrail_snapshot = lambda: {
            "daily_notional": 2400.0,
            "symbol_notional": {"AAPL": 500.0},
            "asset_type_notional": {"stock": 1800.0},
            "resolved_trade_count": 0,
            "weighted_daily_return_pct": None,
            "loss_streak": 0,
            "max_drawdown_pct": 0.0,
            "horizon": "1h",
        }
        service.repo = fake_repo
        service.settings.portfolio_risk_enabled = True
        service.settings.portfolio_max_daily_notional = 2500.0

        eligibility = service.evaluate_trade(
            ticker="AAPL",
            side="buy",
            qty=1,
            latest_price=200.0,
        )

        self.assertFalse(eligibility.allowed)
        self.assertEqual(eligibility.execution_eligibility, "blocked")
        self.assertIn("portfolio_daily_notional", eligibility.reason)

    def test_stored_scan_gate_must_match_locked_window_reevaluation(self) -> None:
        service = RiskService()
        fake_repo = _FakeRepo()

        def mismatch_gate(**kwargs):
            return SimpleNamespace(
                passed=False,
                reason="Locked window disagrees with stored scan gate.",
                horizon=kwargs.get("horizon", "1h"),
                evidence_basis="recent_window:14d:generated_at",
                trust_window_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
                trust_window_end=datetime(2026, 3, 15, tzinfo=timezone.utc),
                signal_count=25,
                signal_win_rate=66.0,
                signal_avg_return=0.25,
                score_band_count=5,
                score_band_win_rate=75.0,
                score_band_avg_return=0.35,
                checks=[],
            )

        fake_repo.evaluate_signal_gate = mismatch_gate
        service.repo = fake_repo
        service.settings.trade_gate_enabled = True

        eligibility = service.evaluate_trade(
            ticker="AAPL",
            side="buy",
            qty=1,
            latest_price=190.0,
        )

        self.assertFalse(eligibility.allowed)
        self.assertIn("does not match", eligibility.reason)

    def test_trade_gate_disabled_blocks_fail_closed(self) -> None:
        service = RiskService()
        service.repo = _FakeRepo()
        service.settings.trade_gate_enabled = False

        eligibility = service.evaluate_trade(
            ticker="AAPL",
            side="buy",
            qty=1,
            latest_price=190.0,
        )

        self.assertFalse(eligibility.allowed)
        self.assertEqual(eligibility.execution_eligibility, "blocked")
        self.assertIn("fail-closed", eligibility.reason)


if __name__ == "__main__":
    unittest.main()
