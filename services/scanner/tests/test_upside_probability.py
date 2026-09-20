import unittest

from app.brain.probability import compute_upside_probability


class UpsideProbabilityTests(unittest.TestCase):
    def test_none_for_non_bullish(self) -> None:
        self.assertIsNone(
            compute_upside_probability(
                hit_rate_pct=90.0, sample_size=100, directional_bias="bearish", shrinkage_k=20.0
            )
        )
        self.assertIsNone(
            compute_upside_probability(
                hit_rate_pct=90.0, sample_size=100, directional_bias="neutral", shrinkage_k=20.0
            )
        )

    def test_no_samples_returns_neutral_prior(self) -> None:
        self.assertEqual(
            compute_upside_probability(
                hit_rate_pct=None, sample_size=0, directional_bias="bullish", shrinkage_k=20.0
            ),
            50.0,
        )

    def test_thin_sample_shrinks_toward_fifty(self) -> None:
        thin = compute_upside_probability(
            hit_rate_pct=90.0, sample_size=2, directional_bias="bullish", shrinkage_k=20.0
        )
        thick = compute_upside_probability(
            hit_rate_pct=90.0, sample_size=200, directional_bias="bullish", shrinkage_k=20.0
        )
        assert thin is not None and thick is not None
        self.assertLess(thin, thick)
        self.assertLess(abs(thin - 50.0), abs(thick - 50.0))
        self.assertGreater(thick, 80.0)

    def test_clamped_to_unit_range(self) -> None:
        high = compute_upside_probability(
            hit_rate_pct=100.0, sample_size=10_000, directional_bias="bullish", shrinkage_k=20.0
        )
        low = compute_upside_probability(
            hit_rate_pct=0.0, sample_size=10_000, directional_bias="bullish", shrinkage_k=20.0
        )
        assert high is not None and low is not None
        self.assertLessEqual(high, 100.0)
        self.assertGreaterEqual(low, 0.0)

    def test_regime_adjustments_shift_probability(self) -> None:
        base = compute_upside_probability(
            hit_rate_pct=70.0,
            sample_size=100,
            directional_bias="bullish",
            shrinkage_k=20.0,
        )
        strong = compute_upside_probability(
            hit_rate_pct=70.0,
            sample_size=100,
            directional_bias="bullish",
            shrinkage_k=20.0,
            trend_strength_pct=5.0,
            relative_strength_pct=3.0,
        )
        weak = compute_upside_probability(
            hit_rate_pct=70.0,
            sample_size=100,
            directional_bias="bullish",
            shrinkage_k=20.0,
            trend_strength_pct=-5.0,
            relative_strength_pct=-3.0,
        )
        assert base is not None and strong is not None and weak is not None
        self.assertGreater(strong, base)
        self.assertLess(weak, base)


if __name__ == "__main__":
    unittest.main()
