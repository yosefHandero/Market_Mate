import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock

if "yahooquery" not in sys.modules:
    yahooquery_stub = types.ModuleType("yahooquery")
    yahooquery_stub.Ticker = object
    sys.modules["yahooquery"] = yahooquery_stub

from app.schemas import GateCheck, ScanResult
from app.services.scanner import ScannerService


class ScannerServiceHardeningTests(unittest.TestCase):
    def test_gate_signal_uses_shared_evidence_evaluator(self) -> None:
        service = ScannerService()
        service.repo.calibrate_signal = MagicMock(return_value=(72.0, "60-69", "signal"))
        checks = [GateCheck(name="sample_size", passed=True, detail="20 vs 20")]
        service.repo.evaluate_signal_gate = MagicMock(
            return_value=SimpleNamespace(
                passed=True,
                reason="Shared gate passed.",
                checks=checks,
            )
        )

        gated = service._gate_signal(
            asset_type="stock",
            signal=SimpleNamespace(decision_signal="BUY", score=68.0),
        )

        self.assertEqual(gated, (72.0, "signal", True, "Shared gate passed.", checks))
        service.repo.evaluate_signal_gate.assert_called_once_with(
            asset_type="stock",
            signal="BUY",
            score_band="60-69",
            horizon=service.settings.trade_gate_horizon,
            observed_at=None,
        )

    def test_run_scan_persists_results_even_when_alert_dispatch_fails(self) -> None:
        service = ScannerService()
        original_watchlist = service.settings.watchlist
        original_crypto_watchlist = service.settings.crypto_watchlist
        service.settings.watchlist = "AAPL"
        service.settings.crypto_watchlist = ""
        self.addCleanup(setattr, service.settings, "watchlist", original_watchlist)
        self.addCleanup(setattr, service.settings, "crypto_watchlist", original_crypto_watchlist)

        service._refresh_due_signal_outcomes = AsyncMock(return_value=0)
        service.alpaca.get_latest_bars = AsyncMock(return_value={"AAPL": {}})
        service.fear_greed.get_index = AsyncMock(return_value=(50, "neutral"))
        service._compute_market_status = MagicMock(return_value=("neutral", 0.0, 0.0))
        service._analyze_ticker = AsyncMock(
            return_value=ScanResult(
                ticker="AAPL",
                asset_type="stock",
                score=82.0,
                calibrated_confidence=82.0,
                calibration_source="raw",
                buy_score=82.0,
                sell_score=20.0,
                decision_signal="BUY",
                scoring_version="v2.1-regime-gated",
                explanation="Test setup.",
                price=100.0,
                price_change_pct=1.2,
                relative_volume=2.1,
                sentiment_score=0.3,
                filing_flag=False,
                breakout_flag=True,
                market_status="neutral",
                sector_strength_score=6.0,
                relative_strength_pct=1.1,
                options_flow_score=7.0,
                options_flow_summary="Test flow.",
                options_flow_bullish=True,
                options_call_put_ratio=0.8,
                alert_sent=False,
                news_checked=True,
                news_source="marketaux+finnhub",
                news_cache_label="Fresh directional news check",
                signal_label="strong",
                data_quality="ok",
                volatility_regime="normal",
                benchmark_ticker="SPY/QQQ",
                benchmark_change_pct=0.4,
                gate_passed=True,
                gate_reason="Passed.",
                gate_checks=[],
                coingecko_price_change_pct_24h=None,
                coingecko_market_cap_rank=None,
                fear_greed_value=50,
                fear_greed_label="neutral",
                created_at=datetime.now(timezone.utc),
            )
        )
        service.alerts.dispatch_for_run = AsyncMock(side_effect=RuntimeError("telegram unavailable"))
        service.repo.save_run = MagicMock()

        run = asyncio.run(service.run_scan())

        self.assertEqual(run.scan_count, 1)
        self.assertEqual(run.alerts_sent, 0)
        service.repo.save_run.assert_called_once()

    def test_provider_health_marks_placeholder_sec_user_agent_as_degraded(self) -> None:
        service = ScannerService()
        original_user_agent = service.settings.sec_user_agent
        service.settings.sec_user_agent = "MarketMateScanner your-email@example.com"
        self.addCleanup(setattr, service.settings, "sec_user_agent", original_user_agent)

        provider_status, warnings = service._provider_health(
            asset_type="stock",
            item={"bars": [{"t": datetime.now(timezone.utc).isoformat()}]},
            observed_at=datetime.now(timezone.utc),
            data_quality="ok",
            fear_greed_value=None,
            coingecko_context=None,
            options_snapshot=SimpleNamespace(summary="Options flow unavailable."),
            news_warnings=[],
        )

        self.assertEqual(provider_status, "degraded")
        self.assertIn("sec_user_agent_placeholder", warnings)
        self.assertIn("options_flow_unavailable", warnings)

    def test_provider_health_is_ok_when_required_inputs_are_present(self) -> None:
        service = ScannerService()
        original_user_agent = service.settings.sec_user_agent
        service.settings.sec_user_agent = "MarketMateScanner trader@example.com"
        self.addCleanup(setattr, service.settings, "sec_user_agent", original_user_agent)

        provider_status, warnings = service._provider_health(
            asset_type="crypto",
            item={"bars": [{"t": datetime.now(timezone.utc).isoformat()}]},
            observed_at=datetime.now(timezone.utc),
            data_quality="ok",
            fear_greed_value=55,
            coingecko_context={"market_cap_change_pct_24h": 1.2},
            options_snapshot=SimpleNamespace(summary="Not applicable for crypto."),
            news_warnings=[],
        )

        self.assertEqual(provider_status, "ok")
        self.assertEqual(warnings, [])

    def test_run_scan_overlays_coinbase_crypto_prices_when_available(self) -> None:
        market_data_service = MagicMock()
        market_data_service.apply_crypto_price_overrides.return_value = {
            "BTC/USD": {
                "latest_price": 68000.0,
                "latest_volume": 10.0,
                "average_volume": 5.0,
                "day_open": 67000.0,
                "session_open": 67000.0,
                "session_high": 68100.0,
                "session_low": 66500.0,
                "rolling_high": 68200.0,
                "rolling_low": 65000.0,
                "previous_close": 66950.0,
                "vwap": 67500.0,
                "session_bar_index": 1,
                "bars": [{"t": datetime.now(timezone.utc).isoformat(), "c": 67050.0}],
            }
        }
        service = ScannerService(market_data_service=market_data_service)
        original_watchlist = service.settings.watchlist
        original_crypto_watchlist = service.settings.crypto_watchlist
        service.settings.watchlist = ""
        service.settings.crypto_watchlist = "BTC/USD"
        self.addCleanup(setattr, service.settings, "watchlist", original_watchlist)
        self.addCleanup(setattr, service.settings, "crypto_watchlist", original_crypto_watchlist)

        service._refresh_due_signal_outcomes = AsyncMock(return_value=0)
        service.alpaca.get_latest_crypto_bars = AsyncMock(
            return_value={
                "BTC/USD": {
                    "latest_price": 67000.0,
                    "latest_volume": 9.0,
                    "average_volume": 5.0,
                    "day_open": 66000.0,
                    "session_open": 66000.0,
                    "session_high": 67100.0,
                    "session_low": 65500.0,
                    "rolling_high": 67200.0,
                    "rolling_low": 65000.0,
                    "previous_close": 65950.0,
                    "vwap": 66500.0,
                    "session_bar_index": 1,
                    "bars": [{"t": datetime.now(timezone.utc).isoformat(), "c": 67000.0}],
                }
            }
        )
        service.fear_greed.get_index = AsyncMock(return_value=(55, "neutral"))
        service.coingecko.get_market_context = AsyncMock(return_value={"BTC/USD": {}})
        service._compute_market_status = MagicMock(return_value=("neutral", 0.0, 0.0))
        service._analyze_ticker = AsyncMock(
            side_effect=lambda **kwargs: ScanResult(
                ticker=kwargs["ticker"],
                asset_type=kwargs["asset_type"],
                score=82.0,
                calibrated_confidence=82.0,
                calibration_source="raw",
                buy_score=82.0,
                sell_score=20.0,
                decision_signal="BUY",
                scoring_version="v2.1-regime-gated",
                explanation="Test setup.",
                price=kwargs["item"]["latest_price"],
                price_change_pct=1.2,
                relative_volume=2.1,
                sentiment_score=0.3,
                filing_flag=False,
                breakout_flag=True,
                market_status="neutral",
                sector_strength_score=6.0,
                relative_strength_pct=1.1,
                options_flow_score=0.0,
                options_flow_summary="Not applicable for crypto.",
                options_flow_bullish=False,
                options_call_put_ratio=0.0,
                alert_sent=False,
                news_checked=True,
                news_source="marketaux+finnhub",
                news_cache_label="Fresh directional news check",
                signal_label="strong",
                data_quality="ok",
                volatility_regime="normal",
                benchmark_ticker="BTC/USD",
                benchmark_change_pct=0.4,
                gate_passed=True,
                gate_reason="Passed.",
                gate_checks=[],
                coingecko_price_change_pct_24h=None,
                coingecko_market_cap_rank=None,
                fear_greed_value=55,
                fear_greed_label="neutral",
                created_at=datetime.now(timezone.utc),
            )
        )
        service.alerts.dispatch_for_run = AsyncMock(return_value=None)
        service.repo.save_run = MagicMock()

        run = asyncio.run(service.run_scan())

        market_data_service.apply_crypto_price_overrides.assert_called_once()
        self.assertEqual(run.results[0].price, 68000.0)
        service.repo.save_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
