from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from uuid import uuid4

from app.clients.alpaca import AlpacaClient
from app.clients.coingecko import CoinGeckoClient
from app.clients.fear_greed import FearGreedClient
from app.clients.finnhub import FinnhubClient
from app.clients.options_flow import OptionsFlowClient
from app.clients.sec import SECClient
from app.clients.marketaux import MarketauxClient
from app.config import get_settings
from app.core.scoring import compute_directional_scores, market_status_from_change
from app.core.signals import compute_signal_and_explanation
from app.schemas import GateCheck, OptionsFlowSnapshot, ScanRun, ScanResult
from app.services.alerts import AlertService
from app.services.repository import OutcomeEvaluationUpdate, PendingSignalOutcomeEvaluation, ScanRepository
from app.services.news_cache import NewsCacheService

logger = logging.getLogger(__name__)


class ScannerService:
    _OUTCOME_LOOKUP_CONFIG = {
        "15m": {"timeframe": "1Min", "max_search_minutes": 8 * 60},
        "1h": {"timeframe": "5Min", "max_search_minutes": 2 * 24 * 60},
        "1d": {"timeframe": "1Hour", "max_search_minutes": 5 * 24 * 60},
    }

    def __init__(self) -> None:
        self.settings = get_settings()
        self.alpaca = AlpacaClient()
        self.coingecko = CoinGeckoClient()
        self.fear_greed = FearGreedClient()
        self.finnhub = FinnhubClient()
        self.marketaux = MarketauxClient()
        self.sec = SECClient()
        self.options_flow = OptionsFlowClient()
        self.news_cache = NewsCacheService()
        self.alerts = AlertService()
        self.repo = ScanRepository()
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

    def _gate_signal(
        self,
        *,
        asset_type: str,
        signal,
    ) -> tuple[float, str, bool, str, list[GateCheck]]:
        if signal.decision_signal not in {"BUY", "SELL"}:
            return round(signal.score, 2), "raw", False, "Signal is HOLD, so trade gate is not applicable.", []

        calibrated_confidence, score_band, calibration_source = self.repo.calibrate_signal(
            asset_type=asset_type,
            signal=signal.decision_signal,
            raw_score=signal.score,
            horizon=self.settings.trade_gate_horizon,
        )
        summary = self.repo.get_signal_outcome_summary(asset_type=asset_type)
        signal_bucket = next((bucket for bucket in summary.by_signal if bucket.key == signal.decision_signal), None)
        score_band_bucket = next(
            (bucket for bucket in summary.by_signal_score_bucket if bucket.key == f"{signal.decision_signal}:{score_band}"),
            None,
        )
        signal_count, signal_win_rate, signal_avg_return = self.repo.bucket_metrics_for_horizon(
            bucket=signal_bucket,
            horizon=self.settings.trade_gate_horizon,
        )
        score_band_count, score_band_win_rate, score_band_avg_return = self.repo.bucket_metrics_for_horizon(
            bucket=score_band_bucket,
            horizon=self.settings.trade_gate_horizon,
        )
        checks = [
            GateCheck(
                name="sample_size",
                passed=(signal_count or 0) >= self.settings.trade_gate_min_evaluated_count,
                detail=(
                    f"{asset_type} {signal.decision_signal} bucket has {signal_count or 0} "
                    f"{self.settings.trade_gate_horizon} outcomes; need {self.settings.trade_gate_min_evaluated_count}"
                ),
            ),
            GateCheck(
                name="win_rate",
                passed=(signal_win_rate or 0) >= self.settings.trade_gate_min_win_rate,
                detail=(
                    f"{asset_type} win rate {signal_win_rate or 0:.2f}% vs "
                    f"min {self.settings.trade_gate_min_win_rate:.2f}%"
                ),
            ),
            GateCheck(
                name="avg_return",
                passed=(signal_avg_return or 0) >= self.settings.trade_gate_min_avg_return,
                detail=(
                    f"{asset_type} avg return {signal_avg_return or 0:.4f}% vs "
                    f"min {self.settings.trade_gate_min_avg_return:.4f}%"
                ),
            ),
        ]
        if (score_band_count or 0) >= self.settings.trade_gate_min_evaluated_count:
            checks.extend(
                [
                    GateCheck(
                        name="score_band_win_rate",
                        passed=(score_band_win_rate or 0) >= self.settings.trade_gate_min_win_rate,
                        detail=(
                            f"score band {score_band} win rate {score_band_win_rate or 0:.2f}% vs "
                            f"min {self.settings.trade_gate_min_win_rate:.2f}%"
                        ),
                    ),
                    GateCheck(
                        name="score_band_avg_return",
                        passed=(score_band_avg_return or 0) >= self.settings.trade_gate_min_avg_return,
                        detail=(
                            f"score band {score_band} avg return {score_band_avg_return or 0:.4f}% vs "
                            f"min {self.settings.trade_gate_min_avg_return:.4f}%"
                        ),
                    ),
                ]
            )
        passed = all(check.passed for check in checks)
        if passed:
            reason = f"{asset_type.capitalize()} signal passed calibration and evidence gates."
        else:
            first_failed = next(check for check in checks if not check.passed)
            reason = f"Blocked by {first_failed.name}: {first_failed.detail}."
        return calibrated_confidence, calibration_source, passed, reason, checks

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
        fear_greed_value: int | None,
        coingecko_context: dict | None,
        options_snapshot: OptionsFlowSnapshot,
        news_warnings: list[str],
    ) -> tuple[str, list[str]]:
        warnings = list(news_warnings)
        if asset_type == "stock" and self.settings.sec_user_agent.endswith("your-email@example.com"):
            warnings.append("sec_user_agent_placeholder")
        if asset_type == "crypto" and fear_greed_value is None:
            warnings.append("fear_greed_unavailable")
        if asset_type == "crypto" and coingecko_context is None:
            warnings.append("coingecko_context_unavailable")
        if asset_type == "stock" and options_snapshot.summary.startswith("Options flow unavailable"):
            warnings.append("options_flow_unavailable")
        return ("degraded" if warnings else "ok"), warnings

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

        if asset_type == "crypto":
            catalyst_score = 0.0
            options_snapshot = OptionsFlowSnapshot(summary="Not applicable for crypto.")
            filing_flag = False
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

        base_sentiment_score = 0.0
        context_bias = self._context_bias(
            asset_type=asset_type,
            market_status=market_status,
            volatility_regime=volatility_regime,
            fear_greed_value=fear_greed_value,
            coingecko_context=coingecko_context,
        )
        pre_news_scores = compute_directional_scores(
            relative_volume=relative_volume,
            price_change_pct=price_change_pct,
            breakout_flag=breakout_flag,
            breakdown_flag=breakdown_flag,
            above_vwap=above_vwap,
            close_to_high_pct=close_to_high_pct,
            close_to_low_pct=close_to_low_pct,
            sentiment_score=base_sentiment_score,
            catalyst_score=catalyst_score,
            market_status=market_status,
            relative_strength_pct=relative_strength_pct,
            options_bullish_score=options_flow_snapshot.bullish_score,
            options_bearish_score=options_flow_snapshot.bearish_score,
            volatility_regime=volatility_regime,
            data_quality=data_quality,
            context_bias=context_bias,
        )

        sentiment_score = 0.0
        news_checked = False
        news_source = "skipped"
        news_cache_label = "Skipped below news threshold"
        news_warnings: list[str] = []

        if (
            pre_news_scores.selected_score >= self.settings.news_check_score_threshold - 5
            or abs(price_change_pct) >= 2
            or abs(relative_strength_pct) >= 1.25
        ):
            sentiment_score, news_checked, news_source, news_cache_label, news_warnings = await self._get_directional_sentiment(
                self._symbol_for_directional_news(ticker, asset_type)
            )
        provider_status, provider_warnings = self._provider_health(
            asset_type=asset_type,
            fear_greed_value=fear_greed_value,
            coingecko_context=coingecko_context,
            options_snapshot=options_flow_snapshot,
            news_warnings=news_warnings,
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
        )
        calibrated_confidence, calibration_source, gate_passed, gate_reason, gate_checks = self._gate_signal(
            asset_type=asset_type,
            signal=signal,
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
        )

        return ScanResult(
            ticker=ticker,
            asset_type=asset_type,
            score=signal.score,
            calibrated_confidence=calibrated_confidence,
            calibration_source=calibration_source,
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
            created_at=created_at,
        )

    async def run_scan(self) -> ScanRun:
        stock_watchlist = self.settings.watchlist_items
        crypto_watchlist = self.settings.crypto_watchlist_items
        watchlist = stock_watchlist + crypto_watchlist
        observed_at = datetime.now(timezone.utc)
        await self.refresh_due_signal_outcomes(observed_at=observed_at)
        stock_bars_task = self.alpaca.get_latest_bars(stock_watchlist) if stock_watchlist else None
        crypto_bars_task = self.alpaca.get_latest_crypto_bars(crypto_watchlist) if crypto_watchlist else None
        fear_greed_task = self.fear_greed.get_index()
        coingecko_task = self.coingecko.get_market_context(crypto_watchlist) if crypto_watchlist else None
        stock_bars, crypto_bars, fear_greed, crypto_context = await asyncio.gather(
            stock_bars_task if stock_bars_task is not None else asyncio.sleep(0, result={}),
            crypto_bars_task if crypto_bars_task is not None else asyncio.sleep(0, result={}),
            fear_greed_task,
            coingecko_task if coingecko_task is not None else asyncio.sleep(0, result={}),
        )
        market_status, spy_change_pct, qqq_change_pct = self._compute_market_status(stock_bars)
        fear_greed_value, fear_greed_label = fear_greed
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
