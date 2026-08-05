import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import Base
from app.models.scan import EvidenceCampaignORM
from app.services.evidence_campaign import (
    _FINGERPRINT_SETTING_KEYS,
    EvidenceCampaignService,
    campaign_config_fingerprint,
)


# Behavior knobs added in Phase B1. Each must change the fingerprint when mutated.
_B1_BEHAVIOR_SETTING_KEYS = (
    "scanner_strategy_variant",
    "top_pick_limit",
    "upside_prob_shrinkage_k",
    "health_max_stale_minutes",
    "provider_max_bar_age_minutes",
    "weekly_apply_calibration_map",
    "weekly_apply_proof_candidate_filters",
    "weekly_forward_tolerance_days",
    "weekly_hold_return_tolerance_pct",
    "weekly_daily_lookback_bars_min",
    "weekly_daily_lookback_bars_preferred",
    "weekly_daily_lookback_bars_max",
    "weekly_daily_bar_max_age_days_stock",
    "weekly_daily_bar_max_age_days_crypto",
    "weekly_trust_window_days",
    "trust_recent_window_days",
    "calibration_min_signal_samples",
    "calibration_min_score_band_samples",
    "validation_win_threshold_pct",
    "validation_false_positive_threshold_pct",
    "weekly_out_of_sample_holdout_ratio",
    "track_hold_outcomes",
    "weekly_pattern_gate_min_historical_samples",
    "weekly_pattern_gate_min_backfilled_samples",
    "weekly_pattern_gate_min_live_forward_samples",
    "weekly_pattern_gate_min_out_of_sample_samples",
    "weekly_pattern_gate_min_win_rate",
    "weekly_pattern_gate_min_avg_return",
    "proof_step_days",
    "proof_momentum_lookback_days",
    "proof_min_expected_value_pct",
    "proof_rsi_overbought",
    "proof_min_pattern_samples",
    "proof_min_pattern_edge_pct",
    "proof_require_buy_hold_baseline",
    "proof_volume_lookback_days",
    "proof_min_volume_median_ratio",
)

# Provider overlays audited as live identity knobs (score/confidence/ranking).
_B1_PROVIDER_OVERLAY_SETTING_KEYS = (
    "news_trigger_abs_move_pct",
    "sec_enhanced_enabled",
    "marketdata_options_enabled",
    "binance_enabled",
    "deribit_enabled",
    "fred_enabled",
    "internal_breadth_enabled",
    "defillama_enabled",
)

# Operational / walk-forward-admin knobs that must NOT enter the live fingerprint.
_OPERATIONAL_ONLY_SETTING_KEYS = (
    "log_level",
    "scan_interval_seconds",
    "scan_concurrency_limit",
    "provider_retry_attempts",
    "provider_retry_backoff_seconds",
    "scheduler_enabled",
    "scheduler_poll_seconds",
    "admin_api_token",
    "read_api_token",
    "public_read_access_enabled",
    "cors_allowed_origins",
    "weekly_daily_bar_cache_ttl_seconds",
    "live_forward_max_scan_gap_minutes",
    "paper_loop_enabled",
    "proof_target_years",
    "proof_holdout_months",
    "proof_validation_months",
    "proof_pilot_min_predictions_per_asset",
    "proof_atr_lookback_days",
    "proof_confidence_shrinkage_k",
    "proof_top_n_per_asset",
)


def _mutated_value(settings, key: str):
    current = getattr(settings, key)
    if isinstance(current, bool):
        return not current
    if isinstance(current, int):
        return current + 1
    if isinstance(current, float):
        return current + 1.0
    if isinstance(current, str):
        return f"{current}-mutated"
    raise AssertionError(f"unsupported fingerprint setting type for {key}: {type(current)!r}")


class EvidenceCampaignServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        database_path = Path(self._temp_dir.name) / "scanner.db"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        Base.metadata.create_all(self.engine)
        # Dispose the engine before the temp dir is removed so Windows releases the
        # SQLite file handle (addCleanup is LIFO, so this runs before cleanup()).
        self.addCleanup(self.engine.dispose)
        self.settings = get_settings().model_copy(deep=True)

    def _service(self) -> EvidenceCampaignService:
        return EvidenceCampaignService(
            settings=self.settings, session_factory=self.SessionLocal
        )

    def _campaign_count(self) -> int:
        with self.SessionLocal() as session:
            return len(session.execute(select(EvidenceCampaignORM)).scalars().all())

    def test_creates_single_active_campaign_and_reuses_it(self) -> None:
        service = self._service()
        first = service.get_or_create_active_campaign()
        second = service.get_or_create_active_campaign()

        self.assertEqual(first.campaign_id, second.campaign_id)
        self.assertEqual(self._campaign_count(), 1)
        self.assertTrue(first.config_fingerprint)
        self.assertTrue(first.campaign_id.startswith("camp-"))

    def test_evidence_relevant_change_rotates_campaign(self) -> None:
        service = self._service()
        first = service.get_or_create_active_campaign()

        # Mutate an evidence-relevant setting -> fingerprint changes -> rotation.
        self.settings.signal_buy_threshold = self.settings.signal_buy_threshold + 5.0
        rotated = self._service().get_or_create_active_campaign()

        self.assertNotEqual(first.campaign_id, rotated.campaign_id)
        self.assertNotEqual(first.config_fingerprint, rotated.config_fingerprint)
        self.assertEqual(self._campaign_count(), 2)

        with self.SessionLocal() as session:
            rows = session.execute(select(EvidenceCampaignORM)).scalars().all()
            statuses = {row.campaign_id: (row.status, row.close_reason) for row in rows}
        self.assertEqual(statuses[first.campaign_id], ("closed", "config_change"))
        self.assertEqual(statuses[rotated.campaign_id][0], "active")

    def test_fingerprint_is_stable_for_same_settings(self) -> None:
        self.assertEqual(
            campaign_config_fingerprint(self.settings),
            campaign_config_fingerprint(self.settings.model_copy(deep=True)),
        )

    def test_b1_behavior_keys_are_fingerprinted(self) -> None:
        missing = [key for key in _B1_BEHAVIOR_SETTING_KEYS if key not in _FINGERPRINT_SETTING_KEYS]
        self.assertEqual(missing, [])

    def test_each_b1_behavior_knob_changes_fingerprint(self) -> None:
        baseline = campaign_config_fingerprint(self.settings)
        for key in _B1_BEHAVIOR_SETTING_KEYS:
            mutated = self.settings.model_copy(deep=True)
            setattr(mutated, key, _mutated_value(mutated, key))
            fingerprint = campaign_config_fingerprint(mutated)
            self.assertNotEqual(
                baseline,
                fingerprint,
                msg=f"expected fingerprint change when mutating {key}",
            )

    def test_provider_overlay_keys_are_fingerprinted(self) -> None:
        missing = [
            key for key in _B1_PROVIDER_OVERLAY_SETTING_KEYS if key not in _FINGERPRINT_SETTING_KEYS
        ]
        self.assertEqual(missing, [])

    def test_each_provider_overlay_knob_changes_fingerprint(self) -> None:
        baseline = campaign_config_fingerprint(self.settings)
        for key in _B1_PROVIDER_OVERLAY_SETTING_KEYS:
            mutated = self.settings.model_copy(deep=True)
            setattr(mutated, key, _mutated_value(mutated, key))
            fingerprint = campaign_config_fingerprint(mutated)
            self.assertNotEqual(
                baseline,
                fingerprint,
                msg=f"expected fingerprint change when mutating overlay {key}",
            )

    def test_operational_only_settings_do_not_change_fingerprint(self) -> None:
        baseline = campaign_config_fingerprint(self.settings)
        for key in _OPERATIONAL_ONLY_SETTING_KEYS:
            self.assertNotIn(key, _FINGERPRINT_SETTING_KEYS)
            mutated = self.settings.model_copy(deep=True)
            setattr(mutated, key, _mutated_value(mutated, key))
            self.assertEqual(
                baseline,
                campaign_config_fingerprint(mutated),
                msg=f"operational setting {key} must not change campaign fingerprint",
            )

    def test_new_behavior_fingerprint_change_opens_new_campaign(self) -> None:
        first = self._service().get_or_create_active_campaign()

        self.settings.scanner_strategy_variant = f"{self.settings.scanner_strategy_variant}-b1"
        self.settings.weekly_apply_calibration_map = not self.settings.weekly_apply_calibration_map
        rotated = self._service().get_or_create_active_campaign()

        self.assertNotEqual(first.campaign_id, rotated.campaign_id)
        self.assertNotEqual(first.config_fingerprint, rotated.config_fingerprint)
        self.assertEqual(self._campaign_count(), 2)

        with self.SessionLocal() as session:
            closed = session.execute(
                select(EvidenceCampaignORM).where(
                    EvidenceCampaignORM.campaign_id == first.campaign_id
                )
            ).scalar_one()
        self.assertEqual(closed.status, "closed")
        self.assertEqual(closed.close_reason, "config_change")


if __name__ == "__main__":
    unittest.main()
