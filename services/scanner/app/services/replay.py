from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.clients.alpaca import AlpacaClient
from app.config import get_settings
from app.core.legacy_signals import compute_legacy_signal
from app.core.scoring import market_status_from_change
from app.core.signals import compute_signal_and_explanation
from app.core.strategy_contract import (
    ENTRY_ASSUMPTION,
    EXIT_ASSUMPTION,
    PRIMARY_HOLDING_HORIZON,
    STRATEGY_ID,
    STRATEGY_VERSION,
    build_strategy_evaluation_metadata,
)
from app.schemas import (
    FrictionAssumptions,
    OptionsFlowSnapshot,
    ReplayRequest,
    ReplayResponse,
    ReplaySignalRow,
    ReplaySummary,
    VariantComparison,
)
from app.services.repository import ScanRepository
from app.services.scanner import ScannerService


class ReplayService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.alpaca = AlpacaClient()
        self.repo = ScanRepository()
        self.scanner = ScannerService()

    def _asset_type_for_symbol(self, symbol: str) -> str:
        return "crypto" if "/" in symbol else "stock"

    def _friction(self) -> FrictionAssumptions:
        return FrictionAssumptions(
            stock_slippage_bps=self.settings.stock_slippage_bps,
            stock_spread_bps=self.settings.stock_spread_bps,
            stock_fee_bps=self.settings.stock_fee_bps,
            crypto_slippage_bps=self.settings.crypto_slippage_bps,
            crypto_spread_bps=self.settings.crypto_spread_bps,
            crypto_fee_bps=self.settings.crypto_fee_bps,
        )

    def _sample_timestamps(self, rows: list[dict], *, interval_minutes: int, warmup_bars: int) -> list[int]:
        sampled_indexes: list[int] = []
        last_included: datetime | None = None
        for index in range(warmup_bars, len(rows)):
            timestamp = self.alpaca._parse_bar_timestamp(rows[index].get("t"))
            if last_included is None or (timestamp - last_included) >= timedelta(minutes=interval_minutes):
                sampled_indexes.append(index)
                last_included = timestamp
        return sampled_indexes

    def _build_item(self, symbol: str, rows: list[dict], index: int) -> dict | None:
        payload = {"bars": {symbol: rows[: index + 1]}}
        return self.alpaca._build_bars_by_symbol(payload).get(symbol)

    def _build_item_at_or_before(self, symbol: str, rows: list[dict], *, observed_at: datetime) -> dict | None:
        usable_rows = [
            row for row in rows
            if self.alpaca._parse_bar_timestamp(row.get("t")) <= observed_at
        ]
        if not usable_rows:
            return None
        return self._build_item(symbol, usable_rows, len(usable_rows) - 1)

    def _future_price(self, rows: list[dict], *, observed_at: datetime, horizon: str) -> float | None:
        target = observed_at + {"15m": timedelta(minutes=15), "1h": timedelta(hours=1), "1d": timedelta(days=1)}[horizon]
        for row in rows:
            timestamp = self.alpaca._parse_bar_timestamp(row.get("t"))
            if timestamp >= target:
                return float(row.get("c", 0) or 0) or None
        return None

    async def replay(self, request: ReplayRequest) -> ReplayResponse:
        strategy_variant = request.strategy_variant or self.settings.scanner_strategy_variant or "layered-v4"
        compare_strategy_variant = request.compare_strategy_variant
        symbols = request.symbols
        stock_symbols = [symbol for symbol in symbols if self._asset_type_for_symbol(symbol) == "stock"]
        crypto_symbols = [symbol for symbol in symbols if self._asset_type_for_symbol(symbol) == "crypto"]

        benchmark_rows: dict[str, list[dict]] = {}
        if stock_symbols:
            for benchmark in ("SPY", "QQQ"):
                benchmark_rows[benchmark] = await self.alpaca.get_historical_stock_bars(
                    benchmark,
                    start=request.start,
                    end=request.end,
                    timeframe="5Min",
                )
        if crypto_symbols:
            benchmark_symbol = "BTC/USD"
            benchmark_rows[benchmark_symbol] = await self.alpaca.get_historical_crypto_bars(
                benchmark_symbol,
                start=request.start,
                end=request.end,
                timeframe="5Min",
            )

        symbol_rows: dict[str, list[dict]] = {}
        for symbol in stock_symbols:
            symbol_rows[symbol] = await self.alpaca.get_historical_stock_bars(
                symbol,
                start=request.start,
                end=request.end,
                timeframe="5Min",
            )
        for symbol in crypto_symbols:
            symbol_rows[symbol] = await self.alpaca.get_historical_crypto_bars(
                symbol,
                start=request.start,
                end=request.end,
                timeframe="5Min",
            )

        output_rows: list[ReplaySignalRow] = []
        for symbol, rows in symbol_rows.items():
            asset_type = self._asset_type_for_symbol(symbol)
            if len(rows) <= request.warmup_bars:
                continue
            benchmark_symbol = "BTC/USD" if asset_type == "crypto" else "SPY"
            secondary_benchmark = "QQQ" if asset_type == "stock" else benchmark_symbol
            for index in self._sample_timestamps(
                rows,
                interval_minutes=request.interval_minutes,
                warmup_bars=request.warmup_bars,
            ):
                observed_at = self.alpaca._parse_bar_timestamp(rows[index].get("t"))
                item = self._build_item(symbol, rows, index)
                if not item:
                    continue
                benchmark_item = self._build_item_at_or_before(
                    benchmark_symbol,
                    benchmark_rows.get(benchmark_symbol, []),
                    observed_at=observed_at,
                )
                secondary_item = self._build_item_at_or_before(
                    secondary_benchmark,
                    benchmark_rows.get(secondary_benchmark, []),
                    observed_at=observed_at,
                )
                if asset_type == "stock":
                    spy_change = (
                        ((((benchmark_item or {}).get("latest_price", 0) or 0) - (((benchmark_item or {}).get("day_open", 0) or 0)))
                        / max((((benchmark_item or {}).get("day_open", 0) or 1)), 1))
                        * 100
                    )
                    qqq_change = (
                        ((((secondary_item or {}).get("latest_price", 0) or 0) - (((secondary_item or {}).get("day_open", 0) or 0)))
                        / max((((secondary_item or {}).get("day_open", 0) or 1)), 1))
                        * 100
                    )
                    market_status = market_status_from_change(spy_change, qqq_change)
                    benchmark_change_pct = (spy_change + qqq_change) / 2
                    benchmark_label = "SPY/QQQ"
                else:
                    benchmark_price = float((benchmark_item or {}).get("latest_price", 0) or 0)
                    benchmark_open = float((benchmark_item or {}).get("session_open", 0) or 1)
                    benchmark_change_pct = ((benchmark_price - benchmark_open) / max(benchmark_open, 1)) * 100
                    market_status = self.scanner._crypto_market_status(benchmark_change_pct, None)
                    benchmark_label = "BTC/USD"

                price = float(item["latest_price"])
                day_open = float(item.get("session_open") or price or 1)
                price_change_pct = ((price - day_open) / max(day_open, 1)) * 100
                relative_volume = float(item.get("latest_volume", 0) or 0) / max(float(item.get("average_volume", 1) or 1), 1)
                data_quality = self.scanner._data_quality(item, relative_volume)
                breakout_flag = price > float(item.get("rolling_high") or price) and price_change_pct > 0
                breakdown_flag = price < float(item.get("rolling_low") or price) and price_change_pct < 0
                vwap = float(item.get("vwap") or price)
                above_vwap = price >= vwap
                session_high = float(item.get("session_high") or price)
                session_low = float(item.get("session_low") or price)
                session_range = max(session_high - session_low, 0.01)
                close_to_high_pct = max(0.0, min(1.0, (price - session_low) / session_range))
                close_to_low_pct = max(0.0, min(1.0, (session_high - price) / session_range))
                relative_strength_pct = round(price_change_pct - benchmark_change_pct, 4)
                volatility_regime = self.scanner._volatility_regime(item, price)
                context_bias = self.scanner._context_bias(
                    asset_type=asset_type,
                    market_status=market_status,
                    volatility_regime=volatility_regime,
                    fear_greed_value=None,
                    coingecko_context=None,
                )
                signal = compute_signal_and_explanation(
                    ticker=symbol,
                    price=price,
                    price_change_pct=price_change_pct,
                    relative_volume=relative_volume,
                    breakout_flag=breakout_flag,
                    breakdown_flag=breakdown_flag,
                    above_vwap=above_vwap,
                    close_to_high_pct=close_to_high_pct,
                    close_to_low_pct=close_to_low_pct,
                    sentiment_score=0.0,
                    catalyst_score=0.0,
                    market_status=market_status,
                    relative_strength_pct=relative_strength_pct,
                    options_snapshot=OptionsFlowSnapshot(summary="Replay uses core market data only."),
                    asset_type=asset_type,
                    benchmark_label=benchmark_label,
                    volatility_regime=volatility_regime,
                    data_quality=data_quality,
                    context_bias=context_bias,
                )
                calibrated_confidence = signal.score
                calibration_source = "raw"
                gate_passed = False
                if signal.decision_signal in {"BUY", "SELL"}:
                    calibrated_confidence, score_band, calibration_source = self.repo.calibrate_signal(
                        asset_type=asset_type,
                        signal=signal.decision_signal,
                        raw_score=signal.score,
                        horizon=PRIMARY_HOLDING_HORIZON,
                        observed_at=observed_at,
                    )
                    gate_passed = self.repo.evaluate_signal_gate(
                        asset_type=asset_type,
                        signal=signal.decision_signal,
                        score_band=score_band,
                        horizon=PRIMARY_HOLDING_HORIZON,
                        observed_at=observed_at,
                    ).passed
                provider_status = "ok" if data_quality == "ok" else "degraded"
                strategy_metadata = build_strategy_evaluation_metadata(
                    signal=signal.decision_signal,
                    gate_passed=gate_passed,
                    calibration_source=calibration_source,
                    data_quality=data_quality,
                    provider_status=provider_status,
                    provider_warnings=[],
                )
                comparison = None
                if compare_strategy_variant == "legacy":
                    legacy_signal = compute_legacy_signal(
                        price_change_pct=price_change_pct,
                        relative_volume=relative_volume,
                        breakout_flag=breakout_flag,
                        breakdown_flag=breakdown_flag,
                        above_vwap=above_vwap,
                        close_to_high_pct=close_to_high_pct,
                        close_to_low_pct=close_to_low_pct,
                        sentiment_score=0.0,
                        catalyst_score=0.0,
                        market_status=market_status,
                        relative_strength_pct=relative_strength_pct,
                        options_snapshot=OptionsFlowSnapshot(summary="Replay uses core market data only."),
                        volatility_regime=volatility_regime,
                        data_quality=data_quality,
                        context_bias=context_bias,
                    )
                    legacy_confidence = legacy_signal.score
                    if legacy_signal.decision_signal in {"BUY", "SELL"}:
                        legacy_confidence, _, _ = self.repo.calibrate_signal(
                            asset_type=asset_type,
                            signal=legacy_signal.decision_signal,
                            raw_score=legacy_signal.score,
                            horizon=PRIMARY_HOLDING_HORIZON,
                            observed_at=observed_at,
                        )
                    comparison = VariantComparison(
                        primary_variant=strategy_variant,
                        comparison_variant=compare_strategy_variant,
                        comparison_signal=legacy_signal.decision_signal,
                        comparison_raw_score=legacy_signal.score,
                        comparison_calibrated_confidence=legacy_confidence,
                        comparison_provider_status=provider_status,
                        comparison_evidence_quality=strategy_metadata.evidence_quality,
                        comparison_execution_eligibility=strategy_metadata.execution_eligibility,
                        changed=(
                            legacy_signal.decision_signal != signal.decision_signal
                            or round(legacy_signal.score, 2) != round(signal.score, 2)
                        ),
                        summary=(
                            f"Legacy replay comparison {legacy_signal.decision_signal} {legacy_signal.score:.2f} "
                            f"vs layered {signal.decision_signal} {signal.score:.2f}."
                        ),
                    )
                future_price = self._future_price(rows, observed_at=observed_at, horizon=PRIMARY_HOLDING_HORIZON)
                raw_return = None
                adjusted_return = None
                if signal.decision_signal in {"BUY", "SELL"} and future_price is not None:
                    raw_return = self.repo._signal_return(
                        signal=signal.decision_signal,
                        entry_price=price,
                        future_price=future_price,
                    )
                    adjusted_return = (
                        self.repo._apply_friction_to_return(raw_return, asset_type=asset_type)
                        if request.apply_friction
                        else raw_return
                    )
                output_rows.append(
                    ReplaySignalRow(
                        symbol=symbol,
                        asset_type=asset_type,
                        observed_at=observed_at,
                        strategy_variant=strategy_variant,
                        signal=signal.decision_signal,
                        raw_score=signal.score,
                        calibrated_confidence=calibrated_confidence,
                        evidence_quality=strategy_metadata.evidence_quality,
                        execution_eligibility=strategy_metadata.execution_eligibility,
                        strategy_version=STRATEGY_VERSION,
                        market_status=market_status,
                        provider_status=provider_status,
                        comparison=comparison,
                        entry_price=round(price, 4),
                        future_price=round(future_price, 4) if future_price is not None else None,
                        raw_return_pct=raw_return,
                        friction_adjusted_return_pct=adjusted_return,
                    )
                )

        actionable_rows = [row for row in output_rows if row.signal in {"BUY", "SELL"}]
        eligible_rows = [row for row in actionable_rows if row.execution_eligibility == "eligible"]
        raw_returns = [row.raw_return_pct for row in actionable_rows if row.raw_return_pct is not None]
        adjusted_returns = [
            row.friction_adjusted_return_pct for row in actionable_rows if row.friction_adjusted_return_pct is not None
        ]
        win_rate = None
        if raw_returns:
            wins = sum(1 for value in raw_returns if value > 0)
            win_rate = round((wins / len(raw_returns)) * 100, 2)
        avg_return = round(sum(raw_returns) / len(raw_returns), 4) if raw_returns else None
        avg_return_after_friction = round(sum(adjusted_returns) / len(adjusted_returns), 4) if adjusted_returns else None

        return ReplayResponse(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            strategy_variant=strategy_variant,
            compare_strategy_variant=compare_strategy_variant,
            start=request.start,
            end=request.end,
            interval_minutes=request.interval_minutes,
            warmup_bars=request.warmup_bars,
            apply_friction=request.apply_friction,
            friction=self._friction(),
            assumptions=[
                ENTRY_ASSUMPTION,
                EXIT_ASSUMPTION,
                "Replay uses only bar history up to each replay timestamp and does not look ahead during signal generation.",
                "Secondary providers are intentionally omitted unless a later replay phase adds historical provider reconstruction.",
            ],
            summary=ReplaySummary(
                total_snapshots=len(output_rows),
                actionable_signals=len(actionable_rows),
                eligible_signals=len(eligible_rows),
                blocked_signals=max(len(actionable_rows) - len(eligible_rows), 0),
                win_rate=win_rate,
                avg_return=avg_return,
                avg_return_after_friction=avg_return_after_friction,
                expectancy=avg_return,
                expectancy_after_friction=avg_return_after_friction,
            ),
            rows=output_rows,
        )
