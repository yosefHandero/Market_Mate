import asyncio
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import AsyncMock

from app.schemas import ReplayRequest
from app.services.replay import ReplayService


def _bar(ts: datetime, price: float, volume: int = 1000) -> dict:
    return {
        "t": ts.isoformat(),
        "o": price - 0.2,
        "h": price + 0.4,
        "l": price - 0.4,
        "c": price,
        "v": volume,
    }


class ReplayServiceTests(unittest.TestCase):
    def test_replay_uses_historical_bars_without_lookahead(self) -> None:
        service = ReplayService()
        start = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
        bars = [_bar(start + timedelta(minutes=5 * index), 100 + index * 0.5) for index in range(40)]
        spy_bars = [_bar(start + timedelta(minutes=5 * index), 500 + index * 0.2) for index in range(40)]
        qqq_bars = [_bar(start + timedelta(minutes=5 * index), 400 + index * 0.15) for index in range(40)]

        service.alpaca.get_historical_stock_bars = AsyncMock(
            side_effect=lambda symbol, **_: {
                "AAPL": bars,
                "SPY": spy_bars,
                "QQQ": qqq_bars,
            }[symbol]
        )

        response = asyncio.run(
            service.replay(
                ReplayRequest(
                    symbols=["AAPL"],
                    start=start,
                    end=start + timedelta(hours=4),
                    interval_minutes=60,
                    warmup_bars=10,
                    apply_friction=True,
                )
            )
        )

        self.assertGreater(response.summary.total_snapshots, 0)
        self.assertEqual(response.strategy_version, "v4.0-layered")
        self.assertEqual(response.strategy_variant, service.settings.scanner_strategy_variant)
        self.assertTrue(
            all(
                row.observed_at <= start + timedelta(hours=4)
                for row in response.rows
            )
        )


if __name__ == "__main__":
    unittest.main()
