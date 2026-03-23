from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from statistics import median

from sqlalchemy import desc, or_, select

from app.config import get_settings
from app.core.signals import map_score_to_decision_signal
from app.db import SessionLocal
from app.models.journal import JournalEntryORM
from app.models.scan import ExecutionAuditORM, ScanRunORM, ScanResultORM, SignalOutcomeORM
from app.schemas import (
    AssetType,
    CohortValidationSummary,
    DecisionRow,
    DecisionSignal,
    ExecutionAlignmentResponse,
    GateCheck,
    ScanRun,
    ScanResult,
    SignalOutcome,
    SignalOutcomePerformanceBucket,
    SignalOutcomeSummary,
    ThresholdSweepResponse,
    ThresholdSweepRow,
    ValidationBucket,
    ValidationSummary,
)


@dataclass(frozen=True)
class PendingSignalOutcomeEvaluation:
    outcome_id: int
    ticker: str
    asset_type: str
    horizon: str
    target_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class OutcomeEvaluationUpdate:
    outcome_id: int
    horizon: str
    status: str
    price: float | None
    evaluated_at: datetime


@dataclass(frozen=True)
class LatestSignalContext:
    run_id: str
    symbol: str
    asset_type: str
    signal: DecisionSignal
    raw_score: float
    calibrated_confidence: float
    calibration_source: str
    score_band: str
    signal_generated_at: datetime
    last_updated: datetime


class ScanRepository:
    _OUTCOME_HORIZONS = {
        "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1),
        "1d": timedelta(days=1),
    }
    _OUTCOME_EXPIRY_WINDOWS = {
        "15m": timedelta(hours=8),
        "1h": timedelta(days=2),
        "1d": timedelta(days=5),
    }
    _CALIBRATION_MIN_SIGNAL_SAMPLES = 20
    _CALIBRATION_MIN_SCORE_BAND_SAMPLES = 10

    def __init__(self) -> None:
        self.settings = get_settings()

    def _confidence_bucket(self, confidence: float) -> str:
        if confidence >= 75:
            return "75-100"
        if confidence >= 60:
            return "60-74"
        if confidence >= 45:
            return "45-59"
        return "0-44"

    def confidence_bucket_for(self, confidence: float) -> str:
        return self._confidence_bucket(confidence)

    def _asset_type_for_symbol(self, symbol: str) -> str:
        return "crypto" if "/" in symbol else "stock"

    def _raw_score_for(self, row: SignalOutcomeORM) -> float:
        return float(getattr(row, "raw_score", row.confidence) or 0.0)

    def _is_actionable_signal(self, signal: str) -> bool:
        return signal in {"BUY", "SELL"}

    def _score_band(self, score: float) -> str:
        if score >= 90:
            return "90-100"
        if score >= 80:
            return "80-89"
        if score >= 70:
            return "70-79"
        if score >= 60:
            return "60-69"
        return "0-59"

    def _signal_return(
        self,
        *,
        signal: str,
        entry_price: float,
        future_price: float | None,
    ) -> float | None:
        if future_price is None or entry_price <= 0:
            return None
        raw_return = ((future_price - entry_price) / entry_price) * 100
        if signal == "SELL":
            raw_return *= -1
        return round(raw_return, 4)

    def _return_for_horizon(self, row: SignalOutcomeORM, horizon: str) -> float | None:
        if horizon == "15m":
            return self._signal_return(
                signal=row.signal,
                entry_price=row.entry_price,
                future_price=row.price_after_15m,
            )
        if horizon == "1d":
            return self._signal_return(
                signal=row.signal,
                entry_price=row.entry_price,
                future_price=row.price_after_1d,
            )
        return self._signal_return(
            signal=row.signal,
            entry_price=row.entry_price,
            future_price=row.price_after_1h,
        )

    def _validation_horizon(self) -> str:
        return self.settings.validation_primary_horizon

    def _is_validation_win(self, value: float) -> bool:
        return value > self.settings.validation_win_threshold_pct

    def _is_false_positive(self, value: float) -> bool:
        return value <= self.settings.validation_false_positive_threshold_pct

    def _avg(self, values: list[float]) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), 4)

    def _median(self, values: list[float]) -> float | None:
        if not values:
            return None
        return round(float(median(values)), 4)

    def _build_validation_bucket(
        self,
        *,
        key: str,
        rows: list[SignalOutcomeORM],
        horizon: str | None = None,
    ) -> ValidationBucket:
        selected_horizon = horizon or self._validation_horizon()
        returns = [
            value
            for value in (self._return_for_horizon(row, selected_horizon) for row in rows)
            if value is not None
        ]
        wins = [value for value in returns if self._is_validation_win(value)]
        losses = [value for value in returns if not self._is_validation_win(value)]
        false_positives = [value for value in returns if self._is_false_positive(value)]
        win_rate = round((len(wins) / len(returns)) * 100, 2) if returns else None
        false_positive_rate = round((len(false_positives) / len(returns)) * 100, 2) if returns else None
        avg_win_return = self._avg(wins)
        avg_loss_return = self._avg(losses)
        expectancy = None
        if returns:
            expectancy = round(
                ((len(wins) / len(returns)) * (avg_win_return or 0.0))
                + ((len(losses) / len(returns)) * (avg_loss_return or 0.0)),
                4,
            )
        return ValidationBucket(
            key=key,
            total_signals=len(rows),
            evaluated_count=len(returns),
            pending_count=max(len(rows) - len(returns), 0),
            win_count=len(wins),
            loss_count=len(losses),
            false_positive_count=len(false_positives),
            win_rate=win_rate,
            avg_return=self._avg(returns),
            median_return=self._median(returns),
            avg_win_return=avg_win_return,
            avg_loss_return=avg_loss_return,
            expectancy=expectancy,
            false_positive_rate=false_positive_rate,
        )

    def _serialize_gate_checks(self, checks: list[GateCheck]) -> str | None:
        if not checks:
            return None
        return json.dumps([check.model_dump() for check in checks])

    def _serialize_list(self, values: list[str]) -> str | None:
        if not values:
            return None
        return json.dumps(values)

    def _deserialize_list(self, raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in decoded if isinstance(item, str)]

    def _deserialize_gate_checks(self, raw_value: str | None) -> list[GateCheck]:
        if not raw_value:
            return []
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError:
            return []
        return [GateCheck(**item) for item in decoded if isinstance(item, dict)]

    def _bucket_metrics(
        self,
        bucket: SignalOutcomePerformanceBucket | None,
        *,
        horizon: str,
    ) -> tuple[int | None, float | None, float | None]:
        if bucket is None:
            return None, None, None
        if horizon == "15m":
            return bucket.evaluated_15m_count, bucket.win_rate_15m, bucket.avg_return_15m
        if horizon == "1d":
            return bucket.evaluated_1d_count, bucket.win_rate_1d, bucket.avg_return_1d
        return bucket.evaluated_1h_count, bucket.win_rate_1h, bucket.avg_return_1h

    def bucket_metrics_for_horizon(
        self,
        *,
        bucket: SignalOutcomePerformanceBucket | None,
        horizon: str,
    ) -> tuple[int | None, float | None, float | None]:
        return self._bucket_metrics(bucket, horizon=horizon)

    def _calibrate_confidence(
        self,
        *,
        signal: DecisionSignal,
        raw_score: float,
        summary: SignalOutcomeSummary,
        horizon: str = "1h",
    ) -> tuple[float, str, str]:
        score_band = self._score_band(raw_score)
        band_bucket = next(
            (bucket for bucket in summary.by_signal_score_bucket if bucket.key == f"{signal}:{score_band}"),
            None,
        )
        signal_bucket = next(
            (bucket for bucket in summary.by_signal if bucket.key == signal),
            None,
        )
        band_count, band_win_rate, band_avg_return = self._bucket_metrics(band_bucket, horizon=horizon)
        signal_count, signal_win_rate, signal_avg_return = self._bucket_metrics(signal_bucket, horizon=horizon)

        def blend(
            *,
            base_score: float,
            win_rate: float | None,
            avg_return: float | None,
            weight: float,
        ) -> float:
            if win_rate is None:
                return round(base_score, 2)
            return round(
                max(
                    0.0,
                    min(
                        100.0,
                        (base_score * (1 - weight))
                        + (win_rate * weight)
                        + max(min((avg_return or 0.0) * 5, 5), -5),
                    ),
                ),
                2,
            )

        if (band_count or 0) >= self._CALIBRATION_MIN_SCORE_BAND_SAMPLES and band_win_rate is not None:
            return (
                blend(base_score=raw_score, win_rate=band_win_rate, avg_return=band_avg_return, weight=0.65),
                score_band,
                "score_band",
            )
        if (signal_count or 0) >= self._CALIBRATION_MIN_SIGNAL_SAMPLES and signal_win_rate is not None:
            return (
                blend(base_score=raw_score, win_rate=signal_win_rate, avg_return=signal_avg_return, weight=0.5),
                score_band,
                "signal",
            )
        return round(raw_score, 2), score_band, "raw"

    def calibrate_signal(
        self,
        *,
        asset_type: AssetType,
        signal: DecisionSignal,
        raw_score: float,
        horizon: str = "1h",
    ) -> tuple[float, str, str]:
        summary = self.get_signal_outcome_summary(asset_type=asset_type)
        calibrated_confidence, score_band, source = self._calibrate_confidence(
            signal=signal,
            raw_score=raw_score,
            summary=summary,
            horizon=horizon,
        )
        if source != "raw":
            return calibrated_confidence, score_band, source
        fallback_summary = self.get_signal_outcome_summary()
        if fallback_summary.total_signals == summary.total_signals:
            return calibrated_confidence, score_band, source
        return self._calibrate_confidence(
            signal=signal,
            raw_score=raw_score,
            summary=fallback_summary,
            horizon=horizon,
        )

    def _resolve_decision_signal(self, result: ScanResultORM) -> DecisionSignal:
        return map_score_to_decision_signal(
            score=result.score,
            price_change_pct=result.price_change_pct,
            decision_signal=getattr(result, "decision_signal", None),
            buy_score=getattr(result, "buy_score", None),
            sell_score=getattr(result, "sell_score", None),
            scoring_version=getattr(result, "scoring_version", None),
        )

    def _sort_results_for_display(self, rows: list[ScanResultORM]) -> list[ScanResultORM]:
        return sorted(
            rows,
            key=lambda row: (
                0 if getattr(row, "gate_passed", False) and self._resolve_decision_signal(row) in {"BUY", "SELL"} else 1 if self._resolve_decision_signal(row) in {"BUY", "SELL"} else 2,
                -float(row.score),
                row.ticker,
            ),
        )

    def _build_decision_row(
        self,
        result: ScanResultORM,
        *,
        summary: SignalOutcomeSummary | None = None,
        horizon: str = "1h",
    ) -> DecisionRow:
        decision_signal = self._resolve_decision_signal(result)
        calibrated_confidence = round(getattr(result, "calibrated_confidence", result.score) or result.score, 2)
        calibration_source = getattr(result, "calibration_source", "raw") or "raw"
        if summary is not None and self._is_actionable_signal(decision_signal):
            calibrated_confidence, _, calibration_source = self._calibrate_confidence(
                signal=decision_signal,
                raw_score=result.score,
                summary=summary,
                horizon=horizon,
            )
        return DecisionRow(
            symbol=result.ticker,
            asset_type=getattr(result, "asset_type", self._asset_type_for_symbol(result.ticker)),
            signal=decision_signal,
            confidence=calibrated_confidence,
            calibration_source=calibration_source,
            short_metric_summary=(
                f"{result.price_change_pct:.1f}% day | "
                f"{result.relative_volume:.1f}x vol | "
                f"flow {result.options_flow_score:.0f}"
            ),
            last_updated=result.created_at,
        )

    def _normalize_comparable_datetimes(
        self,
        first: datetime,
        second: datetime,
    ) -> tuple[datetime, datetime]:
        normalized_first = first
        normalized_second = second
        if first.tzinfo is None and second.tzinfo is not None:
            normalized_second = second.replace(tzinfo=None)
        elif first.tzinfo is not None and second.tzinfo is None:
            normalized_first = first.replace(tzinfo=None)
        return normalized_first, normalized_second

    def _build_outcome_bucket(
        self,
        *,
        key: str,
        rows: list[SignalOutcomeORM],
    ) -> SignalOutcomePerformanceBucket:
        returns_15m = [
            value
            for value in (self._return_for_horizon(row, "15m") for row in rows)
            if value is not None
        ]
        returns_1h = [
            value
            for value in (self._return_for_horizon(row, "1h") for row in rows)
            if value is not None
        ]
        returns_1d = [
            value
            for value in (self._return_for_horizon(row, "1d") for row in rows)
            if value is not None
        ]

        def win_rate(values: list[float]) -> float | None:
            if not values:
                return None
            wins = sum(1 for value in values if self._is_validation_win(value))
            return round((wins / len(values)) * 100, 2)

        return SignalOutcomePerformanceBucket(
            key=key,
            total_signals=len(rows),
            evaluated_15m_count=len(returns_15m),
            win_rate_15m=win_rate(returns_15m),
            avg_return_15m=self._avg(returns_15m),
            evaluated_1h_count=len(returns_1h),
            win_rate_1h=win_rate(returns_1h),
            avg_return_1h=self._avg(returns_1h),
            evaluated_1d_count=len(returns_1d),
            win_rate_1d=win_rate(returns_1d),
            avg_return_1d=self._avg(returns_1d),
        )

    def save_run(self, run: ScanRun) -> None:
        with SessionLocal() as session:
            session.add(
                ScanRunORM(
                    run_id=run.run_id,
                    created_at=run.created_at,
                    market_status=run.market_status,
                    scan_count=run.scan_count,
                    watchlist_size=run.watchlist_size,
                    alerts_sent=run.alerts_sent,
                    fear_greed_value=run.fear_greed_value,
                    fear_greed_label=run.fear_greed_label,
                )
            )

            for result in run.results:
                session.add(
                    ScanResultORM(
                        run_id=run.run_id,
                        created_at=result.created_at,
                        ticker=result.ticker,
                        asset_type=result.asset_type,
                        score=result.score,
                        calibrated_confidence=result.calibrated_confidence,
                        calibration_source=result.calibration_source,
                        buy_score=result.buy_score,
                        sell_score=result.sell_score,
                        decision_signal=result.decision_signal,
                        scoring_version=result.scoring_version,
                        explanation=result.explanation,
                        price=result.price,
                        price_change_pct=result.price_change_pct,
                        relative_volume=result.relative_volume,
                        sentiment_score=result.sentiment_score,
                        filing_flag=result.filing_flag,
                        breakout_flag=result.breakout_flag,
                        market_status=result.market_status,
                        sector_strength_score=result.sector_strength_score,
                        relative_strength_pct=getattr(result, "relative_strength_pct", 0.0) or 0.0,
                        options_flow_score=result.options_flow_score,
                        options_flow_summary=result.options_flow_summary,
                        options_flow_bullish=result.options_flow_bullish,
                        options_call_put_ratio=result.options_call_put_ratio,
                        alert_sent=result.alert_sent,
                        news_checked=result.news_checked,
                        news_source=result.news_source,
                        news_cache_label=result.news_cache_label,
                        signal_label=result.signal_label,
                        data_quality=result.data_quality,
                        volatility_regime=result.volatility_regime,
                        benchmark_ticker=result.benchmark_ticker,
                        benchmark_change_pct=result.benchmark_change_pct,
                        gate_passed=result.gate_passed,
                        gate_reason=result.gate_reason,
                        gate_checks_json=self._serialize_gate_checks(getattr(result, "gate_checks", [])),
                        coingecko_price_change_pct_24h=result.coingecko_price_change_pct_24h,
                        coingecko_market_cap_rank=result.coingecko_market_cap_rank,
                        fear_greed_value=result.fear_greed_value,
                        fear_greed_label=result.fear_greed_label,
                        provider_status=getattr(result, "provider_status", "ok") or "ok",
                        provider_warnings_json=self._serialize_list(
                            getattr(result, "provider_warnings", [])
                        ),
                    )
                )
                if self._is_actionable_signal(result.decision_signal):
                    session.add(
                        SignalOutcomeORM(
                            run_id=run.run_id,
                            ticker=result.ticker,
                            asset_type=result.asset_type,
                            signal=result.decision_signal,
                            confidence=result.score,
                            calibrated_confidence=result.calibrated_confidence,
                            calibration_source=result.calibration_source,
                            raw_score=result.score,
                            score_band=self._score_band(result.score),
                            scoring_version=result.scoring_version,
                            market_status=result.market_status,
                            buy_score=result.buy_score,
                            sell_score=result.sell_score,
                            signal_label=result.signal_label,
                            gate_passed=result.gate_passed,
                            gate_reason=result.gate_reason,
                            news_source=result.news_source,
                            relative_volume=result.relative_volume,
                            price_change_pct=result.price_change_pct,
                            relative_strength_pct=getattr(result, "relative_strength_pct", None),
                            options_flow_score=result.options_flow_score,
                            options_flow_bullish=result.options_flow_bullish,
                            volatility_regime=result.volatility_regime,
                            data_quality=result.data_quality,
                            benchmark_change_pct=result.benchmark_change_pct,
                            entry_price=result.price,
                            generated_at=result.created_at,
                        )
                    )

            session.commit()

    def _map_run(self, run: ScanRunORM, results: list[ScanResultORM]) -> ScanRun:
        return ScanRun(
            run_id=run.run_id,
            created_at=run.created_at,
            market_status=run.market_status,
            scan_count=run.scan_count,
            watchlist_size=run.watchlist_size,
            alerts_sent=run.alerts_sent,
            fear_greed_value=getattr(run, "fear_greed_value", None),
            fear_greed_label=getattr(run, "fear_greed_label", None),
            results=[
                ScanResult(
                    ticker=r.ticker,
                    asset_type=getattr(r, "asset_type", "stock") or "stock",
                    score=r.score,
                    calibrated_confidence=getattr(r, "calibrated_confidence", r.score) or r.score,
                    calibration_source=getattr(r, "calibration_source", "raw") or "raw",
                    buy_score=getattr(r, "buy_score", 0.0) or 0.0,
                    sell_score=getattr(r, "sell_score", 0.0) or 0.0,
                    decision_signal=self._resolve_decision_signal(r),
                    scoring_version=getattr(r, "scoring_version", "v2-directional") or "v2-directional",
                    explanation=r.explanation,
                    price=r.price,
                    price_change_pct=r.price_change_pct,
                    relative_volume=r.relative_volume,
                    sentiment_score=r.sentiment_score,
                    filing_flag=r.filing_flag,
                    breakout_flag=r.breakout_flag,
                    market_status=r.market_status,
                    sector_strength_score=r.sector_strength_score,
                    relative_strength_pct=getattr(r, "relative_strength_pct", 0.0) or 0.0,
                    options_flow_score=r.options_flow_score,
                    options_flow_summary=r.options_flow_summary,
                    options_flow_bullish=r.options_flow_bullish,
                    options_call_put_ratio=r.options_call_put_ratio,
                    alert_sent=r.alert_sent,
                    news_checked=r.news_checked,
                    news_source=r.news_source,
                    news_cache_label=r.news_cache_label,
                    signal_label=r.signal_label,
                    data_quality=getattr(r, "data_quality", "ok") or "ok",
                    volatility_regime=getattr(r, "volatility_regime", "normal") or "normal",
                    benchmark_ticker=getattr(r, "benchmark_ticker", None),
                    benchmark_change_pct=getattr(r, "benchmark_change_pct", None),
                    gate_passed=bool(getattr(r, "gate_passed", False)),
                    gate_reason=getattr(r, "gate_reason", "Signal gate not evaluated.") or "Signal gate not evaluated.",
                    gate_checks=self._deserialize_gate_checks(getattr(r, "gate_checks_json", None)),
                    coingecko_price_change_pct_24h=getattr(r, "coingecko_price_change_pct_24h", None),
                    coingecko_market_cap_rank=getattr(r, "coingecko_market_cap_rank", None),
                    fear_greed_value=getattr(r, "fear_greed_value", None),
                    fear_greed_label=getattr(r, "fear_greed_label", None),
                    provider_status=getattr(r, "provider_status", "ok") or "ok",
                    provider_warnings=self._deserialize_list(
                        getattr(r, "provider_warnings_json", None)
                    ),
                    created_at=r.created_at,
                )
                for r in results
            ],
        )

    def get_latest_run(self) -> ScanRun | None:
        with SessionLocal() as session:
            latest = session.execute(
                select(ScanRunORM).order_by(desc(ScanRunORM.created_at)).limit(1)
            ).scalar_one_or_none()

            if not latest:
                return None

            results = session.execute(
                select(ScanResultORM)
                .where(ScanResultORM.run_id == latest.run_id)
            ).scalars().all()

            return self._map_run(latest, self._sort_results_for_display(results))

    def get_run_history(self, limit: int = 12) -> list[ScanRun]:
        with SessionLocal() as session:
            runs = session.execute(
                select(ScanRunORM)
                .order_by(desc(ScanRunORM.created_at))
                .limit(limit)
            ).scalars().all()

            output: list[ScanRun] = []
            for run in runs:
                results = session.execute(
                    select(ScanResultORM)
                    .where(ScanResultORM.run_id == run.run_id)
                ).scalars().all()

                output.append(self._map_run(run, self._sort_results_for_display(results)))

            return output

    def get_latest_decisions(self, limit: int = 20) -> list[DecisionRow]:
        with SessionLocal() as session:
            latest = session.execute(
                select(ScanRunORM).order_by(desc(ScanRunORM.created_at)).limit(1)
            ).scalar_one_or_none()

            if not latest:
                return []

            results = session.execute(
                select(ScanResultORM)
                .where(ScanResultORM.run_id == latest.run_id)
            ).scalars().all()

            sorted_rows = self._sort_results_for_display(results)[:limit]
            summaries = {
                "stock": self.get_signal_outcome_summary(asset_type="stock"),
                "crypto": self.get_signal_outcome_summary(asset_type="crypto"),
            }
            return [
                self._build_decision_row(
                    r,
                    summary=summaries.get(getattr(r, "asset_type", self._asset_type_for_symbol(r.ticker))),
                    horizon=self.settings.trade_gate_horizon,
                )
                for r in sorted_rows
            ]

    def get_latest_decision_for_symbol(self, symbol: str) -> DecisionRow | None:
        with SessionLocal() as session:
            latest = session.execute(
                select(ScanRunORM).order_by(desc(ScanRunORM.created_at)).limit(1)
            ).scalar_one_or_none()

            if not latest:
                return None

            row = session.execute(
                select(ScanResultORM)
                .where(
                    ScanResultORM.run_id == latest.run_id,
                    ScanResultORM.ticker == symbol.upper(),
                )
                .order_by(desc(ScanResultORM.score))
                .limit(1)
            ).scalar_one_or_none()

            if not row:
                return None

            return self._build_decision_row(
                row,
                summary=self.get_signal_outcome_summary(
                    asset_type=getattr(row, "asset_type", self._asset_type_for_symbol(row.ticker)),
                ),
                horizon=self.settings.trade_gate_horizon,
            )

    def get_latest_signal_context(self, symbol: str) -> LatestSignalContext | None:
        with SessionLocal() as session:
            latest = session.execute(
                select(ScanRunORM).order_by(desc(ScanRunORM.created_at)).limit(1)
            ).scalar_one_or_none()
            if not latest:
                return None

            row = session.execute(
                select(ScanResultORM)
                .where(
                    ScanResultORM.run_id == latest.run_id,
                    ScanResultORM.ticker == symbol.upper(),
                )
                .order_by(desc(ScanResultORM.score))
                .limit(1)
            ).scalar_one_or_none()
            if not row:
                return None

            signal = self._resolve_decision_signal(row)
            score_band = self._score_band(row.score)
            calibrated_confidence = round(getattr(row, "calibrated_confidence", row.score) or row.score, 2)
            calibration_source = getattr(row, "calibration_source", "raw") or "raw"
            if self._is_actionable_signal(signal):
                calibrated_confidence, score_band, calibration_source = self.calibrate_signal(
                    asset_type=getattr(row, "asset_type", self._asset_type_for_symbol(symbol)),
                    signal=signal,
                    raw_score=row.score,
                    horizon=self.settings.trade_gate_horizon,
                )
            return LatestSignalContext(
                run_id=row.run_id,
                symbol=row.ticker,
                asset_type=getattr(row, "asset_type", self._asset_type_for_symbol(symbol)),
                signal=signal,
                raw_score=row.score,
                calibrated_confidence=calibrated_confidence,
                calibration_source=calibration_source,
                score_band=score_band,
                signal_generated_at=row.created_at,
                last_updated=row.created_at,
            )

    def get_latest_run_timestamp(self) -> datetime | None:
        with SessionLocal() as session:
            latest = session.execute(
                select(ScanRunORM.created_at).order_by(desc(ScanRunORM.created_at)).limit(1)
            ).scalar_one_or_none()
            return latest

    def list_due_signal_outcome_evaluations(
        self,
        *,
        observed_at: datetime,
        limit: int = 500,
    ) -> list[PendingSignalOutcomeEvaluation]:
        with SessionLocal() as session:
            rows = session.execute(
                select(SignalOutcomeORM)
                .where(
                    or_(
                        SignalOutcomeORM.price_after_15m.is_(None),
                        SignalOutcomeORM.price_after_1h.is_(None),
                        SignalOutcomeORM.price_after_1d.is_(None),
                    )
                )
                .order_by(SignalOutcomeORM.generated_at)
                .limit(limit)
            ).scalars().all()

            due_evaluations: list[PendingSignalOutcomeEvaluation] = []
            for row in rows:
                generated_at, comparable_observed_at = self._normalize_comparable_datetimes(
                    row.generated_at,
                    observed_at,
                )

                for horizon, delta in self._OUTCOME_HORIZONS.items():
                    target_at = generated_at + delta
                    if comparable_observed_at < target_at:
                        continue
                    expires_at = target_at + self._OUTCOME_EXPIRY_WINDOWS[horizon]

                    if (
                        horizon == "15m"
                        and row.price_after_15m is None
                        and getattr(row, "status_15m", "pending") == "pending"
                    ):
                        due_evaluations.append(
                            PendingSignalOutcomeEvaluation(
                                outcome_id=row.id,
                                ticker=row.ticker,
                                asset_type=getattr(row, "asset_type", "stock") or "stock",
                                horizon=horizon,
                                target_at=target_at,
                                expires_at=expires_at,
                            )
                        )
                    elif (
                        horizon == "1h"
                        and row.price_after_1h is None
                        and getattr(row, "status_1h", "pending") == "pending"
                    ):
                        due_evaluations.append(
                            PendingSignalOutcomeEvaluation(
                                outcome_id=row.id,
                                ticker=row.ticker,
                                asset_type=getattr(row, "asset_type", "stock") or "stock",
                                horizon=horizon,
                                target_at=target_at,
                                expires_at=expires_at,
                            )
                        )
                    elif (
                        horizon == "1d"
                        and row.price_after_1d is None
                        and getattr(row, "status_1d", "pending") == "pending"
                    ):
                        due_evaluations.append(
                            PendingSignalOutcomeEvaluation(
                                outcome_id=row.id,
                                ticker=row.ticker,
                                asset_type=getattr(row, "asset_type", "stock") or "stock",
                                horizon=horizon,
                                target_at=target_at,
                                expires_at=expires_at,
                            )
                        )

            return due_evaluations

    def apply_signal_outcome_evaluations(
        self,
        evaluations: list[OutcomeEvaluationUpdate],
    ) -> int:
        if not evaluations:
            return 0

        with SessionLocal() as session:
            rows = {
                row.id: row
                for row in session.execute(
                    select(SignalOutcomeORM).where(
                        SignalOutcomeORM.id.in_([evaluation.outcome_id for evaluation in evaluations])
                    )
                ).scalars().all()
            }

            updated_count = 0
            for evaluation in evaluations:
                row = rows.get(evaluation.outcome_id)
                if row is None or row.entry_price <= 0:
                    continue

                if evaluation.horizon == "15m" and row.price_after_15m is None:
                    row.evaluated_at_15m = evaluation.evaluated_at
                    row.status_15m = evaluation.status
                    if evaluation.price is not None:
                        row.price_after_15m = round(evaluation.price, 4)
                        row.return_after_15m = self._signal_return(
                            signal=row.signal,
                            entry_price=row.entry_price,
                            future_price=evaluation.price,
                        )
                    updated_count += 1
                elif evaluation.horizon == "1h" and row.price_after_1h is None:
                    row.evaluated_at_1h = evaluation.evaluated_at
                    row.status_1h = evaluation.status
                    if evaluation.price is not None:
                        row.price_after_1h = round(evaluation.price, 4)
                        row.return_after_1h = self._signal_return(
                            signal=row.signal,
                            entry_price=row.entry_price,
                            future_price=evaluation.price,
                        )
                    updated_count += 1
                elif evaluation.horizon == "1d" and row.price_after_1d is None:
                    row.evaluated_at_1d = evaluation.evaluated_at
                    row.status_1d = evaluation.status
                    if evaluation.price is not None:
                        row.price_after_1d = round(evaluation.price, 4)
                        row.return_after_1d = self._signal_return(
                            signal=row.signal,
                            entry_price=row.entry_price,
                            future_price=evaluation.price,
                        )
                    updated_count += 1

            if updated_count:
                session.commit()

        return updated_count

    def list_signal_outcomes(self, limit: int = 50) -> list[SignalOutcome]:
        with SessionLocal() as session:
            rows = session.execute(
                select(SignalOutcomeORM)
                .order_by(desc(SignalOutcomeORM.generated_at))
                .limit(limit)
            ).scalars().all()

            return [
                SignalOutcome(
                    id=row.id,
                    run_id=row.run_id,
                    symbol=row.ticker,
                    asset_type=getattr(row, "asset_type", "stock") or "stock",
                    signal=row.signal,
                    confidence=self._raw_score_for(row),
                    calibrated_confidence=getattr(row, "calibrated_confidence", None),
                    calibration_source=getattr(row, "calibration_source", None),
                    raw_score=self._raw_score_for(row),
                    score_band=getattr(row, "score_band", self._score_band(self._raw_score_for(row))),
                    scoring_version=getattr(row, "scoring_version", None),
                    market_status=getattr(row, "market_status", None),
                    buy_score=getattr(row, "buy_score", None),
                    sell_score=getattr(row, "sell_score", None),
                    signal_label=getattr(row, "signal_label", None),
                    gate_passed=getattr(row, "gate_passed", None),
                    gate_reason=getattr(row, "gate_reason", None),
                    news_source=getattr(row, "news_source", None),
                    relative_volume=getattr(row, "relative_volume", None),
                    price_change_pct=getattr(row, "price_change_pct", None),
                    relative_strength_pct=getattr(row, "relative_strength_pct", None),
                    options_flow_score=getattr(row, "options_flow_score", None),
                    options_flow_bullish=getattr(row, "options_flow_bullish", None),
                    volatility_regime=getattr(row, "volatility_regime", None),
                    data_quality=getattr(row, "data_quality", None),
                    benchmark_change_pct=getattr(row, "benchmark_change_pct", None),
                    entry_price=row.entry_price,
                    generated_at=row.generated_at,
                    price_after_15m=row.price_after_15m,
                    return_after_15m=self._return_for_horizon(row, "15m"),
                    evaluated_at_15m=row.evaluated_at_15m,
                    status_15m=getattr(row, "status_15m", "pending"),
                    price_after_1h=row.price_after_1h,
                    return_after_1h=self._return_for_horizon(row, "1h"),
                    evaluated_at_1h=row.evaluated_at_1h,
                    status_1h=getattr(row, "status_1h", "pending"),
                    price_after_1d=row.price_after_1d,
                    return_after_1d=self._return_for_horizon(row, "1d"),
                    evaluated_at_1d=row.evaluated_at_1d,
                    status_1d=getattr(row, "status_1d", "pending"),
                )
                for row in rows
                if self._is_actionable_signal(row.signal)
            ]

    def get_signal_outcome_summary(self, asset_type: AssetType | None = None) -> SignalOutcomeSummary:
        with SessionLocal() as session:
            rows = session.execute(
                select(SignalOutcomeORM).order_by(desc(SignalOutcomeORM.generated_at))
            ).scalars().all()
            rows = [row for row in rows if self._is_actionable_signal(row.signal)]
            if asset_type is not None:
                rows = [
                    row
                    for row in rows
                    if (getattr(row, "asset_type", self._asset_type_for_symbol(row.ticker)) or "stock") == asset_type
                ]

            by_signal: dict[str, list[SignalOutcomeORM]] = {}
            by_confidence_bucket: dict[str, list[SignalOutcomeORM]] = {}
            by_signal_confidence_bucket: dict[str, list[SignalOutcomeORM]] = {}
            by_signal_score_bucket: dict[str, list[SignalOutcomeORM]] = {}
            for row in rows:
                by_signal.setdefault(row.signal, []).append(row)
                raw_score = self._raw_score_for(row)
                bucket = self._confidence_bucket(raw_score)
                score_band = getattr(row, "score_band", self._score_band(raw_score))
                by_confidence_bucket.setdefault(bucket, []).append(row)
                by_signal_confidence_bucket.setdefault(
                    f"{row.signal}:{bucket}",
                    [],
                ).append(row)
                by_signal_score_bucket.setdefault(
                    f"{row.signal}:{score_band}",
                    [],
                ).append(row)

            observed_at = datetime.now(timezone.utc)

            def due_pending_count(horizon: str) -> int:
                delta = self._OUTCOME_HORIZONS[horizon]
                count = 0
                for row in rows:
                    status_value = getattr(row, f"status_{horizon}", "pending")
                    if status_value != "pending":
                        continue
                    generated_at, comparable_observed_at = self._normalize_comparable_datetimes(
                        row.generated_at,
                        observed_at,
                    )
                    if comparable_observed_at >= generated_at + delta:
                        count += 1
                return count

            return SignalOutcomeSummary(
                total_signals=len(rows),
                pending_15m_count=due_pending_count("15m"),
                pending_1h_count=due_pending_count("1h"),
                pending_1d_count=due_pending_count("1d"),
                overall=self._build_outcome_bucket(key="overall", rows=rows),
                by_signal=[
                    self._build_outcome_bucket(key=key, rows=group_rows)
                    for key, group_rows in sorted(by_signal.items())
                ],
                by_confidence_bucket=[
                    self._build_outcome_bucket(key=key, rows=group_rows)
                    for key, group_rows in sorted(by_confidence_bucket.items())
                ],
                by_signal_confidence_bucket=[
                    self._build_outcome_bucket(key=key, rows=group_rows)
                    for key, group_rows in sorted(by_signal_confidence_bucket.items())
                ],
                by_signal_score_bucket=[
                    self._build_outcome_bucket(key=key, rows=group_rows)
                    for key, group_rows in sorted(by_signal_score_bucket.items())
                ],
            )

    def _load_signal_outcome_rows(
        self,
        *,
        asset_type: AssetType | None = None,
    ) -> list[SignalOutcomeORM]:
        with SessionLocal() as session:
            rows = session.execute(
                select(SignalOutcomeORM).order_by(desc(SignalOutcomeORM.generated_at))
            ).scalars().all()
        rows = [row for row in rows if self._is_actionable_signal(row.signal)]
        if asset_type is not None:
            rows = [
                row
                for row in rows
                if (getattr(row, "asset_type", self._asset_type_for_symbol(row.ticker)) or "stock") == asset_type
            ]
        return rows

    def _sort_validation_buckets(self, buckets: list[ValidationBucket]) -> list[ValidationBucket]:
        return sorted(
            buckets,
            key=lambda bucket: (
                -bucket.evaluated_count,
                -(bucket.expectancy if bucket.expectancy is not None else -999.0),
                bucket.key,
            ),
        )

    def _group_validation_buckets(
        self,
        rows: list[SignalOutcomeORM],
        *,
        key_fn,
    ) -> list[ValidationBucket]:
        grouped: dict[str, list[SignalOutcomeORM]] = {}
        for row in rows:
            key = key_fn(row)
            grouped.setdefault(key, []).append(row)
        buckets = [
            self._build_validation_bucket(key=key, rows=group_rows)
            for key, group_rows in grouped.items()
        ]
        return self._sort_validation_buckets(buckets)

    def get_signal_validation_summary(
        self,
        asset_type: AssetType | None = None,
    ) -> ValidationSummary:
        rows = self._load_signal_outcome_rows(asset_type=asset_type)
        overall = self._build_validation_bucket(key="overall", rows=rows)
        return ValidationSummary(
            primary_horizon=self._validation_horizon(),
            win_threshold_pct=self.settings.validation_win_threshold_pct,
            false_positive_threshold_pct=self.settings.validation_false_positive_threshold_pct,
            total_signals=len(rows),
            evaluated_count=overall.evaluated_count,
            pending_count=overall.pending_count,
            overall=overall,
            by_signal=self._group_validation_buckets(rows, key_fn=lambda row: row.signal),
            by_score_band=self._group_validation_buckets(
                rows,
                key_fn=lambda row: getattr(row, "score_band", self._score_band(self._raw_score_for(row))),
            ),
            by_signal_label=self._group_validation_buckets(
                rows,
                key_fn=lambda row: getattr(row, "signal_label", None) or "unknown",
            ),
            by_market_status=self._group_validation_buckets(
                rows,
                key_fn=lambda row: getattr(row, "market_status", None) or "unknown",
            ),
            by_news_source=self._group_validation_buckets(
                rows,
                key_fn=lambda row: getattr(row, "news_source", None) or "unknown",
            ),
            by_volatility_regime=self._group_validation_buckets(
                rows,
                key_fn=lambda row: getattr(row, "volatility_regime", None) or "unknown",
            ),
            by_data_quality=self._group_validation_buckets(
                rows,
                key_fn=lambda row: getattr(row, "data_quality", None) or "unknown",
            ),
            by_options_flow_bias=self._group_validation_buckets(
                rows,
                key_fn=lambda row: (
                    "bullish"
                    if getattr(row, "options_flow_bullish", None) is True
                    else "bearish"
                    if getattr(row, "options_flow_bullish", None) is False
                    else "unknown"
                ),
            ),
            by_gate_status=self._group_validation_buckets(
                rows,
                key_fn=lambda row: "passed" if getattr(row, "gate_passed", False) else "blocked",
            ),
            by_asset_type=self._group_validation_buckets(
                rows,
                key_fn=lambda row: getattr(row, "asset_type", self._asset_type_for_symbol(row.ticker)) or "stock",
            ),
        )

    def _passes_threshold_candidate(
        self,
        row: SignalOutcomeORM,
        *,
        signal_buckets: dict[str, ValidationBucket],
        score_band_buckets: dict[str, ValidationBucket],
        min_evaluated_count: int,
        min_win_rate: float,
        min_avg_return: float,
        score_band_required: bool,
    ) -> bool:
        signal_bucket = signal_buckets.get(row.signal)
        if signal_bucket is None or signal_bucket.evaluated_count < min_evaluated_count:
            return False
        if (signal_bucket.win_rate or 0.0) < min_win_rate:
            return False
        if (signal_bucket.avg_return or 0.0) < min_avg_return:
            return False
        if not score_band_required:
            return True

        score_band = getattr(row, "score_band", self._score_band(self._raw_score_for(row)))
        band_bucket = score_band_buckets.get(f"{row.signal}:{score_band}")
        if band_bucket is None or band_bucket.evaluated_count < min_evaluated_count:
            return False
        if (band_bucket.win_rate or 0.0) < min_win_rate:
            return False
        if (band_bucket.avg_return or 0.0) < min_avg_return:
            return False
        return True

    def get_validation_threshold_sweep(
        self,
        asset_type: AssetType | None = None,
    ) -> ThresholdSweepResponse:
        rows = self._load_signal_outcome_rows(asset_type=asset_type)
        baseline = self._build_validation_bucket(key="baseline", rows=rows)
        signal_buckets = {bucket.key: bucket for bucket in self._group_validation_buckets(rows, key_fn=lambda row: row.signal)}
        score_band_buckets = {
            bucket.key: bucket
            for bucket in self._group_validation_buckets(
                rows,
                key_fn=lambda row: f"{row.signal}:{getattr(row, 'score_band', self._score_band(self._raw_score_for(row)))}",
            )
        }

        candidates: list[ThresholdSweepRow] = []
        for min_evaluated_count in (5, 10, 20, 30):
            for min_win_rate in (50.0, 55.0, 60.0, 65.0):
                for min_avg_return in (0.0, 0.1, 0.15, 0.25):
                    for score_band_required in (False, True):
                        kept_rows = [
                            row
                            for row in rows
                            if self._passes_threshold_candidate(
                                row,
                                signal_buckets=signal_buckets,
                                score_band_buckets=score_band_buckets,
                                min_evaluated_count=min_evaluated_count,
                                min_win_rate=min_win_rate,
                                min_avg_return=min_avg_return,
                                score_band_required=score_band_required,
                            )
                        ]
                        if not kept_rows:
                            continue
                        kept_metrics = self._build_validation_bucket(
                            key="kept",
                            rows=kept_rows,
                        )
                        candidates.append(
                            ThresholdSweepRow(
                                min_evaluated_count=min_evaluated_count,
                                min_win_rate=min_win_rate,
                                min_avg_return=min_avg_return,
                                score_band_required=score_band_required,
                                kept_signals=len(kept_rows),
                                blocked_signals=max(len(rows) - len(kept_rows), 0),
                                kept_rate=round((len(kept_rows) / len(rows)) * 100, 2) if rows else 0.0,
                                win_rate=kept_metrics.win_rate,
                                avg_return=kept_metrics.avg_return,
                                expectancy=kept_metrics.expectancy,
                                false_positive_rate=kept_metrics.false_positive_rate,
                            )
                        )
        candidates = sorted(
            candidates,
            key=lambda row: (
                -(row.expectancy if row.expectancy is not None else -999.0),
                row.false_positive_rate if row.false_positive_rate is not None else 999.0,
                -row.kept_signals,
            ),
        )[:30]
        return ThresholdSweepResponse(
            primary_horizon=self._validation_horizon(),
            win_threshold_pct=self.settings.validation_win_threshold_pct,
            false_positive_threshold_pct=self.settings.validation_false_positive_threshold_pct,
            baseline=baseline,
            candidates=candidates,
        )

    def _build_cohort_summary(
        self,
        *,
        cohort: str,
        rows: list[SignalOutcomeORM],
    ) -> CohortValidationSummary:
        metrics = self._build_validation_bucket(key=cohort, rows=rows)
        return CohortValidationSummary(
            cohort=cohort,
            total_signals=metrics.total_signals,
            evaluated_count=metrics.evaluated_count,
            pending_count=metrics.pending_count,
            win_rate=metrics.win_rate,
            avg_return=metrics.avg_return,
            expectancy=metrics.expectancy,
            false_positive_rate=metrics.false_positive_rate,
        )

    def get_execution_alignment_summary(
        self,
        asset_type: AssetType | None = None,
    ) -> ExecutionAlignmentResponse:
        rows = self._load_signal_outcome_rows(asset_type=asset_type)
        with SessionLocal() as session:
            journal_rows = session.execute(
                select(JournalEntryORM).order_by(desc(JournalEntryORM.created_at))
            ).scalars().all()
            audit_rows = session.execute(
                select(ExecutionAuditORM).order_by(desc(ExecutionAuditORM.created_at))
            ).scalars().all()

        taken_keys = {
            (row.run_id, row.ticker.upper())
            for row in journal_rows
            if row.run_id and row.decision == "took"
        }
        skipped_keys = {
            (row.run_id, row.ticker.upper())
            for row in journal_rows
            if row.run_id and row.decision in {"skipped", "watching"}
        }
        blocked_keys = {
            (row.signal_run_id, row.ticker.upper())
            for row in audit_rows
            if row.signal_run_id and row.trade_gate_allowed is False
        }
        taken_rows = [row for row in rows if (row.run_id, row.ticker.upper()) in taken_keys]
        skipped_rows = [
            row
            for row in rows
            if (row.run_id, row.ticker.upper()) in skipped_keys
            and (row.run_id, row.ticker.upper()) not in taken_keys
        ]
        blocked_rows = [row for row in rows if (row.run_id, row.ticker.upper()) in blocked_keys]
        return ExecutionAlignmentResponse(
            primary_horizon=self._validation_horizon(),
            win_threshold_pct=self.settings.validation_win_threshold_pct,
            false_positive_threshold_pct=self.settings.validation_false_positive_threshold_pct,
            all_signals=self._build_cohort_summary(cohort="all_signals", rows=rows),
            taken_trades=self._build_cohort_summary(cohort="taken_trades", rows=taken_rows),
            skipped_or_watched=self._build_cohort_summary(cohort="skipped_or_watched", rows=skipped_rows),
            blocked_previews=self._build_cohort_summary(cohort="blocked_previews", rows=blocked_rows),
        )
