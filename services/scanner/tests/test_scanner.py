import asyncio
from datetime import datetime, timezone
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock

if "yahooquery" not in sys.modules:
    yahooquery_stub = types.ModuleType("yahooquery")
    yahooquery_stub.Ticker = object
    sys.modules["yahooquery"] = yahooquery_stub

from app.schemas import ScanResult
from app.services.scanner import ScannerService


class ScannerServiceHardeningTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
