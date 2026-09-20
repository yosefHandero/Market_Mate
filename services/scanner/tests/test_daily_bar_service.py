import asyncio
import unittest
from datetime import datetime, timedelta, timezone

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


class _FakeBarStore:
    """In-memory stand-in for HistoricalBarStore (no DB, no providers)."""

    def __init__(self, bars: list[dict]) -> None:
        self.bars = bars
        self.tail_refresh_calls = 0
        self.load_calls = 0

    def load_bars(self, symbol: str, *, asset_type: str | None = None) -> list[dict]:
        self.load_calls += 1
        return list(self.bars)

    async def ensure_recent_tail(
        self, symbol: str, *, asset_type: str | None = None, overlap_days: int = 5
    ) -> list[dict]:
        self.tail_refresh_calls += 1
        return list(self.bars)


class DailyBarServiceTests(unittest.TestCase):
    def test_store_backed_serving_with_ttl_memo(self) -> None:
        settings = Settings(
            weekly_daily_bar_cache_ttl_seconds=3600,
            weekly_daily_lookback_bars_max=500,
        )
        store = _FakeBarStore(_bars_ending(count=3, last_day=datetime.now(timezone.utc)))
        service = DailyBarService(settings=settings, bar_store=store)  # type: ignore[arg-type]

        async def run() -> None:
            first, first_source = await service.get_daily_bars("AAPL", asset_type="stock")
            second, second_source = await service.get_daily_bars("AAPL", asset_type="stock")
            # First call refreshes the store tail; second within TTL serves the store.
            self.assertEqual(first_source, "store_refreshed")
            self.assertEqual(second_source, "store")
            self.assertEqual(store.tail_refresh_calls, 1)
            self.assertEqual(len(first), 3)
            self.assertEqual(len(second), 3)
            # force_refresh bypasses the memo.
            _, forced_source = await service.get_daily_bars(
                "AAPL", asset_type="stock", force_refresh=True
            )
            self.assertEqual(forced_source, "store_refreshed")
            self.assertEqual(store.tail_refresh_calls, 2)

        asyncio.run(run())

    def test_trims_to_configured_lookback(self) -> None:
        settings = Settings(
            weekly_daily_bar_cache_ttl_seconds=3600,
            weekly_daily_lookback_bars_max=100,
        )
        store = _FakeBarStore(_bars_ending(count=250, last_day=datetime.now(timezone.utc)))
        service = DailyBarService(settings=settings, bar_store=store)  # type: ignore[arg-type]

        async def run() -> None:
            bars, _ = await service.get_daily_bars("AAPL", asset_type="stock")
            self.assertEqual(len(bars), 100)

        asyncio.run(run())

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

    def test_stale_store_content_is_not_reported_fresh(self) -> None:
        settings = Settings(
            weekly_daily_bar_cache_ttl_seconds=86400,
            weekly_daily_lookback_bars_max=500,
            weekly_daily_lookback_bars_min=1,
            weekly_daily_lookback_bars_preferred=1,
            weekly_daily_bar_max_age_days_stock=5,
        )
        # Store tail refresh succeeded but the newest available bar is two
        # weeks old (e.g. providers down, serving stored history).
        stale_last = datetime.now(timezone.utc) - timedelta(days=14)
        store = _FakeBarStore(_bars_ending(count=3, last_day=stale_last))
        service = DailyBarService(settings=settings, bar_store=store)  # type: ignore[arg-type]

        async def run() -> tuple[list[dict], str]:
            return await service.get_daily_bars("AAPL", asset_type="stock")

        loaded, _source = asyncio.run(run())
        # Stale content must not be reported as fresh primary data.
        self.assertTrue(service.is_daily_bars_stale(loaded, asset_type="stock"))
        self.assertNotEqual(service.assess_data_quality(loaded, asset_type="stock"), "ok")


if __name__ == "__main__":
    unittest.main()
