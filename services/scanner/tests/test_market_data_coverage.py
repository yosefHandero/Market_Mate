import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.clients.alpaca import AlpacaClient
from app.config import Settings
from app.http_client import ProviderRequestError
from app.db import Base
from app.models.scan import ScanRunORM, SignalOutcomeORM
from app.schemas import ScanResult, ScanRun
from app.services.repository import ScanRepository
import app.services.repository as repository_module
from app.services.scan_coverage import build_scan_coverage
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


class StockFeedFallbackTests(unittest.TestCase):
    observed_at = datetime(2026, 11, 9, 15, 30, tzinfo=timezone.utc)

    @classmethod
    def _item(cls, age: int) -> dict:
        return {"latest_price": 100, "latest_volume": 100, "average_volume": 100,
                "bars": [{"t": cls.observed_at - timedelta(minutes=age + 5 * offset)}
                         for offset in range(5, -1, -1)]}

    def _service(self) -> ScannerService:
        service = ScannerService()
        service.settings = Settings(_env_file=None, polygon_api_key="fixture", polygon_intraday_fallback_enabled=False)
        service.alpaca.get_latest_bars = AsyncMock()
        service.alpaca.get_latest_stock_sip_bars = AsyncMock()
        service.polygon.get_latest_bars = AsyncMock()
        return service

    def test_sip_covers_only_missing_or_stale_iex_rows(self):
        service = self._service()
        service.alpaca.get_latest_bars.return_value = {"AAPL": self._item(60), "QQQ": self._item(5)}
        service.alpaca.get_latest_stock_sip_bars.return_value = {"AAPL": self._item(20), "SPY": self._item(65)}
        bars, _ = asyncio.run(service._get_stock_bars_with_fallback(["AAPL", "QQQ", "SPY"], observed_at=self.observed_at))
        service.alpaca.get_latest_stock_sip_bars.assert_awaited_once_with(["AAPL", "SPY"], timeframe="5Min")
        service.polygon.get_latest_bars.assert_not_awaited()
        self.assertEqual(set(bars), {"AAPL", "QQQ"})
        self.assertEqual(bars["AAPL"]["_market_bars_source"], "alpaca_sip")
        self.assertEqual(bars["AAPL"]["_market_bars_attempts"]["primary_status"], "stale")
        self.assertEqual(bars["QQQ"]["_market_bars_source"], "alpaca_iex")

    def test_sip_replaces_unusable_volume_reference(self):
        service = self._service()
        service.alpaca.get_latest_bars.return_value = {"AAPL": {**self._item(5), "average_volume": 0}}
        service.alpaca.get_latest_stock_sip_bars.return_value = {"AAPL": self._item(20)}
        bars, _ = asyncio.run(service._get_stock_bars_with_fallback(["AAPL"], observed_at=self.observed_at))
        self.assertEqual(bars["AAPL"]["_market_bars_source"], "alpaca_sip")
        self.assertEqual(bars["AAPL"]["_market_bars_attempts"]["primary_status"], "unusable")

    def test_fallback_does_not_turn_primary_outage_into_empty_success(self):
        service = self._service()
        service.settings.polygon_intraday_fallback_enabled = True
        primary_error = ProviderRequestError("down", provider="alpaca", url="fixture", status_code=503)
        service.alpaca.get_latest_bars.side_effect = primary_error
        service.polygon.get_latest_bars.return_value = {}
        with self.assertRaises(ProviderRequestError) as raised:
            asyncio.run(service._get_stock_bars_with_fallback(["AAPL"], observed_at=self.observed_at))
        self.assertIs(raised.exception, primary_error)
        service.alpaca.get_latest_stock_sip_bars.assert_not_awaited()

    def test_no_sip_retry_during_weekend_closure(self):
        service = self._service()
        service.alpaca.get_latest_bars.return_value = {"AAPL": {"bars": [{"t": "2026-11-06T20:55:00Z"}]}}
        bars, _ = asyncio.run(service._get_stock_bars_with_fallback(
            ["AAPL"], observed_at=datetime(2026, 11, 8, 15, 30, tzinfo=timezone.utc)))
        self.assertIn("AAPL", bars)
        service.alpaca.get_latest_stock_sip_bars.assert_not_awaited()
        service.polygon.get_latest_bars.assert_not_awaited()

    def test_paper_stock_quote_can_use_fresh_sip_but_crypto_requires_fresh_bars(self):
        now = datetime.now(timezone.utc)
        client = AlpacaClient()
        old = {"AAPL": {"latest_price": 100, "bars": [{"t": now - timedelta(hours=3)}]}}
        fresh = {"AAPL": {"latest_price": 101, "bars": [{"t": now - timedelta(minutes=20)}]}}
        client.get_latest_bars = AsyncMock(return_value=old)
        client.get_latest_stock_sip_bars = AsyncMock(return_value=fresh)
        client.get_latest_crypto_bars = AsyncMock(return_value={"BTC/USD": old["AAPL"]})
        with patch("app.clients.alpaca.stock_iex_session_is_open", return_value=True):
            self.assertEqual(asyncio.run(client.get_latest_price("AAPL")), 101)
        with self.assertRaisesRegex(RuntimeError, "stale"):
            asyncio.run(client.get_latest_crypto_price("BTC/USD"))

    def test_alpaca_sip_request_uses_delayed_window_and_separate_cache(self):
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append((request.url.path, request.url.params))
            end = request.url.params["end"]
            return httpx.Response(200, json={"bars": {"AAPL": [{"t": end, "o": 100, "h": 101, "l": 99, "c": 100, "v": 10}]}})

        async def exercise() -> None:
            settings = Settings(_env_file=None, alpaca_api_key="fixture", alpaca_api_secret="fixture")
            with patch("app.clients.alpaca.get_settings", return_value=settings):
                client = AlpacaClient()
            await client._async_client.aclose()
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as session:
                client._async_client = session
                await client.get_latest_bars(["AAPL"])
                await client.get_latest_stock_sip_bars(["AAPL"])
                await client.get_latest_stock_sip_bars(["AAPL"])

        asyncio.run(exercise())

        self.assertEqual([(path, params["feed"]) for path, params in requests], [("/v2/stocks/bars", "iex"), ("/v2/stocks/bars", "sip")])
        iex, sip = (params for _, params in requests)
        self.assertEqual(iex["adjustment"], sip["adjustment"])
        self.assertGreater(datetime.fromisoformat(iex["end"]) - datetime.fromisoformat(sip["end"]), timedelta(minutes=15))


class PartialScanProviderTests(unittest.TestCase):
    @staticmethod
    def _benchmark_item(age_minutes=5):
        return {"latest_price": 101, "session_open": 100, "day_open": 100,
                "bars": [{"t": datetime.now(timezone.utc) - timedelta(minutes=age_minutes)}]}

    def _service(self):
        service = ScannerService()
        service.settings = Settings(_env_file=None, watchlist="AAPL", crypto_watchlist="BTC/USD", weekly_primary_horizon_enabled=False)
        service.refresh_due_signal_outcomes = AsyncMock(return_value=0)
        service.refresh_due_prediction_snapshots = AsyncMock(return_value=0)
        service._get_stock_bars_with_fallback = AsyncMock(return_value=(
            {ticker: self._benchmark_item() for ticker in ("AAPL", "SPY", "QQQ")}, "alpaca",
        ))
        service.alpaca.get_latest_stock_sip_bars = AsyncMock(return_value={})
        service.alpaca.get_latest_crypto_bars = AsyncMock(return_value={"BTC/USD": self._benchmark_item()})
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

    def test_stale_crypto_cache_is_not_attributed_to_stock_bars(self):
        service = self._service()
        service._get_stock_bars_with_fallback = ScannerService._get_stock_bars_with_fallback.__get__(service)
        service.alpaca.get_latest_bars = AsyncMock(return_value={ticker: self._benchmark_item() for ticker in ("AAPL", "SPY", "QQQ")})
        crypto_key = service.alpaca._latest_cache_key("crypto", ["BTC/USD"], "5Min")
        service.alpaca._guard.last_served_stale_for = MagicMock(side_effect=lambda key: key == crypto_key)
        service._analyze_ticker = AsyncMock(wraps=service._analyze_ticker)

        asyncio.run(service.run_scan())

        by_asset = {call.kwargs["asset_type"]: call.kwargs for call in service._analyze_ticker.await_args_list}
        self.assertFalse(by_asset["stock"]["alpaca_served_stale_cache"])
        self.assertTrue(by_asset["crypto"]["alpaca_served_stale_cache"])

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
                coverage = next(row for row in run.coverage if row.asset_type == failed_asset)
                self.assertEqual(coverage.status, "unavailable")
                self.assertEqual(coverage.missing_symbols[0].reason, "provider_unavailable")
                self.assertIn("503", coverage.missing_symbols[0].detail)
                service.repo.save_run.assert_called_once()

    def test_missing_symbol_and_benchmark_reasons_do_not_change_returned_decisions(self):
        service = self._service()
        service.settings.watchlist = "AAPL,MSFT,SPY"
        service._get_stock_bars_with_fallback.return_value = (
            {ticker: self._benchmark_item() for ticker in ("AAPL", "SPY", "QQQ")}, "alpaca",
        )
        analyze = service._analyze_ticker

        async def analyze_with_benchmark(**kwargs):
            return None if kwargs["ticker"] == "SPY" else await analyze(**kwargs)

        service._analyze_ticker = analyze_with_benchmark
        run = asyncio.run(service.run_scan())
        stock = next(row for row in run.coverage if row.asset_type == "stock")
        self.assertEqual(stock.expected_symbols, ["AAPL", "MSFT", "SPY"])
        self.assertEqual(stock.returned_symbols, ["AAPL"])
        self.assertEqual(stock.status, "partial")
        self.assertEqual({row.ticker: row.reason for row in stock.missing_symbols},
                         {"MSFT": "market_data_missing", "SPY": "benchmark_only"})
        self.assertEqual([row.ticker for row in run.results], ["AAPL", "BTC/USD"])

    def test_all_market_providers_failed_does_not_persist_empty_success(self):
        service = self._service()
        error = ProviderRequestError("rate limited", provider="alpaca", url="test", retryable=True, status_code=429)
        service._get_stock_bars_with_fallback.side_effect = error
        service.alpaca.get_latest_crypto_bars.side_effect = error
        with self.assertRaises(ProviderRequestError):
            asyncio.run(service.run_scan())
        service.repo.save_run.assert_not_called()

    def test_intraday_benchmarks_are_requested_even_outside_watchlists(self):
        service = self._service()
        service.settings.crypto_watchlist = "ETH/USD"
        stock = {ticker: self._benchmark_item() for ticker in ("AAPL", "SPY", "QQQ")}
        crypto = {ticker: self._benchmark_item() for ticker in ("ETH/USD", "BTC/USD")}
        service._get_stock_bars_with_fallback.return_value = (stock, "alpaca")
        service.alpaca.get_latest_crypto_bars.return_value = crypto
        run = asyncio.run(service._run_scan())
        self.assertEqual(service._get_stock_bars_with_fallback.await_args.args[0], ["AAPL", "SPY", "QQQ"])
        service.alpaca.get_latest_crypto_bars.assert_awaited_once_with(["ETH/USD", "BTC/USD"])
        self.assertEqual({row.ticker for row in run.results}, {"AAPL", "ETH/USD"})
        self.assertEqual(run.watchlist_size, 2)

    def test_missing_required_benchmark_prevents_scoring_affected_candidates(self):
        service = self._service()
        service.settings.crypto_watchlist = "ETH/USD"
        service._get_stock_bars_with_fallback.return_value = ({"AAPL": self._benchmark_item(), "SPY": self._benchmark_item()}, "alpaca")
        service.alpaca.get_latest_crypto_bars.return_value = {"ETH/USD": self._benchmark_item()}
        service._analyze_ticker = AsyncMock(side_effect=AssertionError("unscoreable candidates should be skipped"))
        run = asyncio.run(service._run_scan())
        self.assertEqual(run.results, [])
        self.assertEqual(run.market_status, "unavailable")
        self.assertIn("QQQ", run.coverage[0].missing_symbols[0].detail)
        self.assertIn("BTC/USD", run.coverage[1].missing_symbols[0].detail)


class ScanCoveragePersistenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_engine(f"sqlite:///{(Path(directory.name) / 'coverage.db').as_posix()}")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.repo = ScanRepository()
        self.repo.settings = Settings(_env_file=None)
        for name, value in (("SessionLocal", self.sessions), ("engine", self.engine)):
            patched = patch.object(repository_module, name, value)
            patched.start()
            self.addCleanup(patched.stop)

    def _api_payload(self):
        from app.api.public import protected_router, require_schema_ready
        from app.auth import require_read_access
        from app.dependencies import get_scanner_service

        service = ScannerService.__new__(ScannerService)
        service.repo = self.repo
        app = FastAPI()
        app.include_router(protected_router)
        app.dependency_overrides[require_read_access] = lambda: None
        app.dependency_overrides[require_schema_ready] = lambda: None
        app.dependency_overrides[get_scanner_service] = lambda: service
        with TestClient(app) as client:
            response = client.get("/scan/latest")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_saved_scan_coverage_survives_database_and_api_round_trip(self):
        service = PartialScanProviderTests()._service()
        service._get_stock_bars_with_fallback.side_effect = ProviderRequestError(
            "temporary failure", provider="alpaca", url="test", retryable=True, status_code=503,
        )
        run = asyncio.run(service.run_scan())
        self.repo.save_run(run)
        expected = [row.model_dump(mode="json") for row in run.coverage]
        self.assertEqual(self._api_payload()["coverage"], expected)
        self.assertEqual(self.repo.get_run_history()[0].coverage, run.coverage)
        with self.sessions() as session:
            self.assertIsNotNone(session.execute(select(ScanRunORM)).scalar_one().coverage_json)

    def test_legacy_scan_coverage_remains_unknown_in_database_and_api(self):
        # A count shortfall alone cannot establish which symbols or why.
        run = ScanRun(
            run_id="legacy-coverage", created_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
            market_status="neutral", scan_count=0, watchlist_size=69, results=[],
        )
        self.repo.save_run(run)
        self.assertIsNone(self._api_payload()["coverage"])
        self.assertIsNone(self.repo.get_run_history()[0].coverage)
        with self.sessions() as session:
            self.assertIsNone(session.execute(select(ScanRunORM)).scalar_one().coverage_json)

    def test_subpenny_scan_price_remains_usable_for_hourly_outcome(self):
        service = ScannerService()
        service.settings = Settings(_env_file=None, weekly_primary_horizon_enabled=False)
        service.repo = self.repo
        self.repo.settings.track_hold_outcomes = True
        service.weekly_prediction_service.build_weekly_prediction = AsyncMock(return_value=None)
        service._gate_signal = MagicMock(return_value=(0, "raw", False, "Fixture evidence", [], {}))
        observed_at = datetime.now(timezone.utc)
        entry = 0.000001
        exit_price = 0.0000011
        item = {"latest_price": entry, "session_open": entry, "latest_volume": 100, "average_volume": 100,
                "rolling_high": entry, "rolling_low": entry, "vwap": entry,
                "bars": [{"t": observed_at, "c": entry, "h": entry, "l": entry}] * 6}
        row = asyncio.run(service._analyze_ticker(
            ticker="PEPE/USD", asset_type="crypto", item=item, market_status="neutral",
            benchmark_ticker="BTC/USD", benchmark_change_pct=0, created_at=observed_at,
        ))
        run = ScanRun(run_id="subpenny-fixture", created_at=observed_at, market_status="neutral",
                      scan_count=1, watchlist_size=1, results=[row])
        self.repo.save_run(run)
        service.alpaca.get_crypto_price_on_or_after_timestamp = AsyncMock(return_value=exit_price)
        asyncio.run(service._refresh_due_signal_outcomes(observed_at=observed_at + timedelta(minutes=65)))

        self.assertEqual(self.repo.get_latest_run().results[0].price, entry)
        with self.sessions() as session:
            outcome = session.execute(select(SignalOutcomeORM)).scalar_one()
            self.assertEqual(outcome.entry_price, entry)
            self.assertEqual(outcome.price_after_1h, exit_price)
            self.assertEqual(outcome.status_1h, "resolved")
            self.assertEqual(outcome.return_after_1h, 10)

    def test_zero_volume_reference_is_not_substituted_or_scored(self):
        service = ScannerService()
        service._get_directional_sentiment = AsyncMock()
        observed_at = datetime(2026, 11, 10, 15, tzinfo=timezone.utc)
        rows = []
        for days_back, volume in ((1, 0), (0, 500)):
            for minutes_back in range(25, -1, -5):
                timestamp = observed_at - timedelta(days=days_back, minutes=minutes_back)
                rows.append({"t": timestamp.isoformat(), "o": 10, "c": 10, "h": 10, "l": 10, "v": volume})
        data = service.alpaca._build_bars_by_symbol({"bars": {"POL/USD": rows}})
        self.assertEqual(data["POL/USD"]["average_volume"], 0)
        blocked_inputs = {}
        result = asyncio.run(service._analyze_ticker(
            ticker="POL/USD", asset_type="crypto", item=data["POL/USD"], market_status="neutral",
            benchmark_ticker="BTC/USD", benchmark_change_pct=0, created_at=observed_at,
            blocked_inputs=blocked_inputs,
        ))
        self.assertIsNone(result)
        service._get_directional_sentiment.assert_not_awaited()
        coverage = build_scan_coverage(asset_type="crypto", expected_symbols=["POL/USD"], market_data=data,
                                       provider_error=None, results=[], blocked_inputs=blocked_inputs)
        self.assertEqual(coverage.missing_symbols[0].required_input, "volume_reference")
        self.assertIn("No positive reference volume", coverage.missing_symbols[0].detail)
