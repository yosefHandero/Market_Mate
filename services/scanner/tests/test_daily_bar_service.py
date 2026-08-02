import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.services.daily_bar_service import DailyBarService


def _bars_ending(*, count: int, last_day: datetime) -> list[dict]:
    return [
        {
            "t": (last_day - timedelta(days=offset)).isoformat(),
            "o": 100,
            "h": 101,
            "l": 99,
            "c": 100.5,
            "v": 10,
        }
        for offset in reversed(range(count))
    ]


class DailyBarServiceTests(unittest.TestCase):
    def test_cache_hit_avoids_refetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = Settings(
                cache_dir=tmpdir,
                weekly_daily_bar_cache_ttl_seconds=3600,
                weekly_daily_lookback_bars_max=500,
            )
            service = DailyBarService(settings=settings)
            symbol = "AAPL"
            bars = [
                {
                    "t": datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(),
                    "o": 100,
                    "h": 101,
                    "l": 99,
                    "c": 100.5,
                    "v": 10,
                }
            ]
            cache_path = service._cache_path(symbol, "stock")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "symbol": symbol,
                        "asset_type": "stock",
                        "timeframe": "1Day",
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "bars": bars,
                    }
                ),
                encoding="utf-8",
            )

            async def run() -> tuple[list[dict], str]:
                return await service.get_daily_bars(symbol, asset_type="stock")

            loaded, source = asyncio.run(run())
            self.assertEqual(source, "cache")
            self.assertEqual(len(loaded), 1)

    def test_assess_data_quality_thresholds(self) -> None:
        settings = Settings(
            weekly_daily_lookback_bars_min=250,
            weekly_daily_lookback_bars_preferred=500,
        )
        service = DailyBarService(settings=settings)
        as_of = datetime(2026, 3, 2, tzinfo=timezone.utc)
        last_day = datetime(2026, 3, 2, tzinfo=timezone.utc)
        self.assertEqual(
            service.assess_data_quality(_bars_ending(count=500, last_day=last_day), asset_type="stock", as_of=as_of),
            "ok",
        )
        self.assertEqual(
            service.assess_data_quality(_bars_ending(count=300, last_day=last_day), asset_type="stock", as_of=as_of),
            "low",
        )
        self.assertEqual(
            service.assess_data_quality(_bars_ending(count=100, last_day=last_day), asset_type="stock", as_of=as_of),
            "degraded",
        )

    def test_stock_tolerates_weekend_gap_but_stale_never_fresh(self) -> None:
        settings = Settings(
            weekly_daily_lookback_bars_min=250,
            weekly_daily_lookback_bars_preferred=500,
            weekly_daily_bar_max_age_days_stock=5,
        )
        service = DailyBarService(settings=settings)
        # Monday scan with Friday as the most recent bar: 3 calendar days old, within tolerance.
        monday = datetime(2026, 3, 2, 14, 0, tzinfo=timezone.utc)
        friday = datetime(2026, 2, 27, 20, 0, tzinfo=timezone.utc)
        fresh_weekend = _bars_ending(count=500, last_day=friday)
        self.assertFalse(service.is_daily_bars_stale(fresh_weekend, asset_type="stock", as_of=monday))
        self.assertEqual(
            service.assess_data_quality(fresh_weekend, asset_type="stock", as_of=monday),
            "ok",
        )
        # A stock bar more than a week old is stale and must never report fresh "ok".
        stale_last = datetime(2026, 2, 20, 20, 0, tzinfo=timezone.utc)
        stale_bars = _bars_ending(count=500, last_day=stale_last)
        self.assertTrue(service.is_daily_bars_stale(stale_bars, asset_type="stock", as_of=monday))
        self.assertEqual(
            service.assess_data_quality(stale_bars, asset_type="stock", as_of=monday),
            "low",
        )

    def test_crypto_recency_is_stricter_than_stock(self) -> None:
        settings = Settings(
            weekly_daily_lookback_bars_min=250,
            weekly_daily_lookback_bars_preferred=500,
            weekly_daily_bar_max_age_days_stock=5,
            weekly_daily_bar_max_age_days_crypto=2,
        )
        service = DailyBarService(settings=settings)
        now = datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc)
        last_day = datetime(2026, 2, 28, 12, 0, tzinfo=timezone.utc)  # ~3 days old
        bars = _bars_ending(count=500, last_day=last_day)
        # Stocks tolerate the gap; crypto (trades daily) flags it stale.
        self.assertFalse(service.is_daily_bars_stale(bars, asset_type="stock", as_of=now))
        self.assertTrue(service.is_daily_bars_stale(bars, asset_type="crypto", as_of=now))
        self.assertEqual(service.assess_data_quality(bars, asset_type="crypto", as_of=now), "low")

    def test_cache_hit_with_stale_bars_is_not_reported_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = Settings(
                cache_dir=tmpdir,
                weekly_daily_bar_cache_ttl_seconds=86400,
                weekly_daily_lookback_bars_max=500,
                weekly_daily_lookback_bars_min=1,
                weekly_daily_lookback_bars_preferred=1,
                weekly_daily_bar_max_age_days_stock=5,
            )
            service = DailyBarService(settings=settings)
            symbol = "AAPL"
            # Cache written now (TTL fresh) but its newest bar is two weeks old.
            stale_last = datetime.now(timezone.utc) - timedelta(days=14)
            bars = _bars_ending(count=3, last_day=stale_last)
            cache_path = service._cache_path(symbol, "stock")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "symbol": symbol,
                        "asset_type": "stock",
                        "timeframe": "1Day",
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "bars": bars,
                    }
                ),
                encoding="utf-8",
            )

            async def run() -> tuple[list[dict], str]:
                return await service.get_daily_bars(symbol, asset_type="stock")

            loaded, source = asyncio.run(run())
            # Cache still prevents a provider call (TTL fresh)...
            self.assertEqual(source, "cache")
            # ...but the stale content must not be reported as fresh primary data.
            self.assertTrue(service.is_daily_bars_stale(loaded, asset_type="stock"))
            self.assertNotEqual(service.assess_data_quality(loaded, asset_type="stock"), "ok")


if __name__ == "__main__":
    unittest.main()
