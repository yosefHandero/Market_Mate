import unittest
from datetime import datetime, timezone

from app.config import Settings
from app.core.freshness_policy import (
    enrich_scan_run_freshness,
    row_has_bad_freshness_flags,
    row_is_bar_stale,
    unified_bar_freshness_max_age_minutes,
    unified_freshness_max_age_minutes,
)
from app.schemas import ScanResult


def _row_with_bar_age(bar_age_minutes: float) -> ScanResult:
    return ScanResult(
        ticker="NVDA",
        score=70,
        explanation="test",
        price=100,
        price_change_pct=1.0,
        relative_volume=1.2,
        sentiment_score=0.1,
        filing_flag=False,
        breakout_flag=False,
        market_status="neutral",
        sector_strength_score=0.0,
        bar_age_minutes=bar_age_minutes,
        created_at=datetime.now(timezone.utc),
    )


class FreshnessPolicyTests(unittest.TestCase):
    def test_unified_threshold_uses_health_max_stale(self) -> None:
        settings = Settings(health_max_stale_minutes=25)
        self.assertEqual(unified_freshness_max_age_minutes(settings), 25)

    def test_bar_threshold_uses_provider_max_bar_age(self) -> None:
        settings = Settings(provider_max_bar_age_minutes=45)
        self.assertEqual(unified_bar_freshness_max_age_minutes(settings), 45)

    def test_row_is_bar_stale_when_age_exceeds_bar_threshold(self) -> None:
        settings = Settings(provider_max_bar_age_minutes=45)
        self.assertTrue(row_is_bar_stale(_row_with_bar_age(46), settings))

    def test_delayed_31_minute_bar_is_not_stale_at_default_threshold(self) -> None:
        # Decoupled bar-age threshold (45m) keeps borderline ~31m delayed feeds usable
        # while scan-run freshness still uses the tighter health_max_stale_minutes (30m).
        settings = Settings(health_max_stale_minutes=30, provider_max_bar_age_minutes=45)
        self.assertFalse(row_is_bar_stale(_row_with_bar_age(31), settings))

    def test_ws_override_flag_is_healthy(self) -> None:
        row = _row_with_bar_age(5)
        row.freshness_flags = {"market_bars": "ws_override"}
        self.assertFalse(row_has_bad_freshness_flags(row))

    def test_scan_run_freshness_false_when_old(self) -> None:
        settings = Settings(health_max_stale_minutes=30)
        old = datetime.now(timezone.utc).replace(year=2020)
        age, fresh = enrich_scan_run_freshness(created_at=old, settings=settings)
        self.assertIsNotNone(age)
        self.assertFalse(fresh)


if __name__ == "__main__":
    unittest.main()
