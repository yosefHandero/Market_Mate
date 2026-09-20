"""Learned-input artifact identity and campaign pinning."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.learned_inputs as learned_inputs_module
from app.brain.calibration import ReliabilityBin, reliability_map_to_payload
from app.brain.identity import learned_artifact_identity
from app.brain.policies.weekly import weekly_learned_artifacts_payload
from app.brain.weekly_backtest import PatternBacktestStats
from app.config import Settings
from app.db import Base
from app.models.scan import EvidenceCampaignORM
from app.services.learned_inputs import LearnedInputService


class FakeRepository:
    def get_weekly_pattern_stats(self, **_kwargs):
        return PatternBacktestStats(
            pattern_name="uptrend_ma_stack",
            sample_size=999,
            hit_rate_pct=99.0,
            avg_forward_return_pct=9.9,
        )


class FakeWalkForwardRepository:
    def get_latest_run(self):
        return SimpleNamespace(
            run_id="wf-current",
            config_fingerprint="current-config",
            engine_version="wf-engine-current",
            metrics_json=json.dumps(
                {
                    "reliability_maps": {
                        "stock": [
                            {
                                "low": 50.0,
                                "high": 100.0,
                                "realized_rate_pct": 99.0,
                                "count": 999,
                            }
                        ]
                    }
                }
            ),
        )


class LearnedInputPinningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        database_path = Path(self.temp_dir.name) / "learned-inputs.db"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        self.addCleanup(self.engine.dispose)
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        Base.metadata.create_all(self.engine)

    def test_active_campaign_pin_wins_over_latest_refresh_sources(self) -> None:
        pinned_maps = {
            "stock": [
                ReliabilityBin(low=50.0, high=100.0, realized_rate_pct=61.0, count=41)
            ]
        }
        pinned_stats = {
            ("uptrend_ma_stack", "stock", "historical"): PatternBacktestStats(
                pattern_name="uptrend_ma_stack",
                sample_size=41,
                hit_rate_pct=61.0,
                avg_forward_return_pct=1.1,
            )
        }
        pinned_identity = learned_artifact_identity(
            artifact_type="weekly_probability_inputs",
            content_payload=weekly_learned_artifacts_payload(
                reliability_maps=pinned_maps,
                extra_stats=pinned_stats,
            ),
            reference_payload={"run_id": "wf-pinned"},
        )
        with self.SessionLocal.begin() as session:
            session.add(
                EvidenceCampaignORM(
                    campaign_id="camp-pinned",
                    started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    status="active",
                    strategy_id="scanner-directional",
                    strategy_version="test",
                    feature_version="test",
                    config_fingerprint="config",
                    code_commit="commit",
                    learned_artifacts_fingerprint=pinned_identity["content_hash"],
                    learned_artifacts_json=json.dumps(pinned_identity, sort_keys=True),
                )
            )

        service = LearnedInputService(
            settings=Settings(_env_file=None),
            repository=FakeRepository(),  # type: ignore[arg-type]
            walk_forward_repository=FakeWalkForwardRepository(),  # type: ignore[arg-type]
            session_factory=self.SessionLocal,
        )
        with patch.object(learned_inputs_module, "engine", self.engine):
            bundle = service.load_for_serving()

        self.assertEqual(bundle.fingerprint, pinned_identity["content_hash"])
        self.assertEqual(
            reliability_map_to_payload(bundle.reliability_maps["stock"]),
            reliability_map_to_payload(pinned_maps["stock"]),
        )
        self.assertEqual(
            bundle.extra_stats[("uptrend_ma_stack", "stock", "historical")].sample_size,
            41,
        )


if __name__ == "__main__":
    unittest.main()
