"""Decision identity vs ruler identity separation."""

from __future__ import annotations

import unittest

from app.brain.config import HybridPolicyConfig, RulerConfig, WeeklyPolicyConfig
from app.brain.calibration import ReliabilityBin
from app.brain.identity import (
    RULER_VERSION,
    decision_fingerprint,
    learned_artifact_identity,
    ruler_fingerprint,
    stable_content_hash,
)
from app.brain.policies import WeeklyProbabilityPolicy
from app.brain.policies.weekly import weekly_learned_artifacts_payload
from app.brain.weekly_backtest import PatternBacktestStats
from app.config import Settings


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


class DecisionFingerprintTest(unittest.TestCase):
    def test_stable_for_same_config(self) -> None:
        config = WeeklyPolicyConfig.from_settings(_settings())
        a = decision_fingerprint(
            policy_id="weekly_probability",
            policy_version="v1",
            config_payload=config.payload(),
        )
        b = decision_fingerprint(
            policy_id="weekly_probability",
            policy_version="v1",
            config_payload=WeeklyPolicyConfig.from_settings(_settings()).payload(),
        )
        self.assertEqual(a, b)

    def test_decision_relevant_setting_changes_fingerprint(self) -> None:
        base = WeeklyPolicyConfig.from_settings(_settings())
        changed = WeeklyPolicyConfig.from_settings(
            _settings(upside_prob_shrinkage_k=35.0)
        )
        self.assertNotEqual(
            decision_fingerprint(
                policy_id="weekly_probability",
                policy_version="v1",
                config_payload=base.payload(),
            ),
            decision_fingerprint(
                policy_id="weekly_probability",
                policy_version="v1",
                config_payload=changed.payload(),
            ),
        )

    def test_ruler_only_setting_does_not_change_decision_fingerprint(self) -> None:
        base = WeeklyPolicyConfig.from_settings(_settings())
        # proof_holdout_months only affects how evidence is judged, never what
        # decisions are produced, so the decision fingerprint must not move.
        changed = WeeklyPolicyConfig.from_settings(_settings(proof_holdout_months=12))
        self.assertEqual(base.payload(), changed.payload())

    def test_policies_have_distinct_fingerprints(self) -> None:
        settings = _settings()
        weekly = decision_fingerprint(
            policy_id="weekly_probability",
            policy_version="v1",
            config_payload=WeeklyPolicyConfig.from_settings(settings).payload(),
        )
        hybrid = decision_fingerprint(
            policy_id="hybrid_legacy",
            policy_version="v1",
            config_payload=HybridPolicyConfig.from_settings(settings).payload(),
        )
        self.assertNotEqual(weekly, hybrid)

    def test_learned_artifact_hash_is_content_stable(self) -> None:
        left = {
            "reliability_maps": {
                "stock": [
                    {"low": 60.0, "high": 80.0, "realized_rate_pct": 65.0, "count": 40}
                ]
            },
            "pattern_stats": [
                {
                    "pattern_name": "uptrend_ma_stack",
                    "asset_type": "stock",
                    "sample_source": "historical",
                    "sample_size": 45,
                    "hit_rate_pct": 62.0,
                    "avg_forward_return_pct": 1.2,
                }
            ],
        }
        right = {
            "pattern_stats": list(left["pattern_stats"]),
            "reliability_maps": dict(left["reliability_maps"]),
        }
        self.assertEqual(stable_content_hash(left), stable_content_hash(right))

    def test_learned_artifact_reference_does_not_move_content_identity(self) -> None:
        content = {"pattern_stats": [{"pattern_name": "uptrend_ma_stack", "sample_size": 45}]}
        first = learned_artifact_identity(
            artifact_type="weekly_probability_inputs",
            content_payload=content,
            reference_payload={"run_id": "wf-1", "created_at": "2026-01-01T00:00:00Z"},
        )
        second = learned_artifact_identity(
            artifact_type="weekly_probability_inputs",
            content_payload=content,
            reference_payload={"run_id": "wf-2", "created_at": "2026-02-01T00:00:00Z"},
        )
        self.assertEqual(first["content_hash"], second["content_hash"])

    def test_weekly_policy_fingerprint_includes_learned_inputs_without_changing_decision(self) -> None:
        config = WeeklyPolicyConfig(apply_proof_candidate_filters=False, apply_calibration_map=True)
        reliability = {
            "stock": [ReliabilityBin(low=50.0, high=100.0, realized_rate_pct=70.0, count=50)]
        }
        stats = {
            ("uptrend_ma_stack", "stock", "historical"): PatternBacktestStats(
                pattern_name="uptrend_ma_stack",
                sample_size=100,
                hit_rate_pct=64.0,
                avg_forward_return_pct=1.4,
            )
        }
        policy_a = WeeklyProbabilityPolicy(
            config=config,
            reliability_maps=reliability,
            extra_stats=stats,
        )
        policy_b = WeeklyProbabilityPolicy(
            config=config,
            reliability_maps={"stock": list(reversed(reliability["stock"]))},
            extra_stats=dict(reversed(list(stats.items()))),
        )
        changed = WeeklyProbabilityPolicy(
            config=config,
            reliability_maps={
                "stock": [ReliabilityBin(low=50.0, high=100.0, realized_rate_pct=71.0, count=50)]
            },
            extra_stats=stats,
        )

        self.assertEqual(policy_a.fingerprint(), policy_b.fingerprint())
        self.assertNotEqual(policy_a.fingerprint(), changed.fingerprint())
        self.assertEqual(
            policy_a.learned_artifacts_payload(),
            weekly_learned_artifacts_payload(
                reliability_maps=reliability,
                extra_stats=stats,
            ),
        )


class RulerFingerprintTest(unittest.TestCase):
    def test_ruler_fingerprint_tracks_ruler_config_only(self) -> None:
        base = RulerConfig.from_settings(_settings())
        judged_differently = RulerConfig.from_settings(_settings(proof_holdout_months=12))
        self.assertNotEqual(
            ruler_fingerprint(config_payload=base.payload()),
            ruler_fingerprint(config_payload=judged_differently.payload()),
        )

    def test_decision_only_setting_does_not_change_ruler_fingerprint(self) -> None:
        base = RulerConfig.from_settings(_settings())
        decision_changed = RulerConfig.from_settings(
            _settings(upside_prob_shrinkage_k=35.0)
        )
        self.assertEqual(
            ruler_fingerprint(config_payload=base.payload()),
            ruler_fingerprint(config_payload=decision_changed.payload()),
        )

    def test_ruler_version_changes_fingerprint(self) -> None:
        payload = RulerConfig.from_settings(_settings()).payload()
        self.assertNotEqual(
            ruler_fingerprint(config_payload=payload, ruler_version=RULER_VERSION),
            ruler_fingerprint(config_payload=payload, ruler_version="ruler-v999"),
        )


if __name__ == "__main__":
    unittest.main()
