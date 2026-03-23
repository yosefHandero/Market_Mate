import unittest
from types import SimpleNamespace

from app.schemas import SignalOutcomePerformanceBucket, SignalOutcomeSummary, ValidationBucket
from app.services.repository import ScanRepository


class RepositoryCalibrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = ScanRepository()

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
                entry_price=100.0,
                price_after_15m=None,
                price_after_1h=101.0,
                price_after_1d=None,
            ),
            SimpleNamespace(
                signal="BUY",
                entry_price=100.0,
                price_after_15m=None,
                price_after_1h=99.9,
                price_after_1d=None,
            ),
            SimpleNamespace(
                signal="BUY",
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


if __name__ == "__main__":
    unittest.main()
