from __future__ import annotations

import unittest

from app.core.decision_presentation import build_decision_enrichment, build_top_reasons, evidence_grade_label
from app.core.structural_prediction import build_structural_prediction, evaluate_prediction_accuracy


class StructuralPredictionTests(unittest.TestCase):
    def test_buy_range_uses_stop_and_target_levels(self) -> None:
        prediction = build_structural_prediction(
            price=100.0,
            decision_signal="BUY",
            volatility_regime="normal",
            horizon="1h",
            asset_type="stock",
        )
        self.assertEqual(prediction.range_low, 99.0)
        self.assertEqual(prediction.range_high, 102.0)
        self.assertEqual(prediction.horizon, "1h")
        self.assertIn("below $99.00", prediction.invalidation)

    def test_hold_range_is_observation_only(self) -> None:
        prediction = build_structural_prediction(
            price=50.0,
            decision_signal="HOLD",
            volatility_regime="normal",
            horizon="1h",
            asset_type="crypto",
        )
        self.assertLess(prediction.range_low, 50.0)
        self.assertGreater(prediction.range_high, 50.0)
        self.assertIn("observation-only", prediction.invalidation)

    def test_evaluate_in_range_when_price_inside_band(self) -> None:
        verdict = evaluate_prediction_accuracy(
            decision_signal="BUY",
            range_low=99.0,
            range_high=102.0,
            price_at_horizon=100.5,
        )
        self.assertTrue(verdict.in_range)
        self.assertEqual(verdict.outcome, "in_range")


class DecisionPresentationTests(unittest.TestCase):
    def test_evidence_grade_mapping(self) -> None:
        self.assertEqual(evidence_grade_label("high"), "Strong")
        self.assertEqual(evidence_grade_label("moderate"), "Mixed")
        self.assertEqual(evidence_grade_label("low"), "Weak")

    def test_top_reasons_limited_to_three(self) -> None:
        reasons = build_top_reasons(
            directional_reasons=("above_vwap", "positive_momentum"),
            score_contributions={"momentum": 5.0, "volume": 2.0, "trend": 1.0, "alignment": 0.5},
            evidence_quality_reasons=("Gate passed",),
            explanation="Extra context.",
        )
        self.assertLessEqual(len(reasons), 3)
        self.assertTrue(any("Momentum" in reason for reason in reasons))

    def test_build_decision_enrichment_includes_prediction(self) -> None:
        enrichment = build_decision_enrichment(
            price=120.0,
            decision_signal="SELL",
            volatility_regime="elevated",
            horizon="1h",
            asset_type="stock",
            evidence_quality="moderate",
            directional_reasons=("below_vwap",),
            score_contributions={"structure": 4.0},
            evidence_quality_reasons=(),
            explanation="Pressure building.",
            gate_passed=True,
        )
        self.assertEqual(enrichment.evidence_grade, "Mixed")
        self.assertLessEqual(len(enrichment.top_reasons), 3)
        self.assertIsNotNone(enrichment.price_prediction)
        self.assertEqual(enrichment.price_prediction.horizon, "1h")


if __name__ == "__main__":
    unittest.main()
