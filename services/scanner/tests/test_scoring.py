import unittest

from app.core.scoring import SCORING_VERSION, TREND_SMA_WINDOW, TREND_SCALING_FACTOR, TREND_MAX_CONTRIBUTION, compute_directional_scores


def _bar_only_kwargs(**overrides):
    """Baseline bar-based inputs with neutral provider signals."""
    defaults = dict(
        relative_volume=1.0,
        price_change_pct=0.0,
        breakout_flag=False,
        breakdown_flag=False,
        above_vwap=False,
        close_to_high_pct=0.0,
        close_to_low_pct=0.0,
        sentiment_score=0.0,
        catalyst_score=0.0,
        market_status="neutral",
        relative_strength_pct=0.0,
        options_bullish_score=0.0,
        options_bearish_score=0.0,
        volatility_regime="normal",
        data_quality="ok",
        context_bias=0.0,
        trend_above_sma=True,
        trend_strength_pct=0.0,
    )
    defaults.update(overrides)
    return defaults


class ScoringVersionTests(unittest.TestCase):
    def test_scoring_version_is_v41_integrated(self) -> None:
        self.assertEqual(SCORING_VERSION, "v4.1-integrated")


class ProviderSignalIntegrationTests(unittest.TestCase):
    def test_neutral_providers_add_zero(self) -> None:
        result = compute_directional_scores(**_bar_only_kwargs())
        self.assertEqual(result.buy_contributions["signals"], 0.0)
        self.assertEqual(result.sell_contributions["signals"], 0.0)

    def test_contributions_dict_includes_signals_key(self) -> None:
        result = compute_directional_scores(**_bar_only_kwargs())
        self.assertIn("signals", result.buy_contributions)
        self.assertIn("signals", result.sell_contributions)
        self.assertIn("signals", result.selected_contributions)

    def test_provider_terms_bounded_at_max(self) -> None:
        result = compute_directional_scores(**_bar_only_kwargs(
            sentiment_score=1.0,
            catalyst_score=1.0,
            market_status="bullish",
            options_bullish_score=10.0,
            options_bearish_score=0.0,
        ))
        self.assertEqual(result.buy_contributions["signals"], 15.0)

    def test_sell_provider_terms_bounded(self) -> None:
        result = compute_directional_scores(**_bar_only_kwargs(
            sentiment_score=-1.0,
            catalyst_score=0.0,
            market_status="bearish",
            options_bullish_score=0.0,
            options_bearish_score=10.0,
        ))
        self.assertEqual(result.sell_contributions["signals"], 12.0)


class BorderlineFlipTests(unittest.TestCase):
    def test_borderline_hold_flips_to_buy_with_provider_support(self) -> None:
        """Bar-based buy_score ~49 (under 52 threshold). Provider signals push past it."""
        baseline = compute_directional_scores(**_bar_only_kwargs(
            price_change_pct=2.0,
            breakout_flag=True,
            above_vwap=True,
            close_to_high_pct=0.1,
            relative_strength_pct=1.8,
            relative_volume=1.0,
        ))
        self.assertEqual(baseline.decision_signal, "HOLD",
                         f"Baseline should be HOLD but got {baseline.decision_signal} "
                         f"(buy={baseline.buy_score}, sell={baseline.sell_score})")
        self.assertLess(baseline.buy_score, 52)

        boosted = compute_directional_scores(**_bar_only_kwargs(
            price_change_pct=2.0,
            breakout_flag=True,
            above_vwap=True,
            close_to_high_pct=0.1,
            relative_strength_pct=1.8,
            relative_volume=1.0,
            sentiment_score=0.8,
            market_status="bullish",
            options_bullish_score=8.0,
            options_bearish_score=1.0,
        ))
        self.assertEqual(boosted.decision_signal, "BUY",
                         f"Should flip to BUY with provider support "
                         f"(buy={boosted.buy_score}, sell={boosted.sell_score})")
        self.assertGreaterEqual(boosted.buy_score, 52)
        self.assertGreaterEqual(boosted.buy_score - boosted.sell_score, 6)

    def test_borderline_buy_suppressed_to_hold_by_opposing_signals(self) -> None:
        """Bar-based BUY with moderate margin. Opposing providers boost sell enough to collapse margin."""
        baseline = compute_directional_scores(**_bar_only_kwargs(
            price_change_pct=4.0,
            breakout_flag=True,
            breakdown_flag=True,
            above_vwap=False,
            close_to_high_pct=0.8,
            close_to_low_pct=1.0,
            relative_strength_pct=2.0,
            relative_volume=2.2,
        ))
        self.assertEqual(baseline.decision_signal, "BUY",
                         f"Baseline should be BUY but got {baseline.decision_signal} "
                         f"(buy={baseline.buy_score}, sell={baseline.sell_score})")

        suppressed = compute_directional_scores(**_bar_only_kwargs(
            price_change_pct=4.0,
            breakout_flag=True,
            breakdown_flag=True,
            above_vwap=False,
            close_to_high_pct=0.8,
            close_to_low_pct=1.0,
            relative_strength_pct=2.0,
            relative_volume=2.2,
            sentiment_score=-0.9,
            market_status="bearish",
            options_bullish_score=0.0,
            options_bearish_score=8.0,
        ))
        self.assertNotEqual(suppressed.decision_signal, "BUY",
                            f"Should be suppressed from BUY with opposing signals "
                            f"(buy={suppressed.buy_score}, sell={suppressed.sell_score}, "
                            f"margin={suppressed.score_margin})")
        self.assertLess(suppressed.score_margin, 6)

    def test_provider_reasons_appear_when_active(self) -> None:
        result = compute_directional_scores(**_bar_only_kwargs(
            price_change_pct=1.0,
            above_vwap=True,
            sentiment_score=0.5,
            catalyst_score=0.5,
            market_status="bullish",
            options_bullish_score=6.0,
            options_bearish_score=0.0,
        ))
        self.assertIn("positive_news_sentiment", result.buy_reasons)
        self.assertIn("sec_catalyst", result.buy_reasons)
        self.assertIn("bullish_regime", result.buy_reasons)
        self.assertIn("bullish_options_flow", result.buy_reasons)

    def test_sell_provider_reasons_appear(self) -> None:
        result = compute_directional_scores(**_bar_only_kwargs(
            price_change_pct=-1.0,
            above_vwap=False,
            sentiment_score=-0.5,
            market_status="bearish",
            options_bullish_score=0.0,
            options_bearish_score=6.0,
        ))
        self.assertIn("negative_news_sentiment", result.sell_reasons)
        self.assertIn("bearish_regime", result.sell_reasons)
        self.assertIn("bearish_options_flow", result.sell_reasons)


class TrendSignalTests(unittest.TestCase):
    def test_neutral_trend_adds_zero(self) -> None:
        result = compute_directional_scores(**_bar_only_kwargs())
        self.assertEqual(result.buy_contributions["trend"], 0.0)
        self.assertEqual(result.sell_contributions["trend"], 0.0)

    def test_bullish_trend_boosts_buy_score(self) -> None:
        result = compute_directional_scores(**_bar_only_kwargs(
            trend_above_sma=True,
            trend_strength_pct=2.0,
        ))
        expected = round(min(2.0 * TREND_SCALING_FACTOR, TREND_MAX_CONTRIBUTION), 2)
        self.assertEqual(result.buy_contributions["trend"], expected)
        self.assertEqual(result.sell_contributions["trend"], 0.0)

    def test_bearish_trend_boosts_sell_score(self) -> None:
        result = compute_directional_scores(**_bar_only_kwargs(
            trend_above_sma=False,
            trend_strength_pct=-3.0,
        ))
        expected = round(min(3.0 * TREND_SCALING_FACTOR, TREND_MAX_CONTRIBUTION), 2)
        self.assertEqual(result.sell_contributions["trend"], expected)
        self.assertEqual(result.buy_contributions["trend"], 0.0)

    def test_trend_contribution_capped_at_max(self) -> None:
        result = compute_directional_scores(**_bar_only_kwargs(
            trend_above_sma=True,
            trend_strength_pct=20.0,
        ))
        self.assertEqual(result.buy_contributions["trend"], TREND_MAX_CONTRIBUTION)

    def test_trend_above_sma_adds_buy_confirmation(self) -> None:
        with_trend = compute_directional_scores(**_bar_only_kwargs(trend_above_sma=True))
        without_trend = compute_directional_scores(**_bar_only_kwargs(trend_above_sma=False))
        self.assertGreater(with_trend.buy_confirmations, without_trend.buy_confirmations)

    def test_trend_below_sma_adds_sell_confirmation(self) -> None:
        with_trend = compute_directional_scores(**_bar_only_kwargs(trend_above_sma=False))
        without_trend = compute_directional_scores(**_bar_only_kwargs(trend_above_sma=True))
        self.assertGreater(with_trend.sell_confirmations, without_trend.sell_confirmations)

    def test_buy_reason_price_above_20sma(self) -> None:
        result = compute_directional_scores(**_bar_only_kwargs(
            trend_above_sma=True,
            trend_strength_pct=1.0,
        ))
        self.assertIn("price_above_20sma", result.buy_reasons)

    def test_sell_reason_price_below_20sma(self) -> None:
        result = compute_directional_scores(**_bar_only_kwargs(
            trend_above_sma=False,
            trend_strength_pct=-1.0,
        ))
        self.assertIn("price_below_20sma", result.sell_reasons)

    def test_no_reason_when_trend_near_neutral(self) -> None:
        result = compute_directional_scores(**_bar_only_kwargs(
            trend_above_sma=True,
            trend_strength_pct=0.3,
        ))
        self.assertNotIn("price_above_20sma", result.buy_reasons)

    def test_constants_are_tunable(self) -> None:
        self.assertEqual(TREND_SMA_WINDOW, 20)
        self.assertEqual(TREND_SCALING_FACTOR, 2.5)
        self.assertEqual(TREND_MAX_CONTRIBUTION, 12)


if __name__ == "__main__":
    unittest.main()
