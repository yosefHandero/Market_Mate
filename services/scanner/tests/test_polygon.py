import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.clients.polygon import PolygonClient


class PolygonClientTests(unittest.TestCase):
    def test_rows_to_alpaca_bars_converts_polygon_payload(self) -> None:
        timestamp_ms = int(datetime(2026, 5, 12, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)
        rows = PolygonClient._rows_to_alpaca_bars(
            [{"t": timestamp_ms, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100}]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["c"], 1.5)
        self.assertIn("2026-05-12", rows[0]["t"])

    def test_get_latest_bars_builds_symbol_rows(self) -> None:
        client = PolygonClient()
        client.settings.polygon_api_key = "test-key"

        def bar_builder(payload: dict) -> dict:
            return {
                symbol: {"latest_price": float(rows[-1]["c"]), "bars": rows}
                for symbol, rows in payload.get("bars", {}).items()
                if rows
            }

        async def run() -> dict:
            with patch.object(
                client,
                "_fetch_symbol_bars",
                AsyncMock(
                    return_value=[
                        {
                            "t": datetime.now(timezone.utc).isoformat(),
                            "o": 100,
                            "h": 101,
                            "l": 99,
                            "c": 100.5,
                            "v": 10,
                        }
                    ]
                ),
            ):
                return await client.get_latest_bars(["AAPL"], bar_builder=bar_builder)

        bars = asyncio.run(run())
        self.assertEqual(bars["AAPL"]["latest_price"], 100.5)


if __name__ == "__main__":
    unittest.main()
