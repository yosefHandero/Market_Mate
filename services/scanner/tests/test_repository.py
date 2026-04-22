import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.repository as repository_module
from app.db import Base
from app.models.journal import JournalEntryORM
from app.models.scan import ExecutionAuditORM, SignalOutcomeORM
from app.schemas import SignalOutcomePerformanceBucket, SignalOutcomeSummary, ValidationBucket
from app.services.repository import ScanRepository


class RepositoryCalibrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = ScanRepository()

    def _outcome_row(
        self,
        *,
        signal: str,
        gate_passed: bool,
        asset_type: str,
        generated_at: datetime,
        price_after_15m: float,
        price_after_1h: float,
        price_after_1d: float,
        ticker: str = "AAPL",
        entry_price: float = 100.0,
        market_status: str = "neutral",
        data_grade: str = "research",
        calibrated_confidence: float = 65.0,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            signal=signal,
            gate_passed=gate_passed,
            asset_type=asset_type,
            ticker=ticker,
            generated_at=generated_at,
            entry_price=entry_price,
            confidence=65.0,
            calibrated_confidence=calibrated_confidence,
            raw_score=65.0,
            score_band="60-69",
            market_status=market_status,
            data_grade=data_grade,
            price_after_15m=price_after_15m,
            price_after_1h=price_after_1h,
            price_after_1d=price_after_1d,
        )

    def _bucket(
        self,
        key: str,
        *,
        count: int,
        win_rate: float | None,
        avg_return: float | None,
    ) -> SignalOutcomePerformanceBucket:
        return SignalOutcomePerformanceBucket(
            key=key,
            total_signals=count,
            evaluated_15m_count=0,
            evaluated_1h_count=count,
            evaluated_1d_count=0,
            win_rate_15m=None,
            avg_return_15m=None,
            win_rate_1h=win_rate,
            avg_return_1h=avg_return,
            win_rate_1d=None,
            avg_return_1d=None,
        )

    def test_calibration_waits_for_minimum_samples(self) -> None:
        summary = SignalOutcomeSummary(
            total_signals=9,
            pending_15m_count=0,
            pending_1h_count=0,
            pending_1d_count=0,
            overall=self._bucket("overall", count=9, win_rate=55.0, avg_return=0.1),
            by_signal=[self._bucket("BUY", count=19, win_rate=60.0, avg_return=0.2)],
            by_confidence_bucket=[],
            by_signal_confidence_bucket=[],
            by_signal_score_bucket=[self._bucket("BUY:60-69", count=9, win_rate=62.0, avg_return=0.22)],
        )

        calibrated, score_band, source = self.repo._calibrate_confidence(
            signal="BUY",
            raw_score=68.0,
            summary=summary,
            horizon="1h",
        )

        self.assertEqual(score_band, "60-69")
        self.assertEqual(calibrated, 68.0)
        self.assertEqual(source, "raw")

    def test_calibration_uses_signal_bucket_when_samples_are_mature(self) -> None:
        summary = SignalOutcomeSummary(
            total_signals=20,
            pending_15m_count=0,
            pending_1h_count=0,
            pending_1d_count=0,
            overall=self._bucket("overall", count=20, win_rate=60.0, avg_return=0.2),
            by_signal=[self._bucket("BUY", count=20, win_rate=65.0, avg_return=0.4)],
            by_confidence_bucket=[],
            by_signal_confidence_bucket=[],
            by_signal_score_bucket=[self._bucket("BUY:60-69", count=10, win_rate=70.0, avg_return=0.5)],
        )

        calibrated, score_band, source = self.repo._calibrate_confidence(
            signal="BUY",
            raw_score=68.0,
            summary=summary,
            horizon="1h",
        )

        self.assertEqual(score_band, "60-69")
        self.assertGreater(calibrated, 68.0)
        self.assertEqual(source, "score_band")

    def test_validation_bucket_uses_configured_thresholds(self) -> None:
        rows = [
            SimpleNamespace(
                signal="BUY",
                asset_type="stock",
                entry_price=100.0,
                price_after_15m=None,
                price_after_1h=101.0,
                price_after_1d=None,
            ),
            SimpleNamespace(
                signal="BUY",
                asset_type="stock",
                entry_price=100.0,
                price_after_15m=None,
                price_after_1h=99.9,
                price_after_1d=None,
            ),
            SimpleNamespace(
                signal="BUY",
                asset_type="stock",
                entry_price=100.0,
                price_after_15m=None,
                price_after_1h=100.0,
                price_after_1d=None,
            ),
        ]
        self.repo.settings.validation_primary_horizon = "1h"
        self.repo.settings.validation_win_threshold_pct = 0.0
        self.repo.settings.validation_false_positive_threshold_pct = 0.0

        bucket = self.repo._build_validation_bucket(key="test", rows=rows)

        self.assertEqual(bucket.evaluated_count, 3)
        self.assertEqual(bucket.win_count, 1)
        self.assertEqual(bucket.false_positive_count, 2)
        self.assertAlmostEqual(bucket.win_rate or 0.0, 33.33, places=2)
        self.assertLess(bucket.avg_return_after_friction or 0.0, bucket.avg_return or 0.0)

    def test_signal_return_flips_sell_direction(self) -> None:
        self.assertEqual(
            self.repo._signal_return(
                signal="SELL",
                entry_price=100.0,
                future_price=99.0,
            ),
            1.0,
        )
        self.assertEqual(
            self.repo._signal_return(
                signal="SELL",
                entry_price=100.0,
                future_price=101.0,
            ),
            -1.0,
        )

    def test_evaluate_signal_gate_uses_recent_window_summary(self) -> None:
        summary = SignalOutcomeSummary(
            total_signals=25,
            pending_15m_count=0,
            pending_1h_count=0,
            pending_1d_count=0,
            overall=self._bucket("overall", count=25, win_rate=60.0, avg_return=0.2),
            by_signal=[self._bucket("BUY", count=25, win_rate=66.0, avg_return=0.3)],
            by_confidence_bucket=[],
            by_signal_confidence_bucket=[],
            by_signal_score_bucket=[self._bucket("BUY:60-69", count=8, win_rate=70.0, avg_return=0.35)],
        )

        with patch.object(self.repo, "get_signal_outcome_summary", return_value=summary) as summary_mock:
            evaluation = self.repo.evaluate_signal_gate(
                asset_type="stock",
                signal="BUY",
                score_band="60-69",
                horizon="1h",
                observed_at=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
            )

        summary_mock.assert_called_once_with(
            asset_type="stock",
            generated_at_start=datetime(2026, 3, 6, 12, 0),
            generated_at_end=datetime(2026, 3, 20, 12, 0),
        )
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.evidence_basis, "recent_window:14d:generated_at")
        self.assertEqual(evaluation.trust_window_start, datetime(2026, 3, 6, 12, 0))
        self.assertEqual(evaluation.trust_window_end, datetime(2026, 3, 20, 12, 0))

    def test_calibrate_signal_uses_recent_window_for_primary_and_fallback(self) -> None:
        sparse_asset_summary = SignalOutcomeSummary(
            total_signals=5,
            pending_15m_count=0,
            pending_1h_count=0,
            pending_1d_count=0,
            overall=self._bucket("overall", count=5, win_rate=50.0, avg_return=0.1),
            by_signal=[self._bucket("BUY", count=5, win_rate=50.0, avg_return=0.1)],
            by_confidence_bucket=[],
            by_signal_confidence_bucket=[],
            by_signal_score_bucket=[self._bucket("BUY:60-69", count=5, win_rate=50.0, avg_return=0.1)],
        )
        mature_fallback_summary = SignalOutcomeSummary(
            total_signals=30,
            pending_15m_count=0,
            pending_1h_count=0,
            pending_1d_count=0,
            overall=self._bucket("overall", count=30, win_rate=60.0, avg_return=0.2),
            by_signal=[self._bucket("BUY", count=30, win_rate=68.0, avg_return=0.4)],
            by_confidence_bucket=[],
            by_signal_confidence_bucket=[],
            by_signal_score_bucket=[self._bucket("BUY:60-69", count=12, win_rate=74.0, avg_return=0.45)],
        )

        with patch.object(
            self.repo,
            "get_signal_outcome_summary",
            side_effect=[sparse_asset_summary, mature_fallback_summary],
        ) as summary_mock:
            calibrated, score_band, source = self.repo.calibrate_signal(
                asset_type="stock",
                signal="BUY",
                raw_score=68.0,
                horizon="1h",
                observed_at=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(score_band, "60-69")
        self.assertEqual(source, "score_band")
        self.assertGreater(calibrated, 68.0)
        self.assertEqual(summary_mock.call_count, 2)
        self.assertEqual(
            summary_mock.call_args_list[0].kwargs,
            {
                "asset_type": "stock",
                "generated_at_start": datetime(2026, 3, 6, 12, 0),
                "generated_at_end": datetime(2026, 3, 20, 12, 0),
            },
        )
        self.assertEqual(
            summary_mock.call_args_list[1].kwargs,
            {
                "generated_at_start": datetime(2026, 3, 6, 12, 0),
                "generated_at_end": datetime(2026, 3, 20, 12, 0),
            },
        )

    def test_threshold_candidate_requires_mature_score_band_when_requested(self) -> None:
        row = SimpleNamespace(signal="BUY", score_band="60-69", confidence=68.0)
        signal_bucket = ValidationBucket(
            key="BUY",
            total_signals=25,
            evaluated_count=25,
            pending_count=0,
            win_count=16,
            loss_count=9,
            false_positive_count=9,
            win_rate=64.0,
            avg_return=0.3,
            median_return=0.2,
            avg_win_return=0.8,
            avg_loss_return=-0.45,
            expectancy=0.3,
            false_positive_rate=36.0,
        )

        allowed = self.repo._passes_threshold_candidate(
            row,
            signal_buckets={"BUY": signal_bucket},
            score_band_buckets={},
            min_evaluated_count=20,
            min_win_rate=55.0,
            min_avg_return=0.15,
            score_band_required=True,
        )

        self.assertFalse(allowed)

    def test_validation_summary_surfaces_out_of_sample_degradation(self) -> None:
        base_time = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
        rows = [
            self._outcome_row(
                signal="BUY",
                gate_passed=True,
                asset_type="stock",
                generated_at=base_time + timedelta(hours=index),
                price_after_15m=101.0,
                price_after_1h=101.0 if index < 3 else 99.0,
                price_after_1d=101.0,
                ticker=f"SYM{index}",
            )
            for index in range(6)
        ]

        with patch.object(self.repo, "_load_signal_outcome_rows", return_value=rows):
            summary = self.repo.get_signal_validation_summary()

        self.assertIsNotNone(summary.in_sample)
        self.assertIsNotNone(summary.out_of_sample)
        self.assertTrue(summary.degradation_warnings)

    def test_filter_loaded_signal_outcome_rows_applies_date_range_and_asset_type(self) -> None:
        rows = [
            self._outcome_row(
                signal="BUY",
                gate_passed=True,
                asset_type="stock",
                ticker="AAPL",
                generated_at=datetime(2026, 3, 1, 11, 59, tzinfo=timezone.utc),
                price_after_15m=101.0,
                price_after_1h=101.0,
                price_after_1d=101.0,
            ),
            self._outcome_row(
                signal="BUY",
                gate_passed=True,
                asset_type="stock",
                ticker="MSFT",
                generated_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
                price_after_15m=101.0,
                price_after_1h=101.0,
                price_after_1d=101.0,
            ),
            self._outcome_row(
                signal="SELL",
                gate_passed=False,
                asset_type="crypto",
                ticker="BTC/USD",
                generated_at=datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc),
                price_after_15m=99.0,
                price_after_1h=99.0,
                price_after_1d=99.0,
            ),
            self._outcome_row(
                signal="HOLD",
                gate_passed=False,
                asset_type="stock",
                ticker="NVDA",
                generated_at=datetime(2026, 3, 1, 13, 0, tzinfo=timezone.utc),
                price_after_15m=100.0,
                price_after_1h=100.0,
                price_after_1d=100.0,
            ),
        ]

        filtered = self.repo._filter_loaded_signal_outcome_rows(
            rows,
            asset_type="stock",
            generated_at_start=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
            generated_at_end=datetime(2026, 3, 2, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual([row.ticker for row in filtered], ["MSFT"])

    def test_signal_outcome_performance_report_builds_multi_horizon_rollups(self) -> None:
        self.repo.settings.outcome_report_min_evaluated_per_horizon = 1
        self.repo.settings.outcome_baseline_min_evaluated_per_horizon = 1
        self.repo.settings.outcome_baseline_min_mean_return_pct = 0.0
        self.repo.settings.validation_primary_horizon = "1h"
        rows = [
            self._outcome_row(
                signal="BUY",
                gate_passed=True,
                asset_type="stock",
                ticker="AAPL",
                generated_at=datetime(2026, 3, 5, 12, 0),
                price_after_15m=101.0,
                price_after_1h=102.0,
                price_after_1d=103.0,
            ),
            self._outcome_row(
                signal="BUY",
                gate_passed=False,
                asset_type="stock",
                ticker="MSFT",
                generated_at=datetime(2026, 3, 5, 12, 5),
                price_after_15m=99.0,
                price_after_1h=98.0,
                price_after_1d=97.0,
            ),
            self._outcome_row(
                signal="SELL",
                gate_passed=True,
                asset_type="crypto",
                ticker="BTC/USD",
                generated_at=datetime(2026, 3, 5, 12, 10),
                price_after_15m=99.0,
                price_after_1h=98.0,
                price_after_1d=97.0,
            ),
            self._outcome_row(
                signal="SELL",
                gate_passed=False,
                asset_type="stock",
                ticker="TSLA",
                generated_at=datetime(2026, 3, 5, 12, 15),
                price_after_15m=101.0,
                price_after_1h=102.0,
                price_after_1d=103.0,
            ),
        ]

        with patch.object(self.repo, "_load_signal_outcome_rows", return_value=rows):
            report = self.repo.get_signal_outcome_performance_report(
                start=datetime(2026, 3, 5, 0, 0),
                end=datetime(2026, 3, 6, 0, 0),
            )

        self.assertEqual(report.total_signals, 4)
        self.assertEqual(report.overall.metrics_1h.evaluated_count, 4)
        self.assertAlmostEqual(report.overall.metrics_1h.mean_return or 0.0, 0.0, places=4)
        signal_gate = {bucket.key: bucket for bucket in report.by_signal_and_gate}
        self.assertEqual(signal_gate["BUY:passed"].metrics_1h.mean_return, 2.0)
        self.assertEqual(signal_gate["BUY:blocked"].metrics_1h.mean_return, -2.0)
        self.assertEqual(signal_gate["SELL:passed"].metrics_1h.mean_return, 2.0)
        self.assertEqual(signal_gate["SELL:blocked"].metrics_1h.mean_return, -2.0)
        asset_types = {bucket.key for bucket in report.by_asset_type}
        self.assertEqual(asset_types, {"stock", "crypto"})
        self.assertTrue(report.baseline.passes_baseline)
        self.assertEqual([check.key for check in report.baseline.checks], ["BUY:passed", "SELL:passed"])

    def test_performance_report_supports_regime_and_stressed_friction(self) -> None:
        rows = [
            self._outcome_row(
                signal="BUY",
                gate_passed=True,
                asset_type="stock",
                ticker="AAPL",
                generated_at=datetime(2026, 3, 5, 12, 0),
                market_status="bullish",
                price_after_15m=101.0,
                price_after_1h=102.0,
                price_after_1d=103.0,
            ),
            self._outcome_row(
                signal="BUY",
                gate_passed=True,
                asset_type="stock",
                ticker="MSFT",
                generated_at=datetime(2026, 3, 5, 12, 5),
                market_status="bearish",
                price_after_15m=101.0,
                price_after_1h=102.0,
                price_after_1d=103.0,
            ),
        ]

        with patch.object(self.repo, "_load_signal_outcome_rows", return_value=rows):
            report = self.repo.get_signal_outcome_performance_report(
                start=datetime(2026, 3, 5, 0, 0),
                end=datetime(2026, 3, 6, 0, 0),
                regime="bullish",
                friction_scenario="stressed",
            )

        self.assertEqual(report.total_signals, 1)
        self.assertEqual(report.regime, "bullish")
        self.assertEqual(report.friction_scenario, "stressed")

    def test_signal_validation_summary_supports_windowed_gate_buckets(self) -> None:
        rows = [
            self._outcome_row(
                signal="BUY",
                gate_passed=True,
                asset_type="stock",
                ticker="AAPL",
                generated_at=datetime(2026, 3, 5, 12, 0),
                price_after_15m=101.0,
                price_after_1h=102.0,
                price_after_1d=103.0,
            ),
            self._outcome_row(
                signal="SELL",
                gate_passed=False,
                asset_type="stock",
                ticker="TSLA",
                generated_at=datetime(2026, 3, 5, 12, 15),
                price_after_15m=101.0,
                price_after_1h=102.0,
                price_after_1d=103.0,
            ),
        ]
        start = datetime(2026, 3, 5, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 6, 0, 0, tzinfo=timezone.utc)

        with patch.object(self.repo, "_load_signal_outcome_rows", return_value=rows) as load_mock:
            summary = self.repo.get_signal_validation_summary(start=start, end=end)

        load_mock.assert_called_once_with(
            asset_type=None,
            generated_at_start=datetime(2026, 3, 5, 0, 0),
            generated_at_end=datetime(2026, 3, 6, 0, 0),
        )
        self.assertEqual(summary.start, datetime(2026, 3, 5, 0, 0))
        self.assertEqual(summary.end, datetime(2026, 3, 6, 0, 0))
        gate_keys = {bucket.key for bucket in summary.by_signal_and_gate}
        self.assertEqual(gate_keys, {"BUY:passed", "SELL:blocked"})

    def test_validation_summary_filters_by_regime_and_data_grade(self) -> None:
        rows = [
            self._outcome_row(
                signal="BUY",
                gate_passed=True,
                asset_type="stock",
                ticker="AAPL",
                generated_at=datetime(2026, 3, 5, 12, 0),
                market_status="bullish",
                data_grade="decision",
                price_after_15m=101.0,
                price_after_1h=102.0,
                price_after_1d=103.0,
            ),
            self._outcome_row(
                signal="SELL",
                gate_passed=False,
                asset_type="stock",
                ticker="TSLA",
                generated_at=datetime(2026, 3, 5, 12, 15),
                market_status="bearish",
                data_grade="research",
                price_after_15m=101.0,
                price_after_1h=102.0,
                price_after_1d=103.0,
            ),
        ]

        with patch.object(self.repo, "_load_signal_outcome_rows", return_value=rows):
            summary = self.repo.get_signal_validation_summary(
                regime="bullish",
                data_grade="decision",
            )

        self.assertEqual(summary.total_signals, 1)
        self.assertEqual(summary.by_data_grade[0].key, "decision")

    def test_validation_threshold_sweep_supports_windowed_rows(self) -> None:
        rows = [
            self._outcome_row(
                signal="BUY",
                gate_passed=True,
                asset_type="stock",
                ticker=f"AAPL{i}",
                generated_at=datetime(2026, 3, 5, 12, i),
                price_after_15m=101.0,
                price_after_1h=102.0,
                price_after_1d=103.0,
            )
            for i in range(5)
        ] + [
            self._outcome_row(
                signal="SELL",
                gate_passed=False,
                asset_type="stock",
                ticker="TSLA",
                generated_at=datetime(2026, 3, 5, 12, 15),
                price_after_15m=101.0,
                price_after_1h=102.0,
                price_after_1d=103.0,
            ),
        ]
        start = datetime(2026, 3, 5, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 6, 0, 0, tzinfo=timezone.utc)

        with patch.object(self.repo, "_load_signal_outcome_rows", return_value=rows) as load_mock:
            sweep = self.repo.get_validation_threshold_sweep(start=start, end=end)

        load_mock.assert_called_once_with(
            asset_type=None,
            generated_at_start=datetime(2026, 3, 5, 0, 0),
            generated_at_end=datetime(2026, 3, 6, 0, 0),
        )
        self.assertEqual(sweep.start, datetime(2026, 3, 5, 0, 0))
        self.assertEqual(sweep.end, datetime(2026, 3, 6, 0, 0))
        self.assertGreaterEqual(len(sweep.candidates), 1)
        self.assertEqual(sweep.recommendation.evidence_status, "provisional")
        self.assertTrue(sweep.recommendation.warnings)
        self.assertEqual({bucket.key for bucket in sweep.by_signal_and_gate}, {"BUY:passed", "SELL:blocked"})

    def test_validation_threshold_sweep_recommends_candidate_when_gated_cohorts_are_mature(self) -> None:
        rows = [
            self._outcome_row(
                signal="BUY",
                gate_passed=True,
                asset_type="stock",
                ticker=f"BUY{i}",
                generated_at=datetime(2026, 3, 5, 12, 0),
                price_after_15m=101.0,
                price_after_1h=102.0,
                price_after_1d=103.0,
            )
            for i in range(20)
        ] + [
            self._outcome_row(
                signal="SELL",
                gate_passed=True,
                asset_type="stock",
                ticker=f"SELL{i}",
                generated_at=datetime(2026, 3, 5, 12, 5),
                price_after_15m=99.0,
                price_after_1h=98.0,
                price_after_1d=97.0,
            )
            for i in range(20)
        ]

        with patch.object(self.repo, "_load_signal_outcome_rows", return_value=rows):
            sweep = self.repo.get_validation_threshold_sweep(
                start=datetime(2026, 3, 5, 0, 0, tzinfo=timezone.utc),
                end=datetime(2026, 3, 6, 0, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(sweep.recommendation.source, "candidate")
        self.assertEqual(sweep.recommendation.evidence_status, "ready")
        self.assertGreaterEqual(len(sweep.candidates), 1)

    def test_sync_signal_outcome_returns_repairs_mismatched_legacy_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                with SessionLocal() as session:
                    session.add(
                        SignalOutcomeORM(
                            run_id="run-1",
                            ticker="AAPL",
                            asset_type="stock",
                            signal="SELL",
                            confidence=62.0,
                            entry_price=100.0,
                            generated_at=datetime(2026, 3, 18, 12, 0),
                            price_after_15m=99.0,
                            return_after_15m=-1.0,
                            evaluated_at_15m=datetime(2026, 3, 18, 12, 15),
                            status_15m="resolved",
                            price_after_1h=98.0,
                            return_after_1h=-2.0,
                            evaluated_at_1h=datetime(2026, 3, 18, 13, 0),
                            status_1h="resolved",
                            price_after_1d=97.0,
                            return_after_1d=-3.0,
                            evaluated_at_1d=datetime(2026, 3, 19, 12, 0),
                            status_1d="resolved",
                        )
                    )
                    session.commit()

                with patch.object(repository_module, "SessionLocal", SessionLocal):
                    repaired = self.repo.sync_signal_outcome_returns()
                    self.assertEqual(repaired, 3)

                    with SessionLocal() as session:
                        row = session.query(SignalOutcomeORM).one()
                        self.assertEqual(row.return_after_15m, 1.0)
                        self.assertEqual(row.return_after_1h, 2.0)
                        self.assertEqual(row.return_after_1d, 3.0)
            finally:
                engine.dispose()

    def test_execution_alignment_counts_blocked_preview_by_signal_outcome_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                with SessionLocal() as session:
                    outcome = SignalOutcomeORM(
                        run_id="run-1",
                        ticker="AAPL",
                        asset_type="stock",
                        signal="BUY",
                        confidence=68.0,
                        entry_price=100.0,
                        generated_at=datetime(2026, 3, 18, 12, 0),
                        price_after_1h=102.0,
                        return_after_1h=2.0,
                        evaluated_at_1h=datetime(2026, 3, 18, 13, 0),
                        status_1h="resolved",
                    )
                    session.add(outcome)
                    session.flush()
                    session.add(
                        ExecutionAuditORM(
                            created_at=datetime(2026, 3, 18, 12, 5),
                            updated_at=datetime(2026, 3, 18, 12, 5),
                            ticker="AAPL",
                            asset_type="stock",
                            side="buy",
                            order_type="market",
                            qty=1.0,
                            lifecycle_status="blocked",
                            signal_outcome_id=outcome.id,
                            signal_run_id="run-1",
                            signal_generated_at=datetime(2026, 3, 18, 12, 0),
                            latest_signal="BUY",
                            confidence=68.0,
                            trade_gate_allowed=False,
                            trade_gate_reason="blocked",
                            submitted=False,
                            preview_payload="{}",
                        )
                    )
                    session.commit()

                with patch.object(repository_module, "SessionLocal", SessionLocal):
                    summary = self.repo.get_execution_alignment_summary(
                        start=datetime(2026, 3, 18, 0, 0, tzinfo=timezone.utc),
                        end=datetime(2026, 3, 19, 0, 0, tzinfo=timezone.utc),
                    )

                self.assertEqual(summary.blocked_previews.total_signals, 1)
                self.assertEqual(summary.blocked_previews.evaluated_count, 1)
            finally:
                engine.dispose()

    def test_execution_alignment_counts_submitted_orders_separately_from_journal_took(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                with SessionLocal() as session:
                    outcome = SignalOutcomeORM(
                        run_id="run-2",
                        ticker="MSFT",
                        asset_type="stock",
                        signal="BUY",
                        confidence=72.0,
                        entry_price=100.0,
                        generated_at=datetime(2026, 3, 18, 12, 0),
                        price_after_1h=103.0,
                        return_after_1h=3.0,
                        evaluated_at_1h=datetime(2026, 3, 18, 13, 0),
                        status_1h="resolved",
                    )
                    session.add(outcome)
                    session.flush()
                    session.add(
                        ExecutionAuditORM(
                            created_at=datetime(2026, 3, 18, 12, 5),
                            updated_at=datetime(2026, 3, 18, 12, 6),
                            ticker="MSFT",
                            asset_type="stock",
                            side="buy",
                            order_type="market",
                            qty=1.0,
                            lifecycle_status="submitted",
                            signal_outcome_id=outcome.id,
                            signal_run_id="run-2",
                            signal_generated_at=datetime(2026, 3, 18, 12, 0),
                            latest_signal="BUY",
                            confidence=72.0,
                            trade_gate_allowed=True,
                            trade_gate_reason="passed",
                            submitted=True,
                            broker_status="accepted",
                            preview_payload="{}",
                        )
                    )
                    session.add(
                        JournalEntryORM(
                            ticker="MSFT",
                            run_id="run-2",
                            decision="took",
                            created_at=datetime(2026, 3, 18, 12, 7),
                            notes="journal-only confirmation",
                        )
                    )
                    session.commit()

                with patch.object(repository_module, "SessionLocal", SessionLocal):
                    summary = self.repo.get_execution_alignment_summary(
                        start=datetime(2026, 3, 18, 0, 0, tzinfo=timezone.utc),
                        end=datetime(2026, 3, 19, 0, 0, tzinfo=timezone.utc),
                    )

                self.assertEqual(summary.taken_trades.total_signals, 1)
                self.assertEqual(summary.journal_took.total_signals, 1)
                self.assertEqual(summary.blocked_previews.total_signals, 0)
            finally:
                engine.dispose()

    def test_execution_alignment_surfaces_dry_run_cohort(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                with SessionLocal() as session:
                    outcome = SignalOutcomeORM(
                        run_id="run-dry",
                        ticker="AMD",
                        asset_type="stock",
                        signal="BUY",
                        confidence=72.0,
                        entry_price=100.0,
                        generated_at=datetime(2026, 3, 18, 12, 0),
                        price_after_1h=103.0,
                        return_after_1h=3.0,
                        evaluated_at_1h=datetime(2026, 3, 18, 13, 0),
                        status_1h="resolved",
                    )
                    session.add(outcome)
                    session.flush()
                    session.add(
                        ExecutionAuditORM(
                            created_at=datetime(2026, 3, 18, 12, 5),
                            updated_at=datetime(2026, 3, 18, 12, 6),
                            ticker="AMD",
                            asset_type="stock",
                            side="buy",
                            order_type="market",
                            qty=1.0,
                            lifecycle_status="dry_run",
                            signal_outcome_id=outcome.id,
                            signal_run_id="run-dry",
                            signal_generated_at=datetime(2026, 3, 18, 12, 0),
                            latest_signal="BUY",
                            confidence=72.0,
                            trade_gate_allowed=True,
                            trade_gate_reason="passed",
                            submitted=False,
                            preview_payload="{}",
                        )
                    )
                    session.commit()

                with patch.object(repository_module, "SessionLocal", SessionLocal):
                    summary = self.repo.get_execution_alignment_summary(
                        start=datetime(2026, 3, 18, 0, 0, tzinfo=timezone.utc),
                        end=datetime(2026, 3, 19, 0, 0, tzinfo=timezone.utc),
                    )

                self.assertIsNotNone(summary.automation_dry_run)
                self.assertEqual(summary.automation_dry_run.total_signals, 1)
            finally:
                engine.dispose()

    def test_backfill_execution_audit_signal_links_populates_missing_link_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                with SessionLocal() as session:
                    session.add(
                        SignalOutcomeORM(
                            run_id="run-9",
                            ticker="COIN",
                            asset_type="stock",
                            signal="SELL",
                            confidence=62.0,
                            entry_price=100.0,
                            generated_at=datetime(2026, 3, 18, 20, 40),
                        )
                    )
                    session.add(
                        ExecutionAuditORM(
                            created_at=datetime(2026, 3, 18, 20, 48),
                            updated_at=datetime(2026, 3, 18, 20, 48),
                            ticker="COIN",
                            asset_type="stock",
                            side="sell",
                            order_type="market",
                            qty=1.0,
                            lifecycle_status="previewed",
                            latest_signal="SELL",
                            confidence=64.0,
                            trade_gate_allowed=False,
                            trade_gate_reason="blocked",
                            submitted=False,
                            preview_payload="{}",
                        )
                    )
                    session.commit()

                with patch.object(repository_module, "SessionLocal", SessionLocal):
                    updated = self.repo.backfill_execution_audit_signal_links()
                    self.assertEqual(updated, 1)
                    with SessionLocal() as session:
                        audit = session.query(ExecutionAuditORM).one()
                        self.assertIsNotNone(audit.signal_outcome_id)
                        self.assertEqual(audit.signal_run_id, "run-9")
                        self.assertEqual(audit.trade_gate_horizon, self.repo.settings.trade_gate_horizon)
                        self.assertEqual(audit.evidence_basis, "recent_window:14d:generated_at")
                        self.assertIsNotNone(audit.trust_window_start)
                        self.assertIsNotNone(audit.trust_window_end)
            finally:
                engine.dispose()

    def test_build_decision_row_includes_evidence_reasons_and_freshness_flags(self) -> None:
        result = SimpleNamespace(
            ticker="AAPL",
            asset_type="stock",
            score=67.5,
            price_change_pct=1.2,
            relative_volume=2.4,
            options_flow_score=58.0,
            created_at=datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc),
            decision_signal="BUY",
            calibration_source="score_band",
            provider_status="ok",
            gate_passed=True,
            data_grade="decision",
            bar_age_minutes=3.5,
            freshness_flags_json=json.dumps({"market_bars": "ok", "options_flow": "missing"}),
            layer_details_json=json.dumps({"directional": {"score_contributions": {"momentum": 12.5}}}),
        )
        strategy_metadata = SimpleNamespace(
            confidence_label="calibrated_confidence",
            evidence_quality="moderate",
            evidence_quality_score=0.74,
            evidence_quality_reasons=(
                "Confidence is informed by mature score-band evidence.",
                "Core market-data inputs look usable.",
            ),
            data_grade="decision",
            execution_eligibility="eligible",
            strategy_version="v3.0-explicit",
        )

        with patch.object(self.repo, "_strategy_metadata_from_row", return_value=strategy_metadata):
            decision_row = self.repo._build_decision_row(result)

        self.assertEqual(decision_row.evidence_quality_reasons, strategy_metadata.evidence_quality_reasons)
        self.assertEqual(decision_row.freshness_flags, {"market_bars": "ok", "options_flow": "missing"})
        self.assertEqual(decision_row.recommended_action, "dry_run")
        self.assertEqual(decision_row.score_contributions, {"momentum": 12.5})

    def test_build_decision_row_includes_signal_age_minutes(self) -> None:
        created = datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc)
        fake_now = datetime(2026, 4, 4, 12, 30, tzinfo=timezone.utc)
        result = SimpleNamespace(
            ticker="AAPL",
            asset_type="stock",
            score=67.5,
            price_change_pct=1.2,
            relative_volume=2.4,
            options_flow_score=58.0,
            created_at=created,
            decision_signal="BUY",
            calibration_source="score_band",
            provider_status="ok",
            gate_passed=True,
            data_grade="decision",
            bar_age_minutes=3.5,
            freshness_flags_json=None,
            layer_details_json=None,
        )
        strategy_metadata = SimpleNamespace(
            confidence_label="calibrated_confidence",
            evidence_quality="moderate",
            evidence_quality_score=0.74,
            evidence_quality_reasons=(),
            data_grade="decision",
            execution_eligibility="eligible",
            strategy_version="v3.0-explicit",
        )

        class _FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fake_now

        with (
            patch.object(self.repo, "_strategy_metadata_from_row", return_value=strategy_metadata),
            patch.object(repository_module, "datetime", _FakeDatetime),
        ):
            decision_row = self.repo._build_decision_row(result)

        self.assertEqual(decision_row.signal_age_minutes, 30.0)
        self.assertGreaterEqual(decision_row.signal_age_minutes, 0)


if __name__ == "__main__":
    unittest.main()
