import re
import unittest
from datetime import datetime, timezone

from app.core.readiness import (
    FRESH_BAR_MAX_MINUTES,
    AutomationReadinessContext,
    compute_trade_readiness,
    readiness_tone,
)
from app.schemas import DecisionRow, GateCheck, ScanResult


def _base_scan(**overrides) -> ScanResult:
    payload = {
        "ticker": "AAPL",
        "asset_type": "stock",
        "score": 72.0,
        "raw_score": 68.0,
        "calibrated_confidence": 88.0,
        "calibration_source": "signal",
        "confidence_label": "moderate_evidence",
        "strategy_id": "scanner-directional",
        "strategy_version": "v4.0-layered",
        "strategy_primary_horizon": "1h",
        "strategy_entry_assumption": "Break above session high",
        "strategy_exit_assumption": "Trail into close",
        "evidence_quality": "high",
        "evidence_quality_score": 0.82,
        "evidence_quality_reasons": [],
        "data_grade": "decision",
        "execution_eligibility": "eligible",
        "decision_signal": "BUY",
        "explanation": "Momentum is expanding.",
        "price": 100.0,
        "price_change_pct": 2.0,
        "relative_volume": 1.4,
        "relative_strength_pct": 0.6,
        "sentiment_score": 0.2,
        "filing_flag": False,
        "breakout_flag": True,
        "market_status": "bullish",
        "sector_strength_score": 0.5,
        "options_flow_score": 0.4,
        "options_flow_summary": "Calls leading.",
        "options_flow_bullish": True,
        "options_call_put_ratio": 1.3,
        "alert_sent": False,
        "news_checked": True,
        "news_source": "marketaux",
        "news_cache_label": None,
        "signal_label": "aggressive",
        "data_quality": "ok",
        "volatility_regime": "normal",
        "benchmark_ticker": "SPY",
        "benchmark_change_pct": 0.8,
        "recommended_action": "preview",
        "gate_passed": True,
        "gate_reason": "Passed",
        "gate_checks": [],
        "provider_status": "ok",
        "provider_warnings": [],
        "bar_age_minutes": 5.0,
        "freshness_flags": {},
        "created_at": datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc),
    }
    payload.update(overrides)
    return ScanResult(**payload)


def _sample_decision(**overrides) -> DecisionRow:
    payload = {
        "symbol": "AAPL",
        "asset_type": "stock",
        "signal": "BUY",
        "confidence": 88.0,
        "raw_score": 68.0,
        "calibration_source": "signal",
        "confidence_label": "moderate_evidence",
        "evidence_quality": "high",
        "evidence_quality_score": 0.85,
        "evidence_quality_reasons": (),
        "data_grade": "decision",
        "execution_eligibility": "eligible",
        "provider_status": "ok",
        "gate_passed": True,
        "bar_age_minutes": 5.0,
        "signal_age_minutes": 5.0,
        "freshness_flags": None,
        "recommended_action": "preview",
        "score_contributions": {},
        "strategy_version": "v4.0-layered",
        "short_metric_summary": "--",
        "last_updated": datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
    }
    payload.update(overrides)
    return DecisionRow(**payload)


class ReadinessTests(unittest.TestCase):
    def test_maps_tone_to_buckets(self) -> None:
        self.assertEqual(readiness_tone(90), "high")
        self.assertEqual(readiness_tone(70), "high")
        self.assertEqual(readiness_tone(69), "watch")
        self.assertEqual(readiness_tone(50), "watch")
        self.assertEqual(readiness_tone(49), "low")
        self.assertEqual(readiness_tone(25), "low")
        self.assertEqual(readiness_tone(24), "none")

    def test_produces_high_readiness_for_eligible_preview_row(self) -> None:
        readiness = compute_trade_readiness(_base_scan(), _sample_decision())
        self.assertGreaterEqual(readiness.score, 80)
        self.assertEqual(readiness.tone, "high")
        self.assertIn("Actionable", readiness.reason)

    def test_uses_scan_provider_and_freshness_over_stale_decision_metadata(self) -> None:
        readiness = compute_trade_readiness(
            _base_scan(provider_status="ok", bar_age_minutes=5.0, freshness_flags={}),
            _sample_decision(
                provider_status="critical",
                bar_age_minutes=400.0,
                freshness_flags={"bars": "stale"},
            ),
        )
        self.assertGreaterEqual(readiness.score, 80)
        self.assertIn("Actionable", readiness.reason)
        self.assertNotRegex(" ".join(readiness.reasons), r"critical|stale", re.IGNORECASE)

    def test_falls_back_from_calibrated_confidence_to_score_raw_and_decision(self) -> None:
        score_fallback = compute_trade_readiness(
            _base_scan(calibrated_confidence=0.0, score=68.0),
            _sample_decision(),
        )
        self.assertEqual(score_fallback.base_score, 68)
        self.assertGreaterEqual(score_fallback.score, 60)
        self.assertEqual(
            compute_trade_readiness(
                _base_scan(calibrated_confidence=0.0, score=61.0, raw_score=74.0),
                _sample_decision(confidence=82.0),
            ).base_score,
            61,
        )
        self.assertEqual(
            compute_trade_readiness(
                _base_scan(calibrated_confidence=0.0, score=0.0, raw_score=74.0),
                _sample_decision(confidence=82.0),
            ).base_score,
            74,
        )
        self.assertEqual(
            compute_trade_readiness(
                _base_scan(calibrated_confidence=0.0, score=0.0, raw_score=0.0),
                _sample_decision(confidence=82.0),
            ).base_score,
            82,
        )

    def test_caps_readiness_for_review_action(self) -> None:
        readiness = compute_trade_readiness(
            _base_scan(recommended_action="review"),
            _sample_decision(recommended_action="review"),
        )
        self.assertLessEqual(readiness.score, 65)
        self.assertGreaterEqual(readiness.score, 40)
        self.assertEqual(readiness.tone, "watch")
        self.assertIn("Watch only", readiness.reason)

    def test_produces_low_readiness_for_sample_size_blocked_row(self) -> None:
        scan = _base_scan(
            recommended_action="blocked",
            gate_passed=False,
            gate_reason="Blocked by sample_size: need 20.",
            gate_checks=[
                GateCheck(
                    name="sample_size",
                    passed=False,
                    detail="stock BUY bucket has 4 1h outcomes; need 20.",
                )
            ],
        )
        readiness = compute_trade_readiness(scan, _sample_decision(recommended_action="blocked"))
        self.assertGreaterEqual(readiness.score, 15)
        self.assertLessEqual(readiness.score, 35)
        self.assertEqual(readiness.tone, "low")
        self.assertIn("sample size", readiness.reason.lower())
        self.assertEqual(readiness.projection, "blocked_until_sample_size")

    def test_produces_low_readiness_for_hold_ignore_row(self) -> None:
        scan = _base_scan(
            decision_signal="HOLD",
            recommended_action="ignore",
            calibrated_confidence=90.0,
        )
        readiness = compute_trade_readiness(
            scan,
            _sample_decision(signal="HOLD", recommended_action="ignore"),
        )
        self.assertGreaterEqual(readiness.score, 10)
        self.assertLessEqual(readiness.score, 30)
        self.assertIn("HOLD", readiness.reason)

    def test_does_not_apply_gate_multiplier_for_hold_gate_not_applicable(self) -> None:
        scan = _base_scan(
            decision_signal="HOLD",
            recommended_action="ignore",
            gate_passed=False,
            gate_reason="Signal is HOLD, so trade gate is not applicable.",
            gate_checks=[],
            calibrated_confidence=90.0,
        )
        readiness = compute_trade_readiness(
            scan,
            _sample_decision(signal="HOLD", recommended_action="ignore"),
        )
        self.assertIn("HOLD", readiness.reason)
        self.assertFalse(readiness.reason.startswith("Blocked:"))
        self.assertNotIn("0.6 multiplier", " ".join(readiness.reasons))

    def test_applies_gate_multiplier_for_real_buy_gate_failure(self) -> None:
        scan = _base_scan(
            decision_signal="BUY",
            recommended_action="blocked",
            gate_passed=False,
            gate_reason="risk/reward below threshold",
            gate_checks=[
                GateCheck(name="risk_reward", passed=False, detail="risk/reward below threshold")
            ],
        )
        readiness = compute_trade_readiness(scan, _sample_decision(recommended_action="blocked"))
        self.assertTrue(readiness.reason.startswith("Blocked:"))
        self.assertIn("0.6 multiplier", " ".join(readiness.reasons))

    def test_penalizes_provider_degraded_without_zeroing(self) -> None:
        healthy = compute_trade_readiness(_base_scan(), _sample_decision())
        degraded = compute_trade_readiness(
            _base_scan(provider_status="degraded"),
            _sample_decision(provider_status="degraded"),
        )
        self.assertGreater(degraded.score, 0)
        self.assertLess(degraded.score, healthy.score)
        self.assertEqual(degraded.projection, "decaying")

    def test_produces_low_readiness_for_provider_critical(self) -> None:
        readiness = compute_trade_readiness(
            _base_scan(provider_status="critical", recommended_action="preview"),
            _sample_decision(),
        )
        self.assertLess(readiness.score, 40)
        self.assertIn("provider", readiness.reason.lower())

    def test_penalizes_stale_bars(self) -> None:
        readiness = compute_trade_readiness(
            _base_scan(bar_age_minutes=200.0, recommended_action="preview"),
            _sample_decision(),
        )
        self.assertLessEqual(readiness.score, 30)
        self.assertRegex(readiness.reason.lower(), r"stale|bars")

    def test_hard_stops_provider_critical_when_bars_stale_over_six_hours(self) -> None:
        readiness = compute_trade_readiness(
            _base_scan(provider_status="critical", bar_age_minutes=361.0),
            _sample_decision(provider_status="critical", bar_age_minutes=361.0),
        )
        self.assertEqual(readiness.score, 0)
        self.assertTrue(readiness.hard_stop)

    def test_hard_stops_missing_or_invalid_price(self) -> None:
        self.assertEqual(compute_trade_readiness(_base_scan(price=0.0), _sample_decision()).score, 0)
        self.assertEqual(
            compute_trade_readiness(_base_scan(price=float("nan")), _sample_decision()).score,
            0,
        )

    def test_returns_required_factors_and_projection(self) -> None:
        readiness = compute_trade_readiness(_base_scan(), _sample_decision())
        self.assertEqual(
            [factor.key for factor in readiness.factors],
            [
                "signal_confidence",
                "actionability",
                "gate_status",
                "provider_health",
                "freshness",
                "risk_setup",
            ],
        )
        self.assertEqual(readiness.band, readiness.tone)
        self.assertGreater(len(readiness.reasons), 0)
        self.assertEqual(readiness.projection, "stable")

    def test_hard_stops_kill_switch(self) -> None:
        automation = AutomationReadinessContext(kill_switch_enabled=True)
        readiness = compute_trade_readiness(_base_scan(), _sample_decision(), automation=automation)
        self.assertIn("kill switch", readiness.reason.lower())
        self.assertEqual(readiness.score, 0)
        self.assertTrue(readiness.hard_stop)
        self.assertEqual(readiness.projection, "kill_switch_or_breaker")

    def test_hard_stops_open_breaker(self) -> None:
        automation = AutomationReadinessContext(breaker_state="open")
        readiness = compute_trade_readiness(_base_scan(), _sample_decision(), automation=automation)
        self.assertEqual(readiness.score, 0)
        self.assertIn("breaker", readiness.reason.lower())

    def test_prefers_freshest_confidence_source_by_timestamp(self) -> None:
        stale_scan = _base_scan(
            calibrated_confidence=90.0,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        fresh_decision = _sample_decision(
            confidence=62.0,
            last_updated=datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
        )
        readiness = compute_trade_readiness(stale_scan, fresh_decision)
        self.assertEqual(readiness.base_score, 62)
        self.assertEqual(readiness.factors[0].bucket, "market")

    def test_fresh_bar_max_minutes_matches_frontend(self) -> None:
        self.assertEqual(FRESH_BAR_MAX_MINUTES, 45)


if __name__ == "__main__":
    unittest.main()
