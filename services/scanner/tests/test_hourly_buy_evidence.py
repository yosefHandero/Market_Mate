from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.brain.policies.hybrid import HYBRID_POLICY_ID, HYBRID_POLICY_VERSION
from app.config import Settings
from app.core.scoring import SCORING_VERSION
from app.db import Base
from app.models.scan import PredictionSnapshotORM, SignalOutcomeORM, StrategyReplayRunORM
import app.services.repository as repository_module
from app.services.hourly_buy_evidence import replay_identity
from app.services.repository import ScanRepository
from app.services.risk import RiskService
from app.services.scanner import ScannerService


class HourlyBuyEvidenceTests(unittest.TestCase):
    as_of = datetime(2026, 11, 6, 20, tzinfo=timezone.utc)

    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.session_local = sessionmaker(bind=engine)
        self.enterContext(patch.object(repository_module, "SessionLocal", self.session_local))
        self.repo = ScanRepository()
        self.repo.settings = Settings(_env_file=None, trade_gate_horizon="1h", weekly_out_of_sample_holdout_ratio=0)

    def save_live(self, session, *, days, index, change, **overrides):
        generated = self.as_of - timedelta(days=days, minutes=index)
        values = {
            "run_id": f"{days}-{index}", "ticker": "AAPL", "asset_type": "stock",
            "strategy_variant": self.repo.settings.scanner_strategy_variant,
            "signal": "BUY", "confidence": 65.0, "raw_score": 65.0, "score_band": "60-69",
            "scoring_version": SCORING_VERSION, "entry_price": 100.0,
            "generated_at": generated, "price_after_1h": 100.0 + change,
            "status_1h": "resolved", "evaluated_at_1h": generated + timedelta(hours=1),
            "sample_source": "live_paper_forward",
        }
        snapshot = overrides.pop("snapshot", True)
        policy = overrides.pop("policy", HYBRID_POLICY_VERSION)
        values.update(overrides)
        session.add(SignalOutcomeORM(**values))
        if snapshot:
            session.add(PredictionSnapshotORM(
                run_id=values["run_id"], ticker=values["ticker"], asset_type=values["asset_type"],
                signal=values["signal"], entry_price=100.0, range_low=99.0, range_high=101.0,
                horizon="1w", generated_at=values["generated_at"],
                sample_source=values["sample_source"], decision_role="production",
                policy_id=HYBRID_POLICY_ID, policy_version=policy,
            ))

    def gate(self, asset_type="stock"):
        return self.repo.evaluate_signal_gate(
            asset_type=asset_type, signal="BUY", score_band="60-69", horizon="1h", observed_at=self.as_of,
        )

    def test_newest_compatible_rows_fill_only_the_shortfall_and_poor_evidence_fails(self):
        with self.session_local.begin() as session:
            for index in range(10):
                self.save_live(session, days=2, index=index, change=-0.25)
                self.save_live(session, days=15, index=index, change=-0.25)
                self.save_live(session, days=20, index=index, change=50.0)
        gate = self.gate()
        self.assertEqual((gate.signal_count, gate.signal_win_rate, gate.signal_avg_return), (20, 0.0, -0.25))
        self.assertEqual([check.name for check in gate.checks if not check.passed], [
            "win_rate", "avg_return", "score_band_win_rate", "score_band_avg_return",
        ])
        self.assertFalse(gate.passed)
        sources = next(check.detail for check in gate.checks if check.name == "evidence_sources")
        self.assertIn("Recent completed 10", sources)
        self.assertIn("Historical completed 10", sources)
        self.assertIn("Historical replay 0", sources)

    def test_rejects_holdouts_unknown_provenance_duplicates_invalid_and_future_resolutions(self):
        with self.session_local.begin() as session:
            self.save_live(session, days=2, index=1, change=0.2)
            self.save_live(session, days=2, index=1, change=0.2, run_id="duplicate")
            self.save_live(session, days=3, index=1, change=50.0, sample_source="live_holdout")
            self.save_live(session, days=3, index=2, change=50.0, sample_source="out_of_sample")
            self.save_live(session, days=3, index=3, change=50.0, sample_source="unknown")
            self.save_live(session, days=3, index=4, change=50.0, snapshot=False)
            self.save_live(session, days=3, index=5, change=50.0, policy="hybrid-v4.2")
            self.save_live(session, days=3, index=6, change=50.0, scoring_version="old-engine")
            self.save_live(session, days=3, index=7, change=50.0, strategy_variant="other")
            self.save_live(session, days=3, index=8, change=50.0, status_1h="pending")
            self.save_live(session, days=3, index=9, change=50.0, price_after_1h=None, price_after_1w=150.0)
            self.save_live(session, days=3, index=10, change=50.0, price_after_1h=float("inf"))
            self.save_live(session, days=3, index=11, change=50.0, evaluated_at_1h=self.as_of + timedelta(minutes=1))
            self.save_live(session, days=91, index=1, change=50.0)
        gate = self.gate()
        self.assertEqual((gate.signal_count, gate.signal_win_rate, gate.signal_avg_return), (1, 100.0, 0.2))
        self.assertFalse(gate.passed)

    def test_recent_samples_are_kept_in_full_and_supplemental_sources_are_not_opened(self):
        with self.session_local.begin() as session:
            for index in range(22):
                self.save_live(session, days=2, index=index, change=-0.25)
            self.save_live(session, days=16, index=0, change=50.0)
        with patch("app.services.hourly_buy_evidence._replay_rows") as replay:
            gate = self.gate()
        replay.assert_not_called()
        self.assertEqual((gate.signal_count, gate.signal_avg_return), (22, -0.25))

    def test_replay_fills_last_and_respects_availability_holdout_horizon_and_duplicate_rules(self):
        def replay_row(days, *, change, ticker="AAPL", **overrides):
            observed = self.as_of - timedelta(days=days)
            row = {
                "symbol": ticker, "observed_at": observed.isoformat(),
                "future_price_at": (observed + timedelta(hours=1, minutes=5)).isoformat(),
                "strategy_variant": self.repo.settings.scanner_strategy_variant,
                "horizon": "1h", "signal": "BUY", "asset_type": "stock", "provider_status": "ok",
                "entry_price": 100.0, "future_price": 100.0 + change, "raw_score": 65.0,
            }
            row.update(overrides)
            return row

        def replay_run(run_id, rows, *, created_at=None, **overrides):
            request = {
                "replay_mode": "intraday", "sample_source": "backfilled_replay", "persist_outcomes": True,
                "horizon": "1h", "hourly_buy_evidence": replay_identity(self.repo.settings),
                "start": (self.as_of - timedelta(days=14)).isoformat(),
                "end": (self.as_of - timedelta(days=1)).isoformat(), "symbols": ["AAPL", "MSFT"],
            }
            request.update(overrides)
            return StrategyReplayRunORM(
                replay_id=run_id, created_at=created_at or self.as_of - timedelta(minutes=5),
                request_json=json.dumps(request), response_json=json.dumps({"rows": rows}),
            )

        with self.session_local.begin() as session:
            for index in range(18):
                self.save_live(session, days=4, index=index, change=-0.25)
            self.save_live(session, days=15, index=0, change=-0.25)
            self.save_live(session, days=2, index=0, change=50.0, ticker="MSFT", sample_source="live_holdout")
            session.add_all([
                replay_run("approved", [
                    replay_row(2, change=50, ticker="MSFT"),
                    replay_row(2, change=50, horizon="1w"),
                    replay_row(2, change=50, future_price_at=self.as_of.isoformat()),
                    replay_row(2, change=50, future_price_at=(self.as_of - timedelta(days=2)).isoformat()),
                    replay_row(4, change=50),  # Same event as the saved live row.
                    replay_row(5, change=-0.25),
                    replay_row(6, change=50),
                ]),
                replay_run("future", [replay_row(2, change=50)], created_at=self.as_of + timedelta(minutes=1)),
                replay_run("holdout", [replay_row(2, change=50)], sample_source="out_of_sample"),
                replay_run("legacy", [replay_row(2, change=50)], hourly_buy_evidence=None),
            ])
        gate = self.gate()
        self.assertEqual((gate.signal_count, gate.signal_win_rate, gate.signal_avg_return), (20, 0.0, -0.25))
        self.assertEqual(gate.evidence_basis, "hourly_buy_mixed_historical")
        self.assertIsNone(gate.real_money_trust_blocked)
        sources = next(check.detail for check in gate.checks if check.name == "evidence_sources")
        self.assertIn("Historical completed 1", sources)
        self.assertIn("Historical replay 1 (2026-11-01T20:00:00Z", sources)

    def test_scanner_and_order_use_identical_evidence_at_the_saved_cutoff(self):
        with self.session_local.begin() as session:
            for index in range(10):
                self.save_live(session, days=2, index=index, change=-0.25)
                self.save_live(session, days=15, index=index, change=-0.25)
            self.save_live(session, days=3, index=0, change=50.0,
                           evaluated_at_1h=self.as_of + timedelta(minutes=1))
        scanner = ScannerService()
        scanner.repo = self.repo
        scanner.settings = self.repo.settings
        confidence, source, passed, reason, checks, _ = scanner._gate_signal(
            asset_type="stock", signal=SimpleNamespace(decision_signal="BUY", score=65.0), observed_at=self.as_of,
        )
        risk = RiskService(self.repo)
        risk.settings = self.repo.settings
        context = SimpleNamespace(
            signal="BUY", raw_score=65.0, score_band="60-69", calibrated_confidence=confidence,
            calibration_source=source, signal_generated_at=self.as_of, gate_passed=passed, gate_reason=reason,
            gate_evaluation_mode="scan_time_window_locked", signal_outcome_id=None, run_id="candidate",
        )
        with patch.object(self.repo, "get_latest_signal_context", return_value=context), \
             patch.object(self.repo, "get_latest_run_timestamp", return_value=self.as_of), \
             patch("app.services.risk.datetime", wraps=datetime) as clock:
            clock.now.return_value = self.as_of + timedelta(minutes=2)
            order = risk.evaluate_trade(ticker="AAPL", side="buy", qty=1, latest_price=100)
        self.assertFalse(passed)
        self.assertFalse(order.allowed)
        self.assertTrue(next(check.passed for check in order.gate_checks if check.name == "signal_gate_consistency"))
        self.assertEqual({check.name: check for check in checks}, {
            check.name: check for check in order.gate_checks if check.name in {item.name for item in checks}
        })
        self.assertEqual((order.signal_evaluated_count, order.signal_avg_return), (20, -0.25))
