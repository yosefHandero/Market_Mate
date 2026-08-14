from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import time
from uuid import uuid4

from app.clients.alpaca import AlpacaClient
from app.clients.polygon import PolygonClient
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
from app.core.decision_presentation import (
    build_decision_enrichment,
    build_exit_window,
    cap_confidence_by_data_quality,
)
from app.core.freshness_policy import unified_bar_freshness_max_age_minutes
from app.core.legacy_signals import compute_legacy_signal
from app.core.structural_prediction import evaluate_exit_window_outcome_with_disambiguation
from app.core.ranking import display_sort_key, is_buy_candidate
from app.core.selection import apply_top_pick_selection
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
from app.services.repository import (
    OutcomeEvaluationUpdate,
    PendingPredictionEvaluation,
    PendingSignalOutcomeEvaluation,
    PredictionEvaluationUpdate,
    ScanRepository,
)
from app.services.news_cache import NewsCacheService
from app.services.weekly_prediction_service import WeeklyPredictionService
from app.services.daily_bar_service import DailyBarService

logger = logging.getLogger(__name__)


class ScannerService:
    _OUTCOME_LOOKUP_CONFIG = {
        "15m": {"timeframe": "1Min", "max_search_minutes": 24 * 60},
        "1h": {"timeframe": "5Min", "max_search_minutes": 3 * 24 * 60},
        "1d": {"timeframe": "1Hour", "max_search_minutes": 7 * 24 * 60},
        "1w": {"timeframe": "1Day", "max_search_minutes": 14 * 24 * 60},
    }
    # Keep /scan/run from drowning in the due-outcome backlog so the live-forward
    # campaign can open. Full backlog drains via admin backfill / worker refresh.
    _SCAN_INLINE_REFRESH_LIMIT = 32

    def __init__(
        self,
        *,
        market_data_service: CoinbaseMarketDataService | None = None,
    ) -> None:
        self.settings = get_settings()
        self.alpaca = AlpacaClient()
        self.polygon = PolygonClient()
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
        self.daily_bar_service = DailyBarService(alpaca=self.alpaca, polygon=self.polygon)
        self.weekly_prediction_service = WeeklyPredictionService(
            daily_bars=self.daily_bar_service,
            repository=self.repo,
        )
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

    @staticmethod
    def _as_utc_datetime(value: datetime) -> datetime:
        return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    def _coinbase_ws_age_minutes(self, item: dict, observed_at: datetime) -> float | None:
        timestamp = item.get("coinbase_price_received_at")
        if timestamp is None:
            return None
        if isinstance(timestamp, datetime):
            parsed = timestamp
        elif isinstance(timestamp, str):
            try:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        return round((self._as_utc_datetime(observed_at) - self._as_utc_datetime(parsed)).total_seconds() / 60, 2)

    def _latest_bar_as_of(self, item: dict) -> datetime | None:
        bars = item.get("bars") or []
        if not bars:
            return None
        latest_timestamp = bars[-1].get("t")
        if latest_timestamp is None:
            return None
        parsed = self.alpaca._parse_bar_timestamp(latest_timestamp)
        return self._as_utc_datetime(parsed)

    def _freshness_max_age_minutes(self) -> int:
        return unified_bar_freshness_max_age_minutes(self.settings)

    def _effective_bar_age_minutes(self, *, asset_type: str, item: dict, observed_at: datetime) -> float | None:
        alpaca_bar_age = self._latest_bar_age_minutes(item, observed_at)
        if asset_type != "crypto":
            return alpaca_bar_age
        ws_age = self._coinbase_ws_age_minutes(item, observed_at)
        if ws_age is None:
            return alpaca_bar_age
        if alpaca_bar_age is None:
            return ws_age
        return min(alpaca_bar_age, ws_age)

    def _derive_price_provenance(
        self,
        *,
        asset_type: str,
        freshness_flags: dict[str, str],
        alpaca_served_stale_cache: bool | None,
        market_bars_source: str | None = None,
    ) -> tuple[str, bool]:
        if alpaca_served_stale_cache:
            return "stale_cache", True
        if asset_type == "stock" and market_bars_source == "polygon":
            return "polygon", True
        market_flag = freshness_flags.get("market_bars", "ok")
        if asset_type == "crypto" and market_flag == "ws_override":
            return "coinbase_ws", True
        return "alpaca", False

    async def _get_stock_bars_with_fallback(
        self,
        symbols: list[str],
        *,
        timeframe: str = "5Min",
    ) -> tuple[dict[str, dict], str]:
        if not symbols:
            return {}, "alpaca"

        alpaca_error: Exception | None = None
        try:
            bars = await self.alpaca.get_latest_bars(symbols, timeframe=timeframe)
            if self.alpaca.consume_last_stale_flag():
                return bars, "stale_cache"
            return bars, "alpaca"
        except Exception as exc:
            alpaca_error = exc

        if not self.settings.polygon_api_key:
            if alpaca_error is not None:
                raise alpaca_error
            return {}, "alpaca"

        try:
            bars = await self.polygon.get_latest_bars(
                symbols,
                timeframe=timeframe,
                bar_builder=self.alpaca._build_bars_by_symbol,
            )
            logger.warning(
                "stock bars served from polygon fallback",
                extra={
                    "event": "provider_fallback_polygon_stock_bars",
                    "symbol_count": len(symbols),
                },
            )
            return bars, "polygon"
        except Exception as polygon_error:
            if alpaca_error is not None:
                raise RuntimeError(
                    f"Alpaca stock bars failed ({alpaca_error}); "
                    f"Polygon fallback also failed ({polygon_error})"
                ) from polygon_error
            raise

    def _market_bars_freshness_flag(self, *, asset_type: str, item: dict, observed_at: datetime) -> str:
        alpaca_bar_age = self._latest_bar_age_minutes(item, observed_at)
        ws_age = self._coinbase_ws_age_minutes(item, observed_at) if asset_type == "crypto" else None
        effective_age = self._effective_bar_age_minutes(asset_type=asset_type, item=item, observed_at=observed_at)
        max_age = self._freshness_max_age_minutes()
        if effective_age is None:
            return "missing"
        if effective_age > max_age:
            return "stale"
        if (
            asset_type == "crypto"
            and ws_age is not None
            and ws_age <= max_age
            and (alpaca_bar_age is None or ws_age <= alpaca_bar_age)
        ):
            return "ws_override"
        return "ok"

    def _gate_signal(
        self,
        *,
        asset_type: str,
        signal,
        observed_at: datetime | None = None,
        pattern_name: str | None = None,
    ) -> tuple[float, str, bool, str, list[GateCheck]]:
        if signal.decision_signal not in {"BUY", "SELL"}:
            return round(signal.score, 2), "raw", False, "Signal is HOLD, so trade gate is not applicable.", []

        horizon = self.settings.trade_gate_horizon
        if horizon == "1w" and pattern_name:
            evaluation = self.repo.evaluate_weekly_pattern_gate(
                pattern_name=pattern_name,
                asset_type=asset_type,
                observed_at=observed_at,
                signal=signal.decision_signal,
            )
            calibrated_confidence, score_band, calibration_source = self.repo.calibrate_signal(
                asset_type=asset_type,
                signal=signal.decision_signal,
                raw_score=signal.score,
                horizon=horizon,
                observed_at=observed_at,
            )
            return (
                calibrated_confidence,
                calibration_source,
                evaluation.passed,
                evaluation.reason,
                evaluation.checks,
            )

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

    async def _refresh_due_signal_outcomes(
        self,
        observed_at: datetime,
        *,
        limit: int | None = None,
    ) -> int:
        pending = self.repo.list_due_signal_outcome_evaluations(
            observed_at=observed_at,
            limit=limit,
        )
        if not pending:
            return 0

        async def resolve(
            evaluation: PendingSignalOutcomeEvaluation,
        ) -> OutcomeEvaluationUpdate | None:
            async with self._analyze_semaphore:
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

    def _bar_high(self, bar: dict) -> float:
        return float(bar.get("h") or bar.get("high") or 0.0)

    def _bar_low(self, bar: dict) -> float:
        return float(bar.get("l") or bar.get("low") or 0.0)

    def _bar_timestamp(self, bar: dict) -> datetime | None:
        raw = bar.get("t") or bar.get("timestamp")
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None

    async def _fetch_path_bars(
        self,
        evaluation: PendingPredictionEvaluation,
        *,
        start: datetime,
        end: datetime,
        timeframe: str,
    ) -> list[dict]:
        try:
            if evaluation.asset_type == "crypto":
                return await self.alpaca.get_historical_crypto_bars(
                    evaluation.ticker,
                    start=start,
                    end=end,
                    timeframe=timeframe,
                    limit=5000,
                )
            return await self.alpaca.get_historical_stock_bars(
                evaluation.ticker,
                start=start,
                end=end,
                timeframe=timeframe,
                limit=5000,
            )
        except Exception:
            return []

    def _ambiguous_bar_indices(
        self,
        bars: list[dict],
        *,
        exit_price: float,
        invalidation_level: float,
    ) -> list[int]:
        indices: list[int] = []
        for index, bar in enumerate(bars):
            if self._bar_high(bar) >= exit_price and self._bar_low(bar) <= invalidation_level:
                indices.append(index)
        return indices

    async def _build_exit_window_fields(
        self,
        evaluation: PendingPredictionEvaluation,
        *,
        price: float | None,
    ) -> dict[str, object]:
        if not self.repo._has_exit_window_columns():
            return {}
        if evaluation.estimated_exit_price is None:
            return {}
        if price is None:
            return {
                "exit_window_status": "missed",
                "exit_hit": False,
                "invalidation_hit": False,
                "protected_return_pct": None,
                "hold_return_pct": None,
                "exit_window_helped": None,
            }
        bars = await self._fetch_path_bars(
            evaluation,
            start=evaluation.generated_at,
            end=evaluation.target_at,
            timeframe="1Hour",
        )
        if not bars:
            return {
                "exit_window_status": "unresolved",
                "exit_hit": False,
                "invalidation_hit": False,
                "protected_return_pct": None,
                "hold_return_pct": None,
                "exit_window_helped": None,
            }
        finer_by_index: dict[int, list[dict]] = {}
        if evaluation.invalidation_level is not None:
            for index in self._ambiguous_bar_indices(
                bars,
                exit_price=evaluation.estimated_exit_price,
                invalidation_level=evaluation.invalidation_level,
            )[:3]:
                bar_start = self._bar_timestamp(bars[index])
                if bar_start is None:
                    continue
                bar_end = bar_start + timedelta(hours=1)
                finer = await self._fetch_path_bars(
                    evaluation,
                    start=bar_start,
                    end=bar_end,
                    timeframe="1Min",
                )
                if finer:
                    finer_by_index[index] = finer
        friction_pct = (
            self.repo._friction_bps_for_asset_type(evaluation.asset_type) * 1.0
        ) / 100.0
        outcome = evaluate_exit_window_outcome_with_disambiguation(
            entry_price=evaluation.entry_price,
            estimated_exit_price=evaluation.estimated_exit_price,
            invalidation_level=evaluation.invalidation_level,
            price_at_horizon=price,
            decision_signal=evaluation.decision_signal,
            bars=bars,
            finer_bars_by_index=finer_by_index or None,
            friction_pct=friction_pct,
        )
        return {
            "exit_window_status": outcome.exit_window_status,
            "exit_hit": outcome.exit_hit,
            "invalidation_hit": outcome.invalidation_hit,
            "protected_return_pct": outcome.protected_return_pct,
            "hold_return_pct": outcome.hold_return_pct,
            "exit_window_helped": outcome.exit_window_helped,
        }

    async def _refresh_due_prediction_snapshots(
        self,
        observed_at: datetime,
        *,
        limit: int | None = None,
    ) -> int:
        pending = self.repo.list_due_prediction_evaluations(
            observed_at=observed_at,
            limit=limit,
        )
        if not pending:
            return 0

        async def resolve(
            evaluation: PendingPredictionEvaluation,
        ) -> PredictionEvaluationUpdate | None:
            async with self._analyze_semaphore:
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
                exit_fields = await self._build_exit_window_fields(evaluation, price=price)
                return PredictionEvaluationUpdate(
                    snapshot_id=evaluation.snapshot_id,
                    status="resolved" if price is not None else "missed",
                    price=price,
                    evaluated_at=observed_at,
                    exit_window_status=str(exit_fields.get("exit_window_status"))
                    if exit_fields.get("exit_window_status") is not None
                    else None,
                    exit_hit=exit_fields.get("exit_hit") if exit_fields else None,
                    invalidation_hit=exit_fields.get("invalidation_hit") if exit_fields else None,
                    protected_return_pct=exit_fields.get("protected_return_pct") if exit_fields else None,
                    hold_return_pct=exit_fields.get("hold_return_pct") if exit_fields else None,
                    exit_window_helped=exit_fields.get("exit_window_helped") if exit_fields else None,
                )

        resolved = await asyncio.gather(*(resolve(item) for item in pending))
        completed = [item for item in resolved if item is not None]
        return self.repo.apply_prediction_evaluations(completed)

    async def close_open_positions_past_horizon(
        self,
        observed_at: datetime | None = None,
    ) -> int:
        observed_at = observed_at or datetime.now(timezone.utc)
        due = self.repo.list_paper_positions_due_for_horizon_close(observed_at=observed_at)
        if not due:
            return 0
        market_prices: dict[str, float] = {}
        for item in due:
            if item.ticker in market_prices:
                continue
            try:
                if (item.asset_type or "stock") == "crypto":
                    market_prices[item.ticker] = float(
                        await self.alpaca.get_latest_crypto_price(item.ticker)
                    )
                else:
                    market_prices[item.ticker] = float(await self.alpaca.get_latest_price(item.ticker))
            except Exception:
                logger.warning(
                    "paper_horizon_close_price_unavailable",
                    extra={"event": "paper_horizon_close_price_unavailable", "ticker": item.ticker},
                )
        return self.repo.close_open_positions_past_horizon(
            observed_at=observed_at,
            market_prices=market_prices,
        )

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
        alpaca_served_stale_cache: bool | None = None,
        sec_snapshot: SECCatalystSnapshot | None = None,
        binance_snapshot: BinanceMicrostructureSnapshot | None = None,
        deribit_snapshot: DeribitPositioningSnapshot | None = None,
        fred_snapshot: FREDMacroSnapshot | None = None,
        breadth_snapshot: BreadthSnapshot | None = None,
        defillama_snapshot: DefiLlamaSnapshot | None = None,
    ) -> tuple[str, list[str]]:
        warnings = list(news_warnings)
        critical_warnings: list[str] = []
        if alpaca_served_stale_cache is None:
            alpaca_served_stale_cache = self.alpaca.consume_last_stale_flag()
        max_age = self._freshness_max_age_minutes()
        if alpaca_served_stale_cache:
            latest_for_stale = self._effective_bar_age_minutes(
                asset_type=asset_type,
                item=item,
                observed_at=observed_at,
            )
            if latest_for_stale is None or latest_for_stale > max_age:
                warnings.append("alpaca_served_stale_cache")
        latest_bar_age_minutes = self._effective_bar_age_minutes(
            asset_type=asset_type,
            item=item,
            observed_at=observed_at,
        )
        if latest_bar_age_minutes is None:
            critical_warnings.append("market_bars_missing")
        elif latest_bar_age_minutes > max_age:
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
        flags: dict[str, str] = {
            "market_bars": self._market_bars_freshness_flag(
                asset_type=asset_type,
                item=item,
                observed_at=observed_at,
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
        alpaca_served_stale_cache: bool | None = None,
        market_bars_source: str | None = None,
        daily_bars: list[dict] | None = None,
        market_daily_bars: list[dict] | None = None,
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
                alpaca_served_stale_cache=alpaca_served_stale_cache,
                market_bars_source=market_bars_source,
                daily_bars=daily_bars,
                market_daily_bars=market_daily_bars,
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
        alpaca_served_stale_cache: bool | None = None,
        market_bars_source: str | None = None,
        daily_bars: list[dict] | None = None,
        market_daily_bars: list[dict] | None = None,
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
            abs(price_change_pct) >= self.settings.news_trigger_abs_move_pct
            or abs(relative_strength_pct) >= self.settings.news_trigger_abs_move_pct
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
            alpaca_served_stale_cache=alpaca_served_stale_cache,
            binance_snapshot=binance_snapshot,
            deribit_snapshot=deribit_snapshot,
            fred_snapshot=fred_snapshot,
            breadth_snapshot=breadth_snapshot,
            defillama_snapshot=defillama_snapshot,
        )
        bar_age_minutes = self._effective_bar_age_minutes(
            asset_type=asset_type,
            item=item,
            observed_at=created_at,
        )
        bar_as_of = self._latest_bar_as_of(item) if item else None
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
        price_source, fallback_used = self._derive_price_provenance(
            asset_type=asset_type,
            freshness_flags=freshness_flags,
            alpaca_served_stale_cache=alpaca_served_stale_cache,
            market_bars_source=market_bars_source,
        )
        if market_bars_source == "polygon" and "polygon_stock_bars_fallback" not in provider_warnings:
            provider_warnings.append("polygon_stock_bars_fallback")

        signal = compute_signal_and_explanation(
            buy_threshold=(
                self.settings.signal_crypto_buy_threshold
                if asset_type == "crypto"
                else self.settings.signal_buy_threshold
            ),
            sell_threshold=(
                self.settings.signal_crypto_sell_threshold
                if asset_type == "crypto"
                else self.settings.signal_sell_threshold
            ),
            signal_margin=(
                self.settings.signal_crypto_margin
                if asset_type == "crypto"
                else self.settings.signal_margin
            ),
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
        weekly_prediction = await self.weekly_prediction_service.build_weekly_prediction(
            symbol=ticker,
            asset_type=asset_type,
            as_of=created_at,
            daily_bars=daily_bars,
            market_daily_bars=market_daily_bars,
        )
        pattern_name = weekly_prediction.pattern_name if weekly_prediction else None
        calibrated_confidence, calibration_source, gate_passed, gate_reason, gate_checks = self._gate_signal(
            asset_type=asset_type,
            signal=signal,
            observed_at=created_at,
            pattern_name=pattern_name,
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
            buy_threshold=(
                self.settings.signal_crypto_buy_threshold
                if asset_type == "crypto"
                else self.settings.signal_buy_threshold
            ),
            sell_threshold=(
                self.settings.signal_crypto_sell_threshold
                if asset_type == "crypto"
                else self.settings.signal_sell_threshold
            ),
            signal_margin=(
                self.settings.signal_crypto_margin
                if asset_type == "crypto"
                else self.settings.signal_margin
            ),
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

        decision_enrichment = build_decision_enrichment(
            price=price,
            decision_signal=signal.decision_signal,
            volatility_regime=volatility_regime,
            horizon=self.settings.trade_gate_horizon,
            asset_type=asset_type,
            evidence_quality=strategy_metadata.evidence_quality,
            directional_reasons=signal.directional_reasons,
            score_contributions=dict(signal.directional_contributions or {}),
            evidence_quality_reasons=strategy_metadata.evidence_quality_reasons,
            explanation=gated_explanation.explanation,
            gate_reason=gate_reason,
            gate_passed=gate_passed,
        )

        exit_window = build_exit_window(
            price=price,
            weekly_prediction=weekly_prediction,
            price_prediction=decision_enrichment.price_prediction,
            decision_signal=signal.decision_signal,
            evidence_quality=strategy_metadata.evidence_quality,
            data_quality=data_quality,
            forward_days=self.settings.weekly_forward_days,
        )
        upside_probability_pct = (
            weekly_prediction.upside_probability_pct if weekly_prediction is not None else None
        )
        evidence_provenance = (
            weekly_prediction.evidence_basis if weekly_prediction is not None else "insufficient"
        )
        confidence_score = cap_confidence_by_data_quality(calibrated_confidence, data_quality)
        buy_candidate = is_buy_candidate(
            decision_signal=signal.decision_signal,
            weekly_directional_bias=(
                weekly_prediction.directional_bias if weekly_prediction is not None else None
            ),
            upside_probability_pct=upside_probability_pct,
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
            evidence_grade=decision_enrichment.evidence_grade,
            top_reasons=decision_enrichment.top_reasons,
            price_prediction=decision_enrichment.price_prediction,
            weekly_prediction=weekly_prediction,
            exit_window=exit_window,
            upside_probability_pct=upside_probability_pct,
            confidence_score=confidence_score,
            evidence_provenance=evidence_provenance,
            is_buy_candidate=buy_candidate,
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
            price_source=price_source,
            fallback_used=fallback_used,
            bar_age_minutes=bar_age_minutes,
            bar_as_of=bar_as_of,
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
                "decision": {
                    "evidence_grade": decision_enrichment.evidence_grade,
                    "top_reasons": decision_enrichment.top_reasons,
                    "prediction": decision_enrichment.price_prediction.model_dump(),
                    "weekly_prediction": (
                        weekly_prediction.model_dump() if weekly_prediction is not None else None
                    ),
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
                    "price_source": price_source,
                    "fallback_used": fallback_used,
                    "options_flow_source": options_flow_snapshot.source,
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
        await self.refresh_due_signal_outcomes(
            observed_at=observed_at,
            limit=self._SCAN_INLINE_REFRESH_LIMIT,
        )
        await self.refresh_due_prediction_snapshots(
            observed_at=observed_at,
            limit=self._SCAN_INLINE_REFRESH_LIMIT,
        )
        stock_bars_task = (
            self._get_stock_bars_with_fallback(stock_watchlist)
            if stock_watchlist
            else None
        )
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
        stock_bars_result, crypto_bars, fear_greed, crypto_context, binance_context, deribit_context, fred_snapshot, defillama_snapshot = await asyncio.gather(
            stock_bars_task if stock_bars_task is not None else asyncio.sleep(0, result=({}, "alpaca")),
            crypto_bars_task if crypto_bars_task is not None else asyncio.sleep(0, result={}),
            fear_greed_task,
            coingecko_task if coingecko_task is not None else asyncio.sleep(0, result={}),
            binance_task if binance_task is not None else asyncio.sleep(0, result={}),
            deribit_task if deribit_task is not None else asyncio.sleep(0, result={}),
            fred_task if fred_task is not None else asyncio.sleep(0, result=None),
            defillama_task if defillama_task is not None else asyncio.sleep(0, result=None),
        )
        stock_bars, stock_bars_source = stock_bars_result
        crypto_alpaca_served_stale_cache = self.alpaca.consume_last_stale_flag()
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
        daily_bars_by_symbol: dict[str, list[dict]] = {}
        stock_market_daily_bars: list[dict] | None = None
        crypto_market_daily_bars: list[dict] | None = None
        if self.settings.weekly_primary_horizon_enabled:
            async def _fetch_daily_bounded(ticker: str) -> tuple[list[dict], str]:
                async with self._analyze_semaphore:
                    return await self.daily_bar_service.get_daily_bars(
                        ticker,
                        asset_type="stock" if ticker not in crypto_watchlist else "crypto",
                    )

            daily_fetch_pairs = await asyncio.gather(
                *[_fetch_daily_bounded(ticker) for ticker in watchlist]
            )
            for ticker, (bars, _) in zip(watchlist, daily_fetch_pairs):
                daily_bars_by_symbol[ticker] = bars
            # Benchmark daily series for live relative-strength parity with the
            # walk-forward proof (SPY for stock, BTC/USD for crypto). Fetched once
            # and cached; reused from the per-symbol map when already present.
            stock_market_daily_bars = daily_bars_by_symbol.get("SPY")
            if stock_market_daily_bars is None:
                stock_market_daily_bars = (
                    await self.daily_bar_service.get_daily_bars("SPY", asset_type="stock")
                )[0]
            crypto_benchmark_symbol = crypto_benchmark_ticker or "BTC/USD"
            crypto_market_daily_bars = daily_bars_by_symbol.get(crypto_benchmark_symbol)
            if crypto_market_daily_bars is None:
                crypto_market_daily_bars = (
                    await self.daily_bar_service.get_daily_bars(
                        crypto_benchmark_symbol, asset_type="crypto"
                    )
                )[0]

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
                    alpaca_served_stale_cache=stock_bars_source == "stale_cache",
                    market_bars_source=(
                        None if stock_bars_source == "stale_cache" else stock_bars_source
                    ),
                    daily_bars=daily_bars_by_symbol.get(ticker),
                    market_daily_bars=stock_market_daily_bars,
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
                    alpaca_served_stale_cache=crypto_alpaca_served_stale_cache,
                    daily_bars=daily_bars_by_symbol.get(ticker),
                    market_daily_bars=crypto_market_daily_bars,
                )
                for ticker in crypto_watchlist
            ],
        )
        ranked = sorted(
            [row for row in analyzed if row is not None],
            key=lambda r: display_sort_key(
                r,
                settings=self.settings,
                resolve_signal=lambda row: row.decision_signal,
                scan_result=r,
            ),
        )
        results = [
            row.model_copy(update={"rank": index + 1})
            for index, row in enumerate(ranked)
        ]
        results = apply_top_pick_selection(
            results, settings=self.settings, limit=self.settings.effective_top_pick_limit
        )
        top_stocks = sorted(
            [row for row in results if row.is_top_pick and row.asset_type == "stock"],
            key=lambda row: row.selection_rank or 999,
        )
        top_crypto = sorted(
            [row for row in results if row.is_top_pick and row.asset_type == "crypto"],
            key=lambda row: row.selection_rank or 999,
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
            top_stocks=top_stocks,
            top_crypto=top_crypto,
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

    async def refresh_due_signal_outcomes(
        self,
        *,
        observed_at: datetime | None = None,
        limit: int | None = None,
    ) -> int:
        return await self._refresh_due_signal_outcomes(
            observed_at=observed_at or datetime.now(timezone.utc),
            limit=limit,
        )

    async def refresh_due_prediction_snapshots(
        self,
        *,
        observed_at: datetime | None = None,
        limit: int | None = None,
    ) -> int:
        return await self._refresh_due_prediction_snapshots(
            observed_at=observed_at or datetime.now(timezone.utc),
            limit=limit,
        )

    def latest(self) -> ScanRun | None:
        run = self.repo.get_latest_run()
        if run is None:
            return None
        age_minutes, scan_fresh = self.repo.scan_run_freshness_fields(run.created_at)
        return run.model_copy(update={"scan_age_minutes": age_minutes, "scan_fresh": scan_fresh})

    def history(self, limit: int = 12) -> list[ScanRun]:
        return self.repo.get_run_history(limit)
