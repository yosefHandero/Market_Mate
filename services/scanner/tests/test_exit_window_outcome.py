from __future__ import annotations

import unittest

from app.brain.structural_prediction import (
    PriceBar,
    evaluate_exit_window_outcome,
    evaluate_exit_window_outcome_with_disambiguation,
)


class ExitWindowOutcomeTests(unittest.TestCase):
    def test_exit_hit_protects_better_than_hold(self) -> None:
        outcome = evaluate_exit_window_outcome(
            entry_price=100.0,
            estimated_exit_price=105.0,
            invalidation_level=98.0,
            price_at_horizon=103.0,
            decision_signal="BUY",
            bars=[PriceBar(high=106.0, low=99.5)],
            friction_pct=0.07,
        )
        self.assertTrue(outcome.exit_hit)
        self.assertFalse(outcome.invalidation_hit)
        self.assertTrue(outcome.exit_window_helped)

    def test_invalidation_hit_when_stop_touched_first(self) -> None:
        outcome = evaluate_exit_window_outcome(
            entry_price=100.0,
            estimated_exit_price=105.0,
            invalidation_level=98.0,
            price_at_horizon=103.0,
            decision_signal="BUY",
            bars=[PriceBar(high=101.0, low=97.0)],
            friction_pct=0.07,
        )
        self.assertFalse(outcome.exit_hit)
        self.assertTrue(outcome.invalidation_hit)

    def test_conservative_same_bar_counts_against_exit(self) -> None:
        outcome = evaluate_exit_window_outcome(
            entry_price=100.0,
            estimated_exit_price=105.0,
            invalidation_level=98.0,
            price_at_horizon=103.0,
            decision_signal="BUY",
            bars=[PriceBar(high=106.0, low=97.0)],
            friction_pct=0.07,
        )
        self.assertTrue(outcome.invalidation_hit)
        self.assertFalse(outcome.exit_hit)
        # The resolving bar touched both levels -> flagged as a same-bar conflict.
        self.assertTrue(outcome.exit_conflict)

    def test_no_conflict_flag_on_clean_exit(self) -> None:
        outcome = evaluate_exit_window_outcome(
            entry_price=100.0,
            estimated_exit_price=105.0,
            invalidation_level=98.0,
            price_at_horizon=103.0,
            decision_signal="BUY",
            bars=[PriceBar(high=106.0, low=99.5)],
            friction_pct=0.07,
        )
        self.assertTrue(outcome.exit_hit)
        self.assertFalse(outcome.exit_conflict)

    def test_finer_bars_can_prove_exit_first(self) -> None:
        outcome = evaluate_exit_window_outcome_with_disambiguation(
            entry_price=100.0,
            estimated_exit_price=105.0,
            invalidation_level=98.0,
            price_at_horizon=103.0,
            decision_signal="BUY",
            bars=[PriceBar(high=106.0, low=97.0)],
            finer_bars_by_index={
                0: [
                    PriceBar(high=105.5, low=100.0),
                    PriceBar(high=104.0, low=97.5),
                ]
            },
            friction_pct=0.07,
        )
        self.assertTrue(outcome.exit_hit)
        self.assertFalse(outcome.invalidation_hit)
        # Daily bar was ambiguous even though finer bars resolved to exit.
        self.assertTrue(outcome.exit_conflict)

    def test_hold_when_neither_level_touched(self) -> None:
        outcome = evaluate_exit_window_outcome(
            entry_price=100.0,
            estimated_exit_price=105.0,
            invalidation_level=98.0,
            price_at_horizon=101.0,
            decision_signal="BUY",
            bars=[PriceBar(high=102.0, low=99.5)],
            friction_pct=0.07,
        )
        self.assertFalse(outcome.exit_hit)
        self.assertFalse(outcome.invalidation_hit)
        self.assertAlmostEqual(outcome.protected_return_pct or 0.0, 1.0, places=2)
        self.assertAlmostEqual(outcome.hold_return_pct or 0.0, 1.0, places=2)


if __name__ == "__main__":
    unittest.main()
