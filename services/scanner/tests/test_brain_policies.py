"""Weekly-probability and hybrid policy behavior on the brain contracts.

The weekly policy must BUY only when a bullish pattern clears the abstention
floors (Wilson lower bound, EV after friction, data quality) and must ABSTAIN
with a machine-readable reason everywhere else. The hybrid wrap must map
precomputed session features onto BrainDecision without inventing anything.
Both are BUY-or-ABSTAIN only: SELL never exists as an action.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.brain.calibration import ReliabilityBin
from app.brain.config import HybridPolicyConfig, WeeklyPolicyConfig
from app.brain.contracts import MarketSnapshot, SymbolSnapshot
from app.brain.policies import HybridLegacyPolicy, WeeklyProbabilityPolicy
from app.brain.weekly_backtest import PatternBacktestStats
from app.brain.weekly_patterns import BULLISH_PATTERN_NAMES

START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bars(closes: list[float], start: datetime = START) -> list[dict]:
    return [
        {
            "t": (start + timedelta(days=index)).isoformat(),
            "o": close,
            "h": close * 1.01,
            "l": close * 0.99,
            "c": close,
            "v": 1000,
        }
        for index, close in enumerate(closes)
    ]


def _snapshot(
    closes: list[float],
    *,
    symbol: str = "AAPL",
    asset_type: str = "stock",
    data_quality: str = "ok",
    stale: bool = False,
) -> MarketSnapshot:
    as_of = START + timedelta(days=len(closes) - 1, hours=1)
    return MarketSnapshot(
        as_of=as_of,
        symbols=(
            SymbolSnapshot(
                symbol=symbol,
                asset_type=asset_type,  # type: ignore[arg-type]
                daily_bars=_bars(closes),
                data_quality=data_quality,
                daily_bars_stale=stale,
            ),
        ),
    )


def _uptrend(n: int = 420, daily_growth: float = 1.004) -> list[float]:
    return [100.0 * (daily_growth**index) for index in range(n)]


def _downtrend(n: int = 420, daily_decay: float = 0.996) -> list[float]:
    return [100.0 * (daily_decay**index) for index in range(n)]


def _policy(**config_overrides) -> WeeklyProbabilityPolicy:
    """Policy with quality filters and calibration map off, isolating the
    abstention floors (quality filters have their own tests)."""
    config = WeeklyPolicyConfig(
        apply_proof_candidate_filters=False,
        apply_calibration_map=False,
        **config_overrides,
    )
    return WeeklyProbabilityPolicy(config=config)


class WeeklyPolicyTests(unittest.TestCase):
    def test_insufficient_bars_abstains(self) -> None:
        decision = _policy().decide_all(_snapshot([100.0 + i for i in range(10)]))[0]
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertIn("insufficient_bars", decision.reasons)

    def test_bearish_trend_abstains_not_bullish(self) -> None:
        decision = _policy().decide_all(_snapshot(_downtrend()))[0]
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertIn("not_bullish", decision.reasons)

    def test_validated_uptrend_buys_with_probability_and_exit_plan(self) -> None:
        policy = _policy()
        decision = policy.decide_all(_snapshot(_uptrend()))[0]
        self.assertEqual(decision.action, "BUY")
        self.assertIsNotNone(decision.p_up_calibrated)
        self.assertGreater(decision.p_up_calibrated, 50.0)
        self.assertLessEqual(decision.p_up_calibrated, 100.0)
        self.assertIsNotNone(decision.expected_value_pct)
        self.assertGreater(decision.expected_value_pct, policy.config.min_ev_floor_pct)
        self.assertIsNotNone(decision.exit_plan)
        self.assertLess(decision.exit_plan.stop_price, decision.exit_plan.target_price)
        self.assertEqual(decision.decision_fingerprint, policy.fingerprint())
        self.assertGreater(decision.diagnostics["wilson_lb_pct"], 50.0)

    def test_wilson_floor_blocks_coin_flip_evidence(self) -> None:
        # Repository-accrued replay evidence with a large sample at a 50% hit
        # rate: the Wilson 95% lower bound sits below the 50% floor, so no BUY
        # regardless of how bullish the chart looks.
        coin_flip = {
            (pattern, "stock", "backfilled_replay"): PatternBacktestStats(
                pattern_name=pattern,
                sample_size=400,
                hit_rate_pct=50.0,
                avg_forward_return_pct=0.05,
            )
            for pattern in BULLISH_PATTERN_NAMES
        }
        policy = WeeklyProbabilityPolicy(
            config=WeeklyPolicyConfig(
                apply_proof_candidate_filters=False, apply_calibration_map=False
            ),
            extra_stats=coin_flip,
        )
        decision = policy.decide_all(_snapshot(_uptrend()))[0]
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertIn("wilson_lb_below_floor", decision.reasons)

    def test_live_and_holdout_stats_do_not_change_served_probability(self) -> None:
        clean_policy = WeeklyProbabilityPolicy(
            config=WeeklyPolicyConfig(
                apply_proof_candidate_filters=False, apply_calibration_map=False
            )
        )
        clean = clean_policy.decide_all(_snapshot(_uptrend()))[0]
        self.assertEqual(clean.action, "BUY")

        contaminated_stats = {}
        for pattern in BULLISH_PATTERN_NAMES:
            for source, hit_rate in (
                ("live_paper_forward", 99.0),
                ("out_of_sample", 1.0),
                ("live_holdout", 1.0),
            ):
                contaminated_stats[(pattern, "stock", source)] = PatternBacktestStats(
                    pattern_name=pattern,
                    sample_size=10_000,
                    hit_rate_pct=hit_rate,
                    avg_forward_return_pct=25.0,
                )
        contaminated_policy = WeeklyProbabilityPolicy(
            config=WeeklyPolicyConfig(
                apply_proof_candidate_filters=False, apply_calibration_map=False
            ),
            extra_stats=contaminated_stats,
        )
        contaminated = contaminated_policy.decide_all(_snapshot(_uptrend()))[0]

        self.assertEqual(contaminated.action, "BUY")
        self.assertEqual(contaminated.p_up_calibrated, clean.p_up_calibrated)
        self.assertEqual(contaminated.expected_value_pct, clean.expected_value_pct)
        self.assertIn(
            contaminated.evidence_basis.basis,
            {"historical_only", "mixed", "live_forward_proven"},
        )

    def test_ev_floor_blocks_marginal_edge(self) -> None:
        decision = _policy(min_ev_floor_pct=50.0).decide_all(_snapshot(_uptrend()))[0]
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertIn("expected_value_below_min", decision.reasons)

    def test_degraded_data_quality_abstains(self) -> None:
        decision = _policy().decide_all(
            _snapshot(_uptrend(), data_quality="degraded")
        )[0]
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertIn("data_quality_insufficient", decision.reasons)

    def test_stale_bars_abstain(self) -> None:
        decision = _policy().decide_all(_snapshot(_uptrend(), stale=True))[0]
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertIn("data_quality_insufficient", decision.reasons)

    def test_actions_are_buy_or_abstain_only(self) -> None:
        policy = _policy()
        for closes in (_uptrend(), _downtrend(), [100.0] * 120, [100.0 + i for i in range(10)]):
            for decision in policy.decide_all(_snapshot(closes)):
                self.assertIn(decision.action, ("BUY", "ABSTAIN"))

    def test_fingerprint_moves_with_decision_config(self) -> None:
        self.assertNotEqual(
            _policy().fingerprint(),
            _policy(shrinkage_k=35.0).fingerprint(),
        )

    def test_equivalent_learned_inputs_produce_identical_predictions(self) -> None:
        stats = {
            ("uptrend_ma_stack", "stock", "historical"): PatternBacktestStats(
                pattern_name="uptrend_ma_stack",
                sample_size=120,
                hit_rate_pct=63.0,
                avg_forward_return_pct=1.25,
            )
        }
        reliability = {
            "stock": [
                ReliabilityBin(low=0.0, high=50.0, realized_rate_pct=45.0, count=50),
                ReliabilityBin(low=50.0, high=100.0, realized_rate_pct=68.0, count=50),
            ]
        }
        first = WeeklyProbabilityPolicy(
            config=WeeklyPolicyConfig(apply_proof_candidate_filters=False),
            reliability_maps=reliability,
            extra_stats=stats,
        )
        second = WeeklyProbabilityPolicy(
            config=WeeklyPolicyConfig(apply_proof_candidate_filters=False),
            reliability_maps={"stock": list(reliability["stock"])},
            extra_stats=dict(stats),
        )

        self.assertEqual(
            first.decide_all(_snapshot(_uptrend())),
            second.decide_all(_snapshot(_uptrend())),
        )


def _hybrid_snapshot(session: dict) -> MarketSnapshot:
    return MarketSnapshot(
        as_of=START,
        symbols=(
            SymbolSnapshot(symbol="AAPL", asset_type="stock", session=session),
        ),
    )


class HybridPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = HybridLegacyPolicy(config=HybridPolicyConfig())

    def test_buy_session_maps_to_buy_decision(self) -> None:
        decision = self.policy.decide_all(
            _hybrid_snapshot(
                {
                    "decision_signal": "BUY",
                    "price": 200.0,
                    "calibrated_confidence": 71.5,
                    "target_price": 210.0,
                    "stop_price": 194.0,
                    "horizon_days": 7,
                    "pattern_name": "uptrend_ma_stack",
                }
            )
        )[0]
        self.assertEqual(decision.action, "BUY")
        self.assertEqual(decision.p_up_calibrated, 71.5)
        self.assertEqual(decision.exit_plan.target_price, 210.0)
        self.assertEqual(decision.exit_plan.stop_price, 194.0)
        self.assertEqual(decision.decision_fingerprint, self.policy.fingerprint())

    def test_hold_session_abstains(self) -> None:
        decision = self.policy.decide_all(
            _hybrid_snapshot({"decision_signal": "HOLD", "price": 200.0})
        )[0]
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertIn("not_buy_signal", decision.reasons)

    def test_sell_session_abstains_buy_only_product(self) -> None:
        decision = self.policy.decide_all(
            _hybrid_snapshot({"decision_signal": "SELL", "price": 200.0})
        )[0]
        self.assertEqual(decision.action, "ABSTAIN")

    def test_empty_session_abstains_with_reason(self) -> None:
        decision = self.policy.decide_all(_hybrid_snapshot({}))[0]
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertIn("insufficient_session_features", decision.reasons)

    def test_policies_carry_distinct_fingerprints(self) -> None:
        self.assertNotEqual(self.policy.fingerprint(), _policy().fingerprint())


if __name__ == "__main__":
    unittest.main()
