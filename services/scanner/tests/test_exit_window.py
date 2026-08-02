import unittest

from app.core.decision_presentation import build_exit_window
from app.core.structural_prediction import build_structural_prediction
from app.schemas import WeeklyPatternPrediction


def _weekly(**overrides) -> WeeklyPatternPrediction:
    base = dict(
        pattern_name="breakout_20d_high",
        directional_bias="bullish",
        range_low=97.0,
        range_high=110.0,
        upside_probability_pct=64.0,
        sample_size=40,
        evidence_basis="historical_only",
        data_quality="ok",
    )
    base.update(overrides)
    return WeeklyPatternPrediction(**base)


class ExitWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.price_prediction = build_structural_prediction(
            price=100.0,
            decision_signal="BUY",
            volatility_regime="normal",
            horizon="1w",
            asset_type="stock",
        )

    def test_buy_candidate_produces_exit_window(self) -> None:
        window = build_exit_window(
            price=100.0,
            weekly_prediction=_weekly(),
            price_prediction=self.price_prediction,
            decision_signal="BUY",
            evidence_quality="moderate",
            data_quality="ok",
            forward_days=7,
        )
        self.assertIsNotNone(window)
        assert window is not None
        self.assertIsNotNone(window.estimated_exit_price)
        self.assertIsNotNone(window.invalidation_level)
        self.assertEqual(window.projected_range_low, 97.0)
        self.assertEqual(window.projected_range_high, 110.0)
        self.assertTrue(window.stop_growing_conditions)

    def test_exit_point_capped_by_structural_target(self) -> None:
        window = build_exit_window(
            price=100.0,
            weekly_prediction=_weekly(range_high=110.0),
            price_prediction=self.price_prediction,
            decision_signal="BUY",
            evidence_quality="moderate",
            data_quality="ok",
        )
        assert window is not None
        # structural target for 1w/normal ~= 102; capped exit is the lower (more conservative) of the two.
        self.assertLessEqual(window.estimated_exit_price, 110.0)
        self.assertGreater(window.estimated_exit_price, 100.0)

    def test_invalidation_below_entry(self) -> None:
        window = build_exit_window(
            price=100.0,
            weekly_prediction=_weekly(),
            price_prediction=self.price_prediction,
            decision_signal="BUY",
            evidence_quality="moderate",
            data_quality="ok",
        )
        assert window is not None
        self.assertLess(window.invalidation_level, 100.0)

    def test_non_buy_returns_none(self) -> None:
        window = build_exit_window(
            price=100.0,
            weekly_prediction=None,
            price_prediction=self.price_prediction,
            decision_signal="HOLD",
            evidence_quality="low",
            data_quality="ok",
        )
        self.assertIsNone(window)

    def test_stale_data_surfaces_risk_warning(self) -> None:
        window = build_exit_window(
            price=100.0,
            weekly_prediction=_weekly(daily_bars_stale=True),
            price_prediction=self.price_prediction,
            decision_signal="BUY",
            evidence_quality="moderate",
            data_quality="low",
        )
        assert window is not None
        self.assertIn("stale", window.risk_warning.lower())

    def test_live_forward_confidence_note(self) -> None:
        window = build_exit_window(
            price=100.0,
            weekly_prediction=_weekly(evidence_basis="live_forward_proven"),
            price_prediction=self.price_prediction,
            decision_signal="BUY",
            evidence_quality="high",
            data_quality="ok",
        )
        assert window is not None
        self.assertIn("live", window.confidence_change_note.lower())


if __name__ == "__main__":
    unittest.main()
