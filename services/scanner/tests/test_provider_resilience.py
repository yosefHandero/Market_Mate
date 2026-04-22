import asyncio
from types import SimpleNamespace
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

if "yahooquery" not in sys.modules:
    yahooquery_stub = types.ModuleType("yahooquery")
    yahooquery_stub.Ticker = object
    sys.modules["yahooquery"] = yahooquery_stub

from app.clients.binance import BinanceClient
from app.clients.coingecko import CoinGeckoClient
from app.clients.defillama import DefiLlamaClient
from app.clients.deribit import DeribitClient
from app.clients.fred import FREDClient
from app.clients.options_flow import OptionsFlowClient
from app.clients.sec import SECClient
from app.http_client import request_json
from app.schemas import OptionsFlowSnapshot


class HttpClientResilienceTests(unittest.TestCase):
    def test_request_json_retries_html_block_page_then_succeeds(self) -> None:
        client = MagicMock()
        client.request = AsyncMock(
            side_effect=[
                httpx.Response(
                    200,
                    headers={"content-type": "text/html"},
                    text="<html><body>Access denied</body></html>",
                ),
                httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json={"ok": True},
                ),
            ]
        )

        async def run() -> dict:
            with patch("app.http_client.get_settings") as mocked_settings:
                mocked_settings.return_value = SimpleNamespace(
                    provider_retry_attempts=1,
                    provider_retry_backoff_seconds=0.0,
                )
                return await request_json(client, method="GET", url="https://example.com/data", provider="test")

        payload = asyncio.run(run())
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(client.request.await_count, 2)


class ProviderCacheTests(unittest.TestCase):
    def test_sec_client_caches_company_mapping_and_filings(self) -> None:
        client = SECClient()
        mapping_payload = {"0": {"ticker": "AAPL", "cik_str": 320193}}
        filings_payload = {"filings": {"recent": {"form": ["8-K", "10-Q"]}}}
        company_facts_payload = {"facts": {"us-gaap": {}}}

        async def run() -> tuple[float, float]:
            with patch(
                "app.clients.sec.request_json",
                AsyncMock(side_effect=[mapping_payload, filings_payload, company_facts_payload]),
            ) as mocked_request:
                first = await client.get_recent_catalyst_score("AAPL")
                second = await client.get_recent_catalyst_score("AAPL")
                self.assertEqual(mocked_request.await_count, 3)
                return first, second

        first_score, second_score = asyncio.run(run())
        self.assertEqual(first_score, 0.45)
        self.assertEqual(second_score, 0.45)

    def test_coingecko_client_returns_stale_context_when_refresh_fails(self) -> None:
        client = CoinGeckoClient()
        original_cache_seconds = client.settings.coingecko_cache_seconds
        client.settings.coingecko_cache_seconds = 0
        self.addCleanup(setattr, client.settings, "coingecko_cache_seconds", original_cache_seconds)

        async def run() -> tuple[dict, dict]:
            with patch(
                "app.clients.coingecko.request_json",
                AsyncMock(
                    side_effect=[
                        [
                            {
                                "id": "bitcoin",
                                "market_cap_rank": 1,
                                "price_change_percentage_24h_in_currency": 2.5,
                                "market_cap_change_percentage_24h": 1.25,
                            }
                        ],
                        RuntimeError("provider unavailable"),
                    ]
                ),
            ) as mocked_request:
                first = await client.get_market_context(["BTC/USD"])
                second = await client.get_market_context(["BTC/USD"])
                self.assertEqual(mocked_request.await_count, 2)
                return first, second

        first_payload, second_payload = asyncio.run(run())
        self.assertEqual(first_payload["BTC/USD"]["market_cap_rank"], 1)
        self.assertEqual(second_payload, first_payload)

    def test_options_flow_deduplicates_concurrent_identical_requests(self) -> None:
        client = OptionsFlowClient()
        snapshot = OptionsFlowSnapshot(summary="Cached snapshot.", bullish_score=1.0, bearish_score=0.5)

        async def run() -> list[OptionsFlowSnapshot]:
            with patch.object(client, "_get_flow_snapshot_sync", return_value=snapshot) as mocked_sync:
                results = await asyncio.gather(
                    client.get_flow_snapshot("AAPL"),
                    client.get_flow_snapshot("AAPL"),
                )
                self.assertEqual(mocked_sync.call_count, 1)
                return results

        results = asyncio.run(run())
        self.assertEqual(results[0].summary, "Cached snapshot.")
        self.assertEqual(results[1].summary, "Cached snapshot.")

    def test_binance_client_normalizes_microstructure(self) -> None:
        client = BinanceClient()

        async def run():
            with patch(
                "app.clients.binance.request_json",
                AsyncMock(
                    side_effect=[
                        {"bidPrice": "100", "askPrice": "100.1"},
                        {"bids": [["100", "12"], ["99.9", "8"]], "asks": [["100.1", "5"], ["100.2", "5"]]},
                        [{"qty": "4", "isBuyerMaker": False}, {"qty": "1", "isBuyerMaker": True}],
                    ]
                ),
            ):
                _, snapshot = await client.get_microstructure("BTC/USD")
                return snapshot

        snapshot = asyncio.run(run())
        self.assertTrue(snapshot.available)
        self.assertGreater(snapshot.book_imbalance or 0.0, 0.0)
        self.assertGreater(snapshot.aggressor_pressure or 0.0, 0.0)

    def test_deribit_client_normalizes_positioning_context(self) -> None:
        client = DeribitClient()

        async def run():
            with patch(
                "app.clients.deribit.request_json",
                AsyncMock(
                    side_effect=[
                        {
                            "result": [
                                {
                                    "instrument_name": "BTC-PERPETUAL",
                                    "underlying_price": 100000,
                                    "mark_price": 101000,
                                    "open_interest": 1000,
                                }
                            ]
                        },
                        {
                            "result": [
                                {"instrument_name": "BTC-1APR24-C", "open_interest": 200, "mark_iv": 60},
                                {"instrument_name": "BTC-1APR24-P", "open_interest": 350, "mark_iv": 72},
                            ]
                        },
                    ]
                ),
            ):
                _, snapshot = await client.get_positioning("BTC/USD")
                return snapshot

        snapshot = asyncio.run(run())
        self.assertTrue(snapshot.available)
        self.assertGreater(snapshot.put_call_open_interest_ratio or 0.0, 1.0)
        self.assertIsNotNone(snapshot.crowding_score)

    def test_fred_client_builds_macro_regime_snapshot(self) -> None:
        client = FREDClient()
        csv_responses = [
            "DATE,VALUE\n2026-03-28,30\n",
            "DATE,VALUE\n2026-03-28,5.1\n",
            "DATE,VALUE\n2026-03-28,-0.4\n",
        ]

        async def run():
            with patch.object(
                client._client,
                "get",
                AsyncMock(side_effect=[SimpleNamespace(text=text, raise_for_status=lambda: None) for text in csv_responses]),
            ):
                return await client.get_macro_snapshot()

        snapshot = asyncio.run(run())
        self.assertTrue(snapshot.available)
        self.assertEqual(snapshot.regime, "risk_off")

    def test_defillama_client_builds_supportive_snapshot(self) -> None:
        client = DefiLlamaClient()

        async def run():
            with patch(
                "app.clients.defillama.request_json",
                AsyncMock(
                    side_effect=[
                        [{"change_7d": 8}, {"change_7d": -2}, {"change_7d": 5}],
                        {"totalCirculatingUSD": 110, "totalCirculatingUSDPrevWeek": 100},
                    ]
                ),
            ):
                return await client.get_macro_snapshot()

        snapshot = asyncio.run(run())
        self.assertTrue(snapshot.available)
        self.assertGreater(snapshot.supportive_score, 0.0)


if __name__ == "__main__":
    unittest.main()
