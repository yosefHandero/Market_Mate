import unittest

from app.core.signals import map_score_to_decision_signal


class MapScoreToDecisionSignalTests(unittest.TestCase):
    def test_directional_buy_scores_take_priority(self) -> None:
        signal = map_score_to_decision_signal(
            score=72,
            price_change_pct=1.2,
            buy_score=72,
            sell_score=40,
            scoring_version="v2-directional",
        )
        self.assertEqual(signal, "BUY")

    def test_directional_sell_scores_do_not_fall_back_to_buy(self) -> None:
        signal = map_score_to_decision_signal(
            score=82,
            price_change_pct=-2.0,
            buy_score=18,
            sell_score=82,
            scoring_version="v2-directional",
        )
        self.assertEqual(signal, "SELL")

    def test_legacy_rows_still_use_score_fallback(self) -> None:
        self.assertEqual(
            map_score_to_decision_signal(score=80, price_change_pct=0.8),
            "BUY",
        )
        self.assertEqual(
            map_score_to_decision_signal(score=42, price_change_pct=-1.1),
            "SELL",
        )


if __name__ == "__main__":
    unittest.main()
