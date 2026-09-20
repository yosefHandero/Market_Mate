import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.clients.alpaca import AlpacaClient
from app.config import Settings
from app.http_client import ProviderRequestError
from app.schemas import ScanResult
from app.services.scanner import ScannerService


class StockClosureCoverageTests(unittest.TestCase):
    def test_missing_symbols_retry_once_without_replacing_available_bars(self):
        client = AlpacaClient.__new__(AlpacaClient)
        recent = [{"t": "2026-09-08T14:00:00Z", "o": 10, "h": 12, "l": 9, "c": 11, "v": 100}]
        older = [{"t": "2026-09-04T19:55:00Z", "o": 20, "h": 22, "l": 19, "c": 21, "v": 100}]
        client._fetch_stock_bars = AsyncMock(side_effect=[
            {"bars": {"AAPL": recent}}, {"bars": {"MSFT": older}}
        ])
        result = asyncio.run(client._get_latest_bars_uncached(symbols=["AAPL", "MSFT"], timeframe="5Min"))
        self.assertEqual(set(result), {"AAPL", "MSFT"})
        self.assertEqual(result["AAPL"], client._build_bars_by_symbol({"bars": {"AAPL": recent}})["AAPL"])
        first, retry = client._fetch_stock_bars.await_args_list
        self.assertEqual(retry.kwargs["symbols"], ["MSFT"])
        self.assertEqual(retry.kwargs["end"], first.kwargs["end"])
        self.assertGreater(first.kwargs["start"], retry.kwargs["start"])
        self.assertLessEqual(retry.kwargs["end"] - retry.kwargs["start"], timedelta(days=10))
        self.assertEqual(result["MSFT"]["bars"], older)  # Actual old timestamps remain stale.

    def test_no_data_after_retry_stays_absent(self):
        client = AlpacaClient.__new__(AlpacaClient)
        client._fetch_stock_bars = AsyncMock(return_value={"bars": {}})
        self.assertEqual(asyncio.run(client._get_latest_bars_uncached(symbols=["AAPL"], timeframe="5Min")), {})
        self.assertEqual(client._fetch_stock_bars.await_count, 2)


class PartialScanProviderTests(unittest.TestCase):
    def _service(self):
        service = ScannerService()
        service.settings = Settings(_env_file=None, watchlist="AAPL", crypto_watchlist="BTC/USD", weekly_primary_horizon_enabled=False)
        service.refresh_due_signal_outcomes = AsyncMock(return_value=0)
        service.refresh_due_prediction_snapshots = AsyncMock(return_value=0)
        service._get_stock_bars_with_fallback = AsyncMock(return_value=({"AAPL": {}}, "alpaca"))
        service.alpaca.get_latest_crypto_bars = AsyncMock(return_value={"BTC/USD": {}})
        service.market_data_service.apply_crypto_price_overrides = lambda rows: rows
        service.fear_greed.get_index = AsyncMock(return_value=(50, "Neutral"))
        service.coingecko.get_market_context = AsyncMock(return_value={})
        service._compute_market_status = MagicMock(return_value=("neutral", 0.0, 0.0))
        service.brain = MagicMock()
        service.brain.effective_champion_id.return_value = "hybrid_legacy"
        service.brain.decide_all.return_value = {}
        service.brain.hybrid.fingerprint.return_value = "test-fingerprint"
        service.brain.hybrid.policy_version = "hybrid-v4.2"
        service.brain.refresh_weekly_inputs.return_value = SimpleNamespace(fingerprint="artifact", identity_json=lambda: "{}")
        service.repo.save_run = MagicMock()
        service.alerts.dispatch_for_run = AsyncMock()

        async def analyze(**kwargs):
            if kwargs["item"] is None:
                return None
            return ScanResult(ticker=kwargs["ticker"], asset_type=kwargs["asset_type"], score=40,
                              decision_signal="HOLD", explanation="fixture", price=100,
                              price_change_pct=0, relative_volume=1, sentiment_score=0,
                              filing_flag=False, breakout_flag=False, market_status="neutral",
                              sector_strength_score=0, relative_strength_pct=0,
                              created_at=datetime(2026, 9, 20, tzinfo=timezone.utc))
        service._analyze_ticker = analyze
        return service

    def test_one_asset_provider_failure_preserves_other_asset_and_reports_partial_count(self):
        for failed_asset in ("stock", "crypto"):
            with self.subTest(failed_asset=failed_asset):
                service = self._service()
                error = ProviderRequestError("temporary failure", provider="alpaca", url="test", retryable=True, status_code=503)
                failed = service._get_stock_bars_with_fallback if failed_asset == "stock" else service.alpaca.get_latest_crypto_bars
                failed.side_effect = error
                run = asyncio.run(service.run_scan())
                self.assertEqual(run.watchlist_size, 2)
                self.assertEqual(run.scan_count, 1)
                self.assertNotEqual(run.results[0].asset_type, failed_asset)
                service.repo.save_run.assert_called_once()

    def test_all_market_providers_failed_does_not_persist_empty_success(self):
        service = self._service()
        error = ProviderRequestError("rate limited", provider="alpaca", url="test", retryable=True, status_code=429)
        service._get_stock_bars_with_fallback.side_effect = error
        service.alpaca.get_latest_crypto_bars.side_effect = error
        with self.assertRaises(ProviderRequestError):
            asyncio.run(service.run_scan())
        service.repo.save_run.assert_not_called()
