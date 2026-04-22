from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import time
from uuid import uuid4

from app.clients.alpaca import AlpacaClient
from app.clients.binance import BinanceClient
from app.clients.coingecko import CoinGeckoClient
from app.clients.defillama import DefiLlamaClient
from app.clients.deribit import DeribitClient
from app.clients.fear_greed import FearGreedClient
from app.clients.finnhub import FinnhubClient
from app.clients.fred import FREDClient
from app.clients.options_flow import OptionsFlowClient
from app.clients.sec import SECClient
from app.clients.marketaux import MarketauxClient
from app.config import get_settings
from app.core.confidence import compute_confidence_overlay
from app.core.legacy_signals import compute_legacy_signal
from app.core.scoring import TREND_SMA_WINDOW, market_status_from_change
from app.core.signals import compute_signal_and_explanation
from app.core.strategy_contract import build_strategy_evaluation_metadata
from app.provider_models import (
    BinanceMicrostructureSnapshot,
    BreadthSnapshot,
    DefiLlamaSnapshot,
    DeribitPositioningSnapshot,
    FREDMacroSnapshot,
    SECCatalystSnapshot,
)
from app.schemas import GateCheck, OptionsFlowSnapshot, ScanRun, ScanResult, VariantComparison
from app.services.alerts import AlertService
from app.services.coinbase_market_data import CoinbaseMarketDataService
from app.services.repository import OutcomeEvaluationUpdate, PendingSignalOutcomeEvaluation, ScanRepository
from app.services.news_cache import NewsCacheService

logger = logging.getLogger(__name__)


class ScannerService:
    _OUTCOME_LOOKUP_CONFIG = {
        "15m": {"timeframe": "1Min", "max_search_minutes": 8 * 60},
        "1h": {"timeframe": "5Min", "max_search_minutes": 2 * 24 * 60},
        "1d": {"timeframe": "1Hour", "max_search_minutes": 5 * 24 * 60},
    }

    def __init__(
        self,
        *,
        market_data_service: CoinbaseMarketDataService | None = None,
    ) -> None:
        self.settings = get_settings()
        self.alpaca = AlpacaClient()
        self.binance = BinanceClient()
        self.coingecko = CoinGeckoClient()
        self.defillama = DefiLlamaClient()
        self.deribit = DeribitClient()
        self.fear_greed = FearGreedClient()
        self.finnhub = FinnhubClient()
        self.fred = FREDClient()
        self.marketaux = MarketauxClient()
        self.sec = SECClient()
        self.options_flow = OptionsFlowClient()
        self.news_cache = NewsCacheService()
        self.alerts = AlertService()
        self.repo = ScanRepository()
        self.market_data_service = market_data_service or CoinbaseMarketDataService()
        self.automation_service = None
        self._analyze_semaphore = asyncio.Semaphore(max(self.settings.scan_concurrency_limit, 1))

    def _volatility_regime(self, item: dict, price: float) -> str:
        bars = item.get("bars") or []
        if len(bars) < 8 or price <= 0:
            return "normal"
        avg_range_pct = sum(
            (
                (float(bar.get("h", 0) or 0) - float(bar.get("l", 0) or 0))
                / max(float(bar.get("c", 0) or price), 0.01)
            ) * 100
            for bar in bars[-8:]
        ) / min(len(bars[-8:]), 8)
        if avg_range_pct >= 2.75:
            return "extreme"
        if avg_range_pct >= 1.4:
            return "hot"
        if avg_range_pct <= 0.35:
            return "calm"
        return "normal"

    def _data_quality(self, item: dict, relative_volume: float) -> str:
        bars = item.get("bars") or []
        if len(bars) < 6 or float(item.get("average_volume") or 0) <= 0:
            return "low"
        if relative_volume > 12 or relative_volume <= 0:
            return "degraded"
        return "ok"

    @staticmethod
    def _compute_trend_signal(item: dict, price: float) -> tuple[bool, float]:
        bars = item.get("bars") or []
        closes = [
            float(bar.get("c", 0) or 0) for bar in bars[-TREND_SMA_WINDOW:]
            if float(bar.get("c", 0) or 0) > 0
        ]
        if len(closes) < TREND_SMA_WINDOW or price <= 0:
            return True, 0.0
        sma = sum(closes) / len(closes)
        if sma <= 0:
            return True, 0.0
        trend_strength_pct = (price - sma) / sma * 100
        return price >= sma, round(trend_strength_pct, 4)

    def _crypto_market_status(self, benchmark_change_pct: float, fear_greed_value: int | None) -> str:
        if benchmark_change_pct >= 1.0 or (fear_greed_value or 50) >= 65:
            return "bullish"
        if benchmark_change_pct <= -1.0 or (fear_greed_value or 50) <= 35:
            return "bearish"
        return "neutral"

    def _context_bias(
        self,
        *,
        asset_type: str,
        market_status: str,
        volatility_regime: str,
        fear_greed_value: int | None,
        coingecko_context: dict | None,
    ) -> float:
        bias = 0.15 if market_status == "bullish" else -0.15 if market_status == "bearish" else 0.0
        if volatility_regime == "extreme":
            bias *= 0.7
        if asset_type == "crypto":
            if fear_greed_value is not None:
                bias += max(min((fear_greed_value - 50) / 100, 0.2), -0.2)
            if coingecko_context:
                bias += max(min(float(coingecko_context.get("market_cap_change_pct_24h") or 0.0) / 20, 0.15), -0.15)
        return round(bias, 4)

    def _latest_bar_age_minutes(self, item: dict, observed_at: datetime) -> float | None:
        bars = item.get("bars") or []
        if not bars:
            return None
        latest_timestamp = bars[-1].get("t")
        if latest_timestamp is None:
            return None
        parsed = self.alpaca._parse_bar_timestamp(latest_timestamp)
        comparable_observed = (
            observed_at.astimezone(timezone.utc)
            if observed_at.tzinfo is not None
            else observed_at.replace(tzinfo=timezone.utc)
        )
        comparable_parsed = (
            parsed.astimezone(timezone.utc)
            if parsed.tzinfo is not None
            else parsed.replace(tzinfo=timezone.utc)
        )
        return round((comparable_observed - comparable_parsed).total_seconds() / 60, 2)

    def _gate_signal(
        self,
        *,
        asset_type: str,
        signal,
        observed_at: datetime | None = None,
    ) -> tuple[float, str, bool, str, list[GateCheck]]:
        if signal.decision_signal not in {"BUY", "SELL"}:
            return round(signal.score, 2), "raw", False, "Signal is HOLD, so trade gate is not applicable.", []

        calibrated_confidence, score_band, calibration_source = self.repo.calibrate_signal(
            asset_type=asset_type,
            signal=signal.decision_signal,
            raw_score=signal.score,
            horizon=self.settings.trade_gate_horizon,
            observed_at=observed_at,
        )
        evaluation = self.repo.evaluate_signal_gate(
            asset_type=asset_type,
            signal=signal.decision_signal,
            score_band=score_band,
            horizon=self.settings.trade_gate_horizon,
            observed_at=observed_at,
        )
        return (
            calibrated_confidence,
            calibration_source,
            evaluation.passed,
            evaluation.reason,
            evaluation.checks,
        )

    def _primary_variant(self) -> str:
        return self.settings.scanner_strategy_variant or "layered-v4"

    def _shadow_variant(self) -> str:
        return self.settings.scanner_shadow_variant or "layered-v4"

    def _build_shadow_comparison(
        self,
        *,
        signal,
        calibrated_confidence: float,
        provider_status: str,
        strategy_metadata,
    ) -> VariantComparison | None:
        if not self.settings.scanner_shadow_enabled:
            return None
        primary_variant = self._primary_variant()
        comparison_variant = self._shadow_variant()
        return VariantComparison(
            primary_variant=primary_variant,
            comparison_variant=comparison_variant,
            comparison_signal=signal.decision_signal,
            comparison_raw_score=signal.score,
            comparison_calibrated_confidence=calibrated_confidence,
            comparison_provider_status=provider_status,
            comparison_evidence_quality=strategy_metadata.evidence_quality,
            comparison_execution_eligibility=strategy_metadata.execution_eligibility,
            changed=False,
            summary=(
                "Shadow mode is enabled, but this variant still mirrors the active pipeline until the "
                "layered architecture and new providers are wired in."
            ),
        )

    def _build_breadth_snapshot(self, *, asset_type: str, bars: dict[str, dict]) -> BreadthSnapshot:
        usable_rows = [row for row in bars.values() if row]
        if not usable_rows:
            return BreadthSnapshot(source="internal_breadth", available=False, universe=asset_type)
        total = len(usable_rows)
        above_vwap = 0
        intraday_high = 0
        intraday_low = 0
        buy_balance = 0
        sell_balance = 0
        for row in usable_rows:
            latest_price = float(row.get("latest_price") or 0.0)
            vwap = float(row.get("vwap") or latest_price or 0.0)
            session_open = float(row.get("session_open") or latest_price or 1.0)
            session_high = float(row.get("session_high") or latest_price or 0.0)
            session_low = float(row.get("session_low") or latest_price or 0.0)
            price_change_pct = ((latest_price - session_open) / max(session_open, 1.0)) * 100 if session_open else 0.0
            if latest_price >= vwap:
                above_vwap += 1
            if latest_price >= session_high * 0.998:
                intraday_high += 1
            if latest_price <= max(session_low, 0.0001) * 1.002:
                intraday_low += 1
            if price_change_pct > 0 and latest_price >= vwap:
                buy_balance += 1
            elif price_change_pct < 0 and latest_price < vwap:
                sell_balance += 1
        participation_score = ((above_vwap / total) * 100) - 50.0
        return BreadthSnapshot(
            source="internal_breadth",
            available=True,
            stale=False,
            as_of=datetime.now(timezone.utc),
            universe=asset_type,
            percent_above_vwap=round((above_vwap / total) * 100, 2),
            percent_intraday_high=round((intraday_high / total) * 100, 2),
            percent_intraday_low=round((intraday_low / total) * 100, 2),
            buy_balance=round((buy_balance / total) * 100, 2),
            sell_balance=round((sell_balance / total) * 100, 2),
            participation_score=round(participation_score, 2),
        )

    def _symbol_for_directional_news(self, symbol: str, asset_type: str) -> str:
        if asset_type == "crypto" and "/" in symbol:
            return symbol.split("/", 1)[0]
        return symbol

    async def _refresh_due_signal_outcomes(self, observed_at: datetime) -> int:
        pending = self.repo.list_due_signal_outcome_evaluations(observed_at=observed_at)
        if not pending:
            return 0

        async def resolve(
            evaluation: PendingSignalOutcomeEvaluation,
        ) -> OutcomeEvaluationUpdate | None:
            lookup = self._OUTCOME_LOOKUP_CONFIG[evaluation.horizon]
            try:
                if evaluation.asset_type == "crypto":
                    price = await self.alpaca.get_crypto_price_on_or_after_timestamp(
                        evaluation.ticker,
                        evaluation.target_at,
                        max_search_minutes=lookup["max_search_minutes"],
                        timeframe=lookup["timeframe"],
                    )
                else:
                    price = await self.alpaca.get_price_on_or_after_timestamp(
                        evaluation.ticker,
                        evaluation.target_at,
                        max_search_minutes=lookup["max_search_minutes"],
                        timeframe=lookup["timeframe"],
                    )
            except Exception:
                price = None
            comparable_observed_at = observed_at
            comparable_expires_at = evaluation.expires_at
            if observed_at.tzinfo is None and evaluation.expires_at.tzinfo is not None:
                comparable_expires_at = evaluation.expires_at.replace(tzinfo=None)
            elif observed_at.tzinfo is not None and evaluation.expires_at.tzinfo is None:
                comparable_observed_at = observed_at.replace(tzinfo=None)
            if price is None and comparable_observed_at < comparable_expires_at:
                return None
            return OutcomeEvaluationUpdate(
                outcome_id=evaluation.outcome_id,
                horizon=evaluation.horizon,
                status="resolved" if price is not None else "missed",
                price=price,
                evaluated_at=observed_at,
            )

        resolved = await asyncio.gather(*(resolve(item) for item in pending))
        completed = [item for item in resolved if item is not None]
        return self.repo.apply_signal_outcome_evaluations(completed)

    def _compute_market_status(self, bars: dict[str, dict]) -> tuple[str, float, float]:
        spy = bars.get("SPY")
        qqq = bars.get("QQQ")
        spy_change = (
            (((spy or {}).get("latest_price", 0) - (spy or {}).get("day_open", 0))
             / ((spy or {}).get("day_open", 1) or 1))
            * 100
        )
        qqq_change = (
            (((qqq or {}).get("latest_price", 0) - (qqq or {}).get("day_open", 0))
             / ((qqq or {}).get("day_open", 1) or 1))
            * 100
        )
        market_status = market_status_from_change(spy_change, qqq_change)
        return market_status, spy_change, qqq_change

    async def _get_directional_sentiment(self, ticker: str) -> tuple[float, bool, str, str, list[str]]:
        cached_score, cached_label = self.news_cache.get(ticker)
        if cached_score is not None:
            return cached_score, True, "cache", cached_label, []

        marketaux_score, finnhub_score = await asyncio.gather(
            self.marketaux.get_news_sentiment_score(ticker),
            self.finnhub.get_news_sentiment_score(ticker),
        )
        scores = [score for score in (marketaux_score, finnhub_score) if abs(score) > 0]
        sentiment = round(sum(scores) / len(scores), 4) if scores else 0.0
        self.news_cache.set(ticker, sentiment)
        warnings: list[str] = []
        if not self.settings.marketaux_api_token:
            warnings.append("marketaux_api_token_missing")
        if not self.settings.finnhub_api_key:
            warnings.append("finnhub_api_key_missing")
        if not scores:
            warnings.append("directional_news_unavailable")
            return sentiment, True, "insufficient", "Directional news providers returned no usable signal", warnings
        return sentiment, True, "marketaux+finnhub", "Fresh directional news check", warnings

    def _provider_health(
        self,
        *,
        asset_type: str,
        item: dict,
        observed_at: datetime,
        data_quality: str,
        fear_greed_value: int | None,
        coingecko_context: dict | None,
        options_snapshot: OptionsFlowSnapshot,
        news_warnings: list[str],
        sec_snapshot: SECCatalystSnapshot | None = None,
        binance_snapshot: BinanceMicrostructureSnapshot | None = None,
        deribit_snapshot: DeribitPositioningSnapshot | None = None,
        fred_snapshot: FREDMacroSnapshot | None = None,
        breadth_snapshot: BreadthSnapshot | None = None,
        defillama_snapshot: DefiLlamaSnapshot | None = None,
    ) -> tuple[str, list[str]]:
        warnings = list(news_warnings)
        critical_warnings: list[str] = []
        latest_bar_age_minutes = self._latest_bar_age_minutes(item, observed_at)
        if latest_bar_age_minutes is None:
            critical_warnings.append("market_bars_missing")
        elif latest_bar_age_minutes > self.settings.provider_max_bar_age_minutes:
            critical_warnings.append("market_bars_stale")
        if data_quality == "low":
            critical_warnings.append("market_data_quality_low")
        if asset_type == "stock" and self.settings.sec_user_agent.endswith("your-email@example.com"):
            warnings.append("sec_user_agent_placeholder")
        if asset_type == "stock" and self.settings.sec_enhanced_enabled:
            if sec_snapshot is None or not sec_snapshot.available:
                warnings.append("sec_snapshot_unavailable")
            else:
                warnings.extend(list(sec_snapshot.warnings))
        if asset_type == "crypto" and fear_greed_value is None:
            warnings.append("fear_greed_unavailable")
        if asset_type == "crypto" and coingecko_context is None:
            warnings.append("coingecko_context_unavailable")
        if asset_type == "stock" and options_snapshot.summary.startswith("Options flow unavailable"):
            warnings.append("options_flow_unavailable")
        if asset_type == "crypto" and self.settings.binance_enabled:
            if binance_snapshot is None or not binance_snapshot.available:
                warnings.append("binance_microstructure_unavailable")
            elif binance_snapshot.warnings:
                warnings.extend(list(binance_snapshot.warnings))
        if asset_type == "crypto" and self.settings.deribit_enabled:
            if deribit_snapshot is None or not deribit_snapshot.available:
                warnings.append("deribit_positioning_unavailable")
            elif deribit_snapshot.warnings:
                warnings.extend(list(deribit_snapshot.warnings))
        if fred_snapshot is not None and self.settings.fred_enabled:
            if not fred_snapshot.available:
                warnings.append("fred_macro_unavailable")
            elif fred_snapshot.warning_flags:
                warnings.extend(list(fred_snapshot.warning_flags))
        if self.settings.internal_breadth_enabled:
            if breadth_snapshot is None or not breadth_snapshot.available:
                warnings.append(f"{asset_type}_breadth_unavailable")
        if asset_type == "crypto" and self.settings.defillama_enabled:
            if defillama_snapshot is None or not defillama_snapshot.available:
                warnings.append("defillama_macro_unavailable")
            elif defillama_snapshot.warnings:
                warnings.extend(list(defillama_snapshot.warnings))
        merged_warnings = list(dict.fromkeys([*critical_warnings, *warnings]))
        if critical_warnings:
            return "critical", merged_warnings
        return ("degraded" if merged_warnings else "ok"), merged_warnings

    def _freshness_flags(
        self,
        *,
        asset_type: str,
        item: dict,
        observed_at: datetime,
        news_source: str,
        options_snapshot: OptionsFlowSnapshot,
        fear_greed_value: int | None,
        coingecko_context: dict | None,
        sec_snapshot: SECCatalystSnapshot | None = None,
        binance_snapshot: BinanceMicrostructureSnapshot | None = None,
        deribit_snapshot: DeribitPositioningSnapshot | None = None,
        fred_snapshot: FREDMacroSnapshot | None = None,
        breadth_snapshot: BreadthSnapshot | None = None,
        defillama_snapshot: DefiLlamaSnapshot | None = None,
    ) -> dict[str, str]:
        bar_age = self._latest_bar_age_minutes(item, observed_at)
        flags: dict[str, str] = {
            "market_bars": (
                "missing"
                if bar_age is None
                else "stale"
                if bar_age > self.settings.provider_max_bar_age_minutes
                else "ok"
            ),
            "directional_news": "fallback" if news_source in {"cache", "insufficient"} else "ok",
            "options_flow": (
                "missing"
                if asset_type == "stock" and options_snapshot.summary.startswith("Options flow unavailable")
                else "ok"
            ),
            "sec": (
                "missing"
                if asset_type == "stock" and self.settings.sec_enhanced_enabled and (sec_snapshot is None or not sec_snapshot.available)
                else "ok"
            ),
            "fear_greed": (
                "missing" if asset_type == "crypto" and fear_greed_value is None else "ok"
            ),
            "coingecko_context": (
                "missing" if asset_type == "crypto" and coingecko_context is None else "ok"
            ),
            "binance": (
                "missing"
                if asset_type == "crypto" and self.settings.binance_enabled and (binance_snapshot is None or not binance_snapshot.available)
                else "ok"
            ),
            "deribit": (
                "missing"
                if asset_type == "crypto" and self.settings.deribit_enabled and (deribit_snapshot is None or not deribit_snapshot.available)
                else "ok"
            ),
            "fred": (
                "missing" if self.settings.fred_enabled and fred_snapshot is not None and not fred_snapshot.available else "ok"
            ),
            "breadth": (
                "missing"
                if self.settings.internal_breadth_enabled and (breadth_snapshot is None or not breadth_snapshot.available)
                else "ok"
            ),
            "defillama": (
                "missing"
                if asset_type == "crypto" and self.settings.defillama_enabled and (defillama_snapshot is None or not defillama_snapshot.available)
                else "ok"
            ),
        }
        return flags

    async def _analyze_ticker(
        self,
        *,
        ticker: str,
        asset_type: str,
        item: dict,
        market_status: str,
        benchmark_ticker: str,
        benchmark_change_pct: float,
        created_at: datetime,
        fear_greed_value: int | None = None,
        fear_greed_label: str | None = None,
        coingecko_context: dict | None = None,
        binance_snapshot: BinanceMicrostructureSnapshot | None = None,
        deribit_snapshot: DeribitPositioningSnapshot | None = None,
        fred_snapshot: FREDMacroSnapshot | None = None,
        breadth_snapshot: BreadthSnapshot | None = None,
        defillama_snapshot: DefiLlamaSnapshot | None = None,
    ) -> ScanResult | None:
        async with self._analyze_semaphore:
            return await self._analyze_ticker_impl(
                ticker=ticker,
                asset_type=asset_type,
                item=item,
                market_status=market_status,
                benchmark_ticker=benchmark_ticker,
                benchmark_change_pct=benchmark_change_pct,
                created_at=created_at,
                fear_greed_value=fear_greed_value,
                fear_greed_label=fear_greed_label,
                coingecko_context=coingecko_context,
                binance_snapshot=binance_snapshot,
                deribit_snapshot=deribit_snapshot,
                fred_snapshot=fred_snapshot,
                breadth_snapshot=breadth_snapshot,
                defillama_snapshot=defillama_snapshot,
            )

    async def _analyze_ticker_impl(
        self,
        *,
        ticker: str,
        asset_type: str,
        item: dict,
        market_status: str,
        benchmark_ticker: str,
        benchmark_change_pct: float,
        created_at: datetime,
        fear_greed_value: int | None = None,
        fear_greed_label: str | None = None,
        coingecko_context: dict | None = None,
        binance_snapshot: BinanceMicrostructureSnapshot | None = None,
        deribit_snapshot: DeribitPositioningSnapshot | None = None,
        fred_snapshot: FREDMacroSnapshot | None = None,
        breadth_snapshot: BreadthSnapshot | None = None,
        defillama_snapshot: DefiLlamaSnapshot | None = None,
    ) -> ScanResult | None:
        if not item or (asset_type == "stock" and ticker in {"SPY", "QQQ"}):
            return None

        price = item["latest_price"]
        day_open = item["session_open"] or price or 1
        price_change_pct = ((price - day_open) / day_open) * 100
        relative_volume = item["latest_volume"] / max(item["average_volume"], 1)
        data_quality = self._data_quality(item, relative_volume)
        breakout_flag = price > item["rolling_high"] and price_change_pct > 0
        breakdown_flag = price < item["rolling_low"] and price_change_pct < 0
        vwap = float(item.get("vwap") or price)
        above_vwap = price >= vwap
        session_high = float(item.get("session_high") or price)
        session_low = float(item.get("session_low") or price)
        session_range = max(session_high - session_low, 0.01)
        volatility_regime = self._volatility_regime(item, price)
        close_to_high_pct = max(0.0, min(1.0, (price - session_low) / session_range))
        close_to_low_pct = max(0.0, min(1.0, (session_high - price) / session_range))
        relative_strength_pct = round(price_change_pct - benchmark_change_pct, 4)
        trend_above_sma, trend_strength_pct = self._compute_trend_signal(item, price)

        sec_snapshot: SECCatalystSnapshot | None = None
        if asset_type == "crypto":
            catalyst_score = 0.0
            options_snapshot = OptionsFlowSnapshot(summary="Not applicable for crypto.")
            filing_flag = False
        else:
            if self.settings.sec_enhanced_enabled:
                sec_snapshot, options_snapshot = await asyncio.gather(
                    self.sec.get_company_snapshot(ticker),
                    self.options_flow.get_flow_snapshot(ticker),
                )
                catalyst_score = sec_snapshot.catalyst_score if sec_snapshot.available else 0.0
                filing_flag = bool(sec_snapshot.recent_event_flags or sec_snapshot.recent_forms)
            else:
                catalyst_score, options_snapshot = await asyncio.gather(
                    self.sec.get_recent_catalyst_score(ticker),
                    self.options_flow.get_flow_snapshot(ticker),
                )
                filing_flag = catalyst_score > 0

        sector_strength_score = max(0.0, min(10.0, 5 + (relative_strength_pct * 1.5)))
        options_flow_snapshot: OptionsFlowSnapshot = options_snapshot
        options_flow_score = max(
            options_flow_snapshot.bullish_score,
            options_flow_snapshot.bearish_score,
        )
        options_bullish = (
            options_flow_snapshot.bullish_score >= options_flow_snapshot.bearish_score
            and options_flow_snapshot.call_volume > 0
        )

        context_bias = self._context_bias(
            asset_type=asset_type,
            market_status=market_status,
            volatility_regime=volatility_regime,
            fear_greed_value=fear_greed_value,
            coingecko_context=coingecko_context,
        )

        sentiment_score = 0.0
        news_checked = False
        news_source = "skipped"
        news_cache_label = "Skipped below news threshold"
        news_warnings: list[str] = []

        if (
            abs(price_change_pct) >= 1.25
            or abs(relative_strength_pct) >= 1.25
            or breakout_flag
            or breakdown_flag
        ):
            sentiment_score, news_checked, news_source, news_cache_label, news_warnings = await self._get_directional_sentiment(
                self._symbol_for_directional_news(ticker, asset_type)
            )
        provider_status, provider_warnings = self._provider_health(
            asset_type=asset_type,
            item=item,
            observed_at=created_at,
            data_quality=data_quality,
            fear_greed_value=fear_greed_value,
            coingecko_context=coingecko_context,
            sec_snapshot=sec_snapshot,
            options_snapshot=options_flow_snapshot,
            news_warnings=news_warnings,
            binance_snapshot=binance_snapshot,
            deribit_snapshot=deribit_snapshot,
            fred_snapshot=fred_snapshot,
            breadth_snapshot=breadth_snapshot,
            defillama_snapshot=defillama_snapshot,
        )
        bar_age_minutes = self._latest_bar_age_minutes(item, created_at)
        freshness_flags = self._freshness_flags(
            asset_type=asset_type,
            item=item,
            observed_at=created_at,
            news_source=news_source,
            options_snapshot=options_flow_snapshot,
            fear_greed_value=fear_greed_value,
            coingecko_context=coingecko_context,
            sec_snapshot=sec_snapshot,
            binance_snapshot=binance_snapshot,
            deribit_snapshot=deribit_snapshot,
            fred_snapshot=fred_snapshot,
            breadth_snapshot=breadth_snapshot,
            defillama_snapshot=defillama_snapshot,
        )

        signal = compute_signal_and_explanation(
            ticker=ticker,
            price=price,
            price_change_pct=price_change_pct,
            relative_volume=relative_volume,
            breakout_flag=breakout_flag,
            breakdown_flag=breakdown_flag,
            above_vwap=above_vwap,
            close_to_high_pct=close_to_high_pct,
            close_to_low_pct=close_to_low_pct,
            sentiment_score=sentiment_score,
            catalyst_score=catalyst_score,
            market_status=market_status,
            relative_strength_pct=relative_strength_pct,
            options_snapshot=options_flow_snapshot,
            asset_type=asset_type,
            benchmark_label=benchmark_ticker,
            volatility_regime=volatility_regime,
            data_quality=data_quality,
            context_bias=context_bias,
            trend_above_sma=trend_above_sma,
            trend_strength_pct=trend_strength_pct,
        )
        calibrated_confidence, calibration_source, gate_passed, gate_reason, gate_checks = self._gate_signal(
            asset_type=asset_type,
            signal=signal,
            observed_at=created_at,
        )
        confidence_overlay = compute_confidence_overlay(
            asset_type=asset_type,
            decision_signal=signal.decision_signal,
            base_confidence=calibrated_confidence,
            market_status=market_status,
            sentiment_score=sentiment_score,
            catalyst_score=catalyst_score,
            options_snapshot=options_flow_snapshot,
            context_bias=context_bias,
            provider_status=provider_status,
            binance_snapshot=binance_snapshot,
            deribit_snapshot=deribit_snapshot,
            sec_snapshot=sec_snapshot,
            fred_snapshot=fred_snapshot,
            breadth_snapshot=breadth_snapshot,
            defillama_snapshot=defillama_snapshot,
        )
        calibrated_confidence = confidence_overlay.adjusted_confidence
        strategy_metadata = build_strategy_evaluation_metadata(
            signal=signal.decision_signal,
            gate_passed=gate_passed,
            calibration_source=calibration_source,
            data_quality=data_quality,
            provider_status=provider_status,
            provider_warnings=provider_warnings,
        )
        execution_eligibility = strategy_metadata.execution_eligibility
        if confidence_overlay.review_flags and execution_eligibility == "eligible":
            execution_eligibility = "review"
        comparison = self._build_shadow_comparison(
            signal=signal,
            calibrated_confidence=calibrated_confidence,
            provider_status=provider_status,
            strategy_metadata=strategy_metadata,
        )
        if self.settings.scanner_shadow_enabled and self._shadow_variant() == "legacy":
            legacy_signal = compute_legacy_signal(
                price_change_pct=price_change_pct,
                relative_volume=relative_volume,
                breakout_flag=breakout_flag,
                breakdown_flag=breakdown_flag,
                above_vwap=above_vwap,
                close_to_high_pct=close_to_high_pct,
                close_to_low_pct=close_to_low_pct,
                sentiment_score=sentiment_score,
                catalyst_score=catalyst_score,
                market_status=market_status,
                relative_strength_pct=relative_strength_pct,
                options_snapshot=options_flow_snapshot,
                volatility_regime=volatility_regime,
                data_quality=data_quality,
                context_bias=context_bias,
            )
            legacy_confidence, legacy_source, legacy_gate_passed, _, _ = self._gate_signal(
                asset_type=asset_type,
                signal=legacy_signal,
                observed_at=created_at,
            )
            legacy_metadata = build_strategy_evaluation_metadata(
                signal=legacy_signal.decision_signal,
                gate_passed=legacy_gate_passed,
                calibration_source=legacy_source,
                data_quality=data_quality,
                provider_status=provider_status,
                provider_warnings=provider_warnings,
            )
            comparison = VariantComparison(
                primary_variant=self._primary_variant(),
                comparison_variant="legacy",
                comparison_signal=legacy_signal.decision_signal,
                comparison_raw_score=legacy_signal.score,
                comparison_calibrated_confidence=legacy_confidence,
                comparison_provider_status=provider_status,
                comparison_evidence_quality=legacy_metadata.evidence_quality,
                comparison_execution_eligibility=legacy_metadata.execution_eligibility,
                changed=(
                    legacy_signal.decision_signal != signal.decision_signal
                    or round(legacy_signal.score, 2) != round(signal.score, 2)
                    or round(legacy_confidence, 2) != round(calibrated_confidence, 2)
                ),
                summary=(
                    f"Legacy comparison {legacy_signal.decision_signal} {legacy_signal.score:.2f} "
                    f"vs layered {signal.decision_signal} {signal.score:.2f}."
                ),
            )
        gated_explanation = compute_signal_and_explanation(
            ticker=ticker,
            price=price,
            price_change_pct=price_change_pct,
            relative_volume=relative_volume,
            breakout_flag=breakout_flag,
            breakdown_flag=breakdown_flag,
            above_vwap=above_vwap,
            close_to_high_pct=close_to_high_pct,
            close_to_low_pct=close_to_low_pct,
            sentiment_score=sentiment_score,
            catalyst_score=catalyst_score,
            market_status=market_status,
            relative_strength_pct=relative_strength_pct,
            options_snapshot=options_flow_snapshot,
            asset_type=asset_type,
            benchmark_label=benchmark_ticker,
            volatility_regime=volatility_regime,
            data_quality=data_quality,
            context_bias=context_bias,
            gate_reason=gate_reason,
            trend_above_sma=trend_above_sma,
            trend_strength_pct=trend_strength_pct,
        )

        return ScanResult(
            ticker=ticker,
            asset_type=asset_type,
            strategy_variant=self._primary_variant(),
            score=signal.score,
            raw_score=signal.score,
            calibrated_confidence=calibrated_confidence,
            calibration_source=calibration_source,
            confidence_label=strategy_metadata.confidence_label,
            strategy_id=strategy_metadata.strategy_id,
            strategy_version=strategy_metadata.strategy_version,
            strategy_primary_horizon=strategy_metadata.primary_holding_horizon,
            strategy_entry_assumption=strategy_metadata.entry_assumption,
            strategy_exit_assumption=strategy_metadata.exit_assumption,
            evidence_quality=strategy_metadata.evidence_quality,
            evidence_quality_score=strategy_metadata.evidence_quality_score,
            evidence_quality_reasons=list(strategy_metadata.evidence_quality_reasons),
            data_grade=strategy_metadata.data_grade,
            execution_eligibility=execution_eligibility,
            buy_score=signal.buy_score,
            sell_score=signal.sell_score,
            decision_signal=signal.decision_signal,
            scoring_version=signal.scoring_version,
            explanation=gated_explanation.explanation,
            price=round(price, 2),
            price_change_pct=round(price_change_pct, 2),
            relative_volume=round(relative_volume, 2),
            sentiment_score=round(sentiment_score, 2),
            filing_flag=filing_flag,
            breakout_flag=breakout_flag,
            market_status=market_status,
            sector_strength_score=round(sector_strength_score, 2),
            relative_strength_pct=relative_strength_pct,
            options_flow_score=round(options_flow_score, 2),
            options_flow_summary=options_flow_snapshot.summary,
            options_flow_bullish=options_bullish,
            options_call_put_ratio=options_flow_snapshot.put_call_volume_ratio,
            alert_sent=False,
            news_checked=news_checked,
            news_source=news_source,
            news_cache_label=news_cache_label,
            signal_label="strong" if gate_passed and signal.signal_label == "strong" else ("watch" if gate_passed and signal.signal_label != "weak" else ("blocked" if signal.decision_signal != "HOLD" else signal.signal_label)),
            data_quality=data_quality,
            volatility_regime=volatility_regime,
            benchmark_ticker=benchmark_ticker,
            benchmark_change_pct=round(benchmark_change_pct, 2),
            gate_passed=gate_passed,
            gate_reason=gate_reason,
            gate_checks=gate_checks,
            coingecko_price_change_pct_24h=(
                round(float(coingecko_context.get("price_change_pct_24h") or 0.0), 2)
                if coingecko_context and coingecko_context.get("price_change_pct_24h") is not None
                else None
            ),
            coingecko_market_cap_rank=(coingecko_context or {}).get("market_cap_rank"),
            fear_greed_value=fear_greed_value,
            fear_greed_label=fear_greed_label,
            provider_status=provider_status,
            provider_warnings=provider_warnings,
            bar_age_minutes=bar_age_minutes,
            freshness_flags=freshness_flags,
            layer_details={
                "directional": {
                    "reasons": list(signal.directional_reasons),
                    "score_contributions": dict(signal.directional_contributions or {}),
                    "buy_score": signal.buy_score,
                    "sell_score": signal.sell_score,
                    "market_status": market_status,
                    "relative_strength_pct": relative_strength_pct,
                    "volatility_regime": volatility_regime,
                },
                "confidence": {
                    "adjustment_delta": confidence_overlay.delta,
                    "reasons": list(confidence_overlay.reasons),
                    "adjusted_confidence": calibrated_confidence,
                    "calibration_source": calibration_source,
                    "gate_passed": gate_passed,
                    "gate_reason": gate_reason,
                },
                "evidence": {
                    "quality": strategy_metadata.evidence_quality,
                    "reasons": list(strategy_metadata.evidence_quality_reasons),
                },
                "execution": {
                    "eligibility": execution_eligibility,
                    "review_flags": list(confidence_overlay.review_flags),
                },
                "provider_health": {
                    "provider_status": provider_status,
                    "warnings": provider_warnings,
                    "bar_age_minutes": bar_age_minutes,
                    "freshness_flags": freshness_flags,
                    "binance": (
                        {
                            "available": binance_snapshot.available,
                            "spread_bps": binance_snapshot.spread_bps,
                            "book_imbalance": binance_snapshot.book_imbalance,
                            "aggressor_pressure": binance_snapshot.aggressor_pressure,
                        }
                        if binance_snapshot is not None
                        else None
                    ),
                    "deribit": (
                        {
                            "available": deribit_snapshot.available,
                            "crowding_score": deribit_snapshot.crowding_score,
                            "put_call_open_interest_ratio": deribit_snapshot.put_call_open_interest_ratio,
                            "perp_premium_pct": deribit_snapshot.perp_premium_pct,
                        }
                        if deribit_snapshot is not None
                        else None
                    ),
                    "sec": (
                        {
                            "available": sec_snapshot.available,
                            "catalyst_score": sec_snapshot.catalyst_score,
                            "recent_event_flags": list(sec_snapshot.recent_event_flags),
                            "fundamental_flags": list(sec_snapshot.fundamental_flags),
                        }
                        if sec_snapshot is not None
                        else None
                    ),
                    "fred": (
                        {
                            "available": fred_snapshot.available,
                            "regime": fred_snapshot.regime,
                            "risk_off_score": fred_snapshot.risk_off_score,
                        }
                        if fred_snapshot is not None
                        else None
                    ),
                    "breadth": (
                        {
                            "available": breadth_snapshot.available,
                            "percent_above_vwap": breadth_snapshot.percent_above_vwap,
                            "buy_balance": breadth_snapshot.buy_balance,
                            "sell_balance": breadth_snapshot.sell_balance,
                        }
                        if breadth_snapshot is not None
                        else None
                    ),
                    "defillama": (
                        {
                            "available": defillama_snapshot.available,
                            "stablecoin_growth_pct_7d": defillama_snapshot.stablecoin_growth_pct_7d,
                            "total_tvl_change_pct_7d": defillama_snapshot.total_tvl_change_pct_7d,
                            "positive_chain_breadth_pct": defillama_snapshot.positive_chain_breadth_pct,
                        }
                        if defillama_snapshot is not None
                        else None
                    ),
                },
            },
            comparison=comparison,
            created_at=created_at,
        )

    async def run_scan(self) -> ScanRun:
        scan_t0 = time.monotonic()
        stock_watchlist = self.settings.watchlist_items
        crypto_watchlist = self.settings.crypto_watchlist_items
        watchlist = stock_watchlist + crypto_watchlist
        observed_at = datetime.now(timezone.utc)
        await self.refresh_due_signal_outcomes(observed_at=observed_at)
        stock_bars_task = self.alpaca.get_latest_bars(stock_watchlist) if stock_watchlist else None
        crypto_bars_task = self.alpaca.get_latest_crypto_bars(crypto_watchlist) if crypto_watchlist else None
        fear_greed_task = self.fear_greed.get_index()
        coingecko_task = self.coingecko.get_market_context(crypto_watchlist) if crypto_watchlist else None
        binance_task = (
            self.binance.get_microstructure_batch(crypto_watchlist)
            if crypto_watchlist and self.settings.binance_enabled
            else None
        )
        deribit_task = (
            self.deribit.get_positioning_batch(crypto_watchlist)
            if crypto_watchlist and self.settings.deribit_enabled
            else None
        )
        fred_task = self.fred.get_macro_snapshot() if self.settings.fred_enabled else None
        defillama_task = (
            self.defillama.get_macro_snapshot()
            if crypto_watchlist and self.settings.defillama_enabled
            else None
        )
        stock_bars, crypto_bars, fear_greed, crypto_context, binance_context, deribit_context, fred_snapshot, defillama_snapshot = await asyncio.gather(
            stock_bars_task if stock_bars_task is not None else asyncio.sleep(0, result={}),
            crypto_bars_task if crypto_bars_task is not None else asyncio.sleep(0, result={}),
            fear_greed_task,
            coingecko_task if coingecko_task is not None else asyncio.sleep(0, result={}),
            binance_task if binance_task is not None else asyncio.sleep(0, result={}),
            deribit_task if deribit_task is not None else asyncio.sleep(0, result={}),
            fred_task if fred_task is not None else asyncio.sleep(0, result=None),
            defillama_task if defillama_task is not None else asyncio.sleep(0, result=None),
        )
        crypto_bars = self.market_data_service.apply_crypto_price_overrides(crypto_bars)
        market_status, spy_change_pct, qqq_change_pct = self._compute_market_status(stock_bars)
        fear_greed_value, fear_greed_label = fear_greed
        stock_breadth = self._build_breadth_snapshot(asset_type="stock", bars=stock_bars) if self.settings.internal_breadth_enabled else None
        crypto_breadth = self._build_breadth_snapshot(asset_type="crypto", bars=crypto_bars) if self.settings.internal_breadth_enabled else None
        crypto_benchmark_ticker = "BTC/USD" if "BTC/USD" in crypto_bars else (crypto_watchlist[0] if crypto_watchlist else None)
        crypto_benchmark_row = crypto_bars.get(crypto_benchmark_ticker or "", {})
        crypto_benchmark_change_pct = (
            (
                (float(crypto_benchmark_row.get("latest_price", 0) or 0) - float(crypto_benchmark_row.get("session_open", 0) or 0))
                / max(float(crypto_benchmark_row.get("session_open", 0) or 1), 1)
            ) * 100
            if crypto_benchmark_row
            else 0.0
        )
        crypto_market_status = self._crypto_market_status(crypto_benchmark_change_pct, fear_greed_value)
        created_at = observed_at

        analyzed = await asyncio.gather(
            *[
                self._analyze_ticker(
                    ticker=ticker,
                    asset_type="stock",
                    item=stock_bars.get(ticker),
                    market_status=market_status,
                    benchmark_ticker="SPY/QQQ",
                    benchmark_change_pct=(spy_change_pct + qqq_change_pct) / 2,
                    created_at=created_at,
                    fred_snapshot=fred_snapshot,
                    breadth_snapshot=stock_breadth,
                )
                for ticker in stock_watchlist
            ],
            *[
                self._analyze_ticker(
                    ticker=ticker,
                    asset_type="crypto",
                    item=crypto_bars.get(ticker),
                    market_status=crypto_market_status,
                    benchmark_ticker=crypto_benchmark_ticker or "BTC/USD",
                    benchmark_change_pct=crypto_benchmark_change_pct,
                    created_at=created_at,
                    fear_greed_value=fear_greed_value,
                    fear_greed_label=fear_greed_label,
                    coingecko_context=crypto_context.get(ticker),
                    binance_snapshot=binance_context.get(ticker),
                    deribit_snapshot=deribit_context.get(ticker),
                    fred_snapshot=fred_snapshot,
                    breadth_snapshot=crypto_breadth,
                    defillama_snapshot=defillama_snapshot,
                )
                for ticker in crypto_watchlist
            ],
        )
        results = sorted(
            [row for row in analyzed if row is not None],
            key=lambda r: (
                0 if r.gate_passed and r.decision_signal in {"BUY", "SELL"} else 1 if r.decision_signal in {"BUY", "SELL"} else 2,
                -r.score,
                r.ticker,
            ),
        )

        run = ScanRun(
            run_id=str(uuid4()),
            created_at=created_at,
            market_status=market_status,
            strategy_variant=self._primary_variant(),
            shadow_enabled=bool(self.settings.scanner_shadow_enabled),
            scan_count=len(results),
            watchlist_size=len(watchlist),
            fear_greed_value=fear_greed_value,
            fear_greed_label=fear_greed_label,
            results=results,
        )
        try:
            await self.alerts.dispatch_for_run(run)
        except Exception as exc:
            run.alerts_sent = sum(1 for result in run.results if result.alert_sent)
            logger.warning(
                "alert dispatch failed",
                extra={"event": "alert_failure", "run_id": run.run_id},
                exc_info=exc,
            )
        self.repo.save_run(run)
        scan_duration_ms = round((time.monotonic() - scan_t0) * 1000)
        logger.info(
            "scan completed",
            extra={
                "event": "scan_completed",
                "run_id": run.run_id,
                "watchlist_size": run.watchlist_size,
                "scan_count": run.scan_count,
                "duration_ms": scan_duration_ms,
            },
        )
        if self.automation_service is not None:
            await self.automation_service.process_completed_run(run)
        return run

    async def refresh_due_signal_outcomes(self, *, observed_at: datetime | None = None) -> int:
        return await self._refresh_due_signal_outcomes(
            observed_at=observed_at or datetime.now(timezone.utc)
        )

    def latest(self) -> ScanRun | None:
        return self.repo.get_latest_run()

    def history(self, limit: int = 12) -> list[ScanRun]:
        return self.repo.get_run_history(limit)

    def start_scheduler(self) -> bool:
        return False

    def stop_scheduler(self) -> bool:
        return False

    def scheduler_running(self) -> bool:
        return False
