from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from app.services.coinbase_market_data import CoinbaseMarketDataService


class CoinbaseMarketDataServiceTests(unittest.TestCase):
    def test_handle_ticker_message_updates_and_persists_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CoinbaseMarketDataService(
                client=MagicMock(
                    url="wss://advanced-trade-ws.coinbase.com",
                    channel="ticker",
                    product_ids=["BTC-USD", "ETH-USD"],
                )
            )
            original_cache_dir = service.settings.cache_dir
            service.settings.cache_dir = tmpdir
            self.addCleanup(setattr, service.settings, "cache_dir", original_cache_dir)

            service.handle_message(
                {
                    "channel": "ticker",
                    "sequence_num": 42,
                    "events": [
                        {
                            "type": "update",
                            "tickers": [
                                {"product_id": "BTC-USD", "price": "67123.45"},
                                {"product_id": "ETH-USD", "price": "3456.78"},
                            ],
                        }
                    ],
                }
            )

            btc_snapshot = service.get_snapshot_for_symbol("BTC/USD")
            eth_snapshot = service.get_snapshot_for_symbol("ETH/USD")

            self.assertIsNotNone(btc_snapshot)
            self.assertIsNotNone(eth_snapshot)
            self.assertEqual(btc_snapshot["price"], 67123.45)
            self.assertEqual(eth_snapshot["price"], 3456.78)
            self.assertTrue(service.snapshot_file_path.exists())

            payload = json.loads(service.snapshot_file_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["prices"]), 2)
            self.assertEqual(list(Path(tmpdir).glob("*.tmp")), [])

    def test_apply_crypto_price_overrides_updates_latest_price_only_for_fresh_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CoinbaseMarketDataService(
                client=MagicMock(
                    url="wss://advanced-trade-ws.coinbase.com",
                    channel="ticker",
                    product_ids=["BTC-USD", "ETH-USD"],
                )
            )
            original_cache_dir = service.settings.cache_dir
            service.settings.cache_dir = tmpdir
            self.addCleanup(setattr, service.settings, "cache_dir", original_cache_dir)

            service.handle_message(
                {
                    "channel": "ticker",
                    "sequence_num": 99,
                    "events": [
                        {
                            "type": "snapshot",
                            "tickers": [
                                {"product_id": "BTC-USD", "price": "68000.00"},
                            ],
                        }
                    ],
                }
            )

            updated = service.apply_crypto_price_overrides(
                {
                    "BTC/USD": {"latest_price": 67000.0, "session_open": 66000.0},
                    "SOL/USD": {"latest_price": 150.0, "session_open": 148.0},
                }
            )

            self.assertEqual(updated["BTC/USD"]["latest_price"], 68000.0)
            self.assertEqual(updated["SOL/USD"]["latest_price"], 150.0)
            self.assertEqual(updated["BTC/USD"]["coinbase_product_id"], "BTC-USD")

    def test_handle_ticker_message_ignores_older_sequence_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CoinbaseMarketDataService(
                client=MagicMock(
                    url="wss://advanced-trade-ws.coinbase.com",
                    channel="ticker",
                    product_ids=["BTC-USD"],
                )
            )
            original_cache_dir = service.settings.cache_dir
            service.settings.cache_dir = tmpdir
            self.addCleanup(setattr, service.settings, "cache_dir", original_cache_dir)

            service.handle_message(
                {
                    "channel": "ticker",
                    "sequence_num": 10,
                    "events": [
                        {
                            "type": "update",
                            "tickers": [
                                {"product_id": "BTC-USD", "price": "70000.00"},
                            ],
                        }
                    ],
                }
            )
            service.handle_message(
                {
                    "channel": "ticker",
                    "sequence_num": 9,
                    "events": [
                        {
                            "type": "update",
                            "tickers": [
                                {"product_id": "BTC-USD", "price": "69000.00"},
                            ],
                        }
                    ],
                }
            )

            snapshot = service.get_snapshot_for_symbol("BTC/USD")
            self.assertIsNotNone(snapshot)
            self.assertEqual(snapshot["price"], 70000.0)
            self.assertEqual(snapshot["sequence_num"], 10)
            self.assertTrue(service.snapshot_file_path.exists())
            self.assertEqual(list(Path(tmpdir).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
