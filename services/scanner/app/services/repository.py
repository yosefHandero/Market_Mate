from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import json
from statistics import median, quantiles

from sqlalchemy import desc, or_, select

from app.config import get_settings
from app.core.freshness import signal_age_minutes as _signal_age_minutes
from app.core.signals import map_score_to_decision_signal
from app.core.strategy_contract import build_strategy_evaluation_metadata
from app.db import SessionLocal
from app.models.journal import JournalEntryORM
from app.models.scan import (
    AutomationIntentORM,
    ExecutionAuditORM,
    PaperPositionORM,
    ScanRunORM,
    ScanResultORM,
    SignalOutcomeORM,
)
from app.schemas import (
    AssetType,
    ReconciliationIssue,
    ReconciliationReportResponse,
    CohortValidationSummary,
    DecisionRow,
    DecisionSignal,
    ExecutionAuditSummary,
    ExecutionAlignmentResponse,
    GateCheck,
    HorizonMetrics,
    OutcomeBaselineCheck,
    OutcomeBaselineSummary,
    OutcomePerformanceSlice,
    PaperLedgerSummaryResponse,
    PaperPositionSummary,
    PromotionGateResult,
    PromotionReadinessResponse,
    ScanRun,
    ScanResult,
    SignalOutcomePerformanceBucket,
    SignalOutcomePerformanceReportResponse,
    SignalOutcomeSummary,
    ThresholdRecommendation,
    ThresholdSweepResponse,
    ThresholdSweepRow,
    ValidationBucket,
    ValidationSummary,
    VariantComparison,
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
    signal_outcome_id: int | None
    run_id: str
    symbol: str
    asset_type: str
    strategy_variant: str
    signal: DecisionSignal
    raw_score: float
    calibrated_confidence: float
    calibration_source: str
    score_band: str
    signal_generated_at: datetime
    last_updated: datetime
    gate_passed: bool
    gate_reason: str
    gate_checks: list[GateCheck]
    gate_evaluation_mode: str
    evidence_basis: str
    trust_window_start: datetime
    trust_window_end: datetime
    data_quality: str = "ok"
    provider_status: str = "ok"
    provider_warnings: list[str] | None = None
    layer_details: dict | None = None


@dataclass(frozen=True)
class EvidenceGateEvaluation:
    passed: bool
    reason: str
    horizon: str
    evidence_basis: str
    trust_window_start: datetime
    trust_window_end: datetime
    signal_count: int | None
    signal_win_rate: float | None
    signal_avg_return: float | None
    score_band_count: int | None
    score_band_win_rate: float | None
    score_band_avg_return: float | None
    checks: list[GateCheck]


@dataclass(frozen=True)
class TrustWindowBounds:
    start: datetime
    end: datetime
    days: int


@dataclass(frozen=True)
class TrustReadinessSnapshot:
    window: TrustWindowBounds
    summary: ValidationSummary
    threshold: ThresholdSweepResponse
    pending_due_15m_count: int
    pending_due_1h_count: int
    pending_due_1d_count: int


@dataclass(frozen=True)
class ProjectionOutcomeStats:
    signal: str
    score_band: str
    sample_count: int
    low_sample_size: bool
    median_daily_return_pct: float | None
    p25_daily_return_pct: float | None
    p75_daily_return_pct: float | None
    regime_shift_pct: float | None
    regime_data_available: bool
    current_regime: str | None


class ScanRepository:
    PROJECTION_HORIZON = "1h"
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

    def _stored_return_for_horizon(self, row: SignalOutcomeORM, horizon: str) -> float | None:
        if horizon == "15m":
            return getattr(row, "return_after_15m", None)
        if horizon == "1d":
            return getattr(row, "return_after_1d", None)
        return getattr(row, "return_after_1h", None)

    def _set_stored_return_for_horizon(
        self,
        row: SignalOutcomeORM,
        *,
        horizon: str,
        value: float | None,
    ) -> None:
        if horizon == "15m":
            row.return_after_15m = value
            return
        if horizon == "1d":
            row.return_after_1d = value
            return
        row.return_after_1h = value

    def sync_signal_outcome_returns(self) -> int:
        """Repair legacy rows whose stored return fields drifted from price-derived returns."""
        updated_count = 0
        with SessionLocal() as session:
            rows = session.execute(select(SignalOutcomeORM)).scalars().all()
            for row in rows:
                for horizon in self._OUTCOME_HORIZONS:
                    derived_return = self._return_for_horizon(row, horizon)
                    stored_return = self._stored_return_for_horizon(row, horizon)
                    if stored_return == derived_return:
                        continue
                    self._set_stored_return_for_horizon(
                        row,
                        horizon=horizon,
                        value=derived_return,
                    )
                    updated_count += 1
            if updated_count:
                session.commit()
        return updated_count

    def _validation_horizon(self) -> str:
        return self.settings.validation_primary_horizon

    def _trust_window_days(self) -> int:
        return max(int(self.settings.trust_recent_window_days), 1)

    def _trust_window_bounds(self, *, observed_at: datetime | None = None) -> TrustWindowBounds:
        comparable_end = self._normalize_report_datetime(observed_at or datetime.now(timezone.utc))
        if comparable_end is None:
            comparable_end = datetime.now(timezone.utc).replace(tzinfo=None)
        days = self._trust_window_days()
        return TrustWindowBounds(
            start=comparable_end - timedelta(days=days),
            end=comparable_end,
            days=days,
        )

    def trust_window_bounds_for(self, *, observed_at: datetime | None = None) -> tuple[datetime, datetime]:
        window = self._trust_window_bounds(observed_at=observed_at)
        return window.start, window.end

    def _evidence_basis_label(self, *, window: TrustWindowBounds) -> str:
        return f"recent_window:{window.days}d:generated_at"

    def _window_reason_suffix(self, *, window: TrustWindowBounds, horizon: str) -> str:
        start = window.start.isoformat()
        end = window.end.isoformat()
        return f"Evidence basis={self._evidence_basis_label(window=window)} horizon={horizon} window={start}..{end}."

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

    def _friction_bps_for_asset_type(self, asset_type: str) -> float:
        if asset_type == "crypto":
            return (
                float(self.settings.crypto_slippage_bps)
                + float(self.settings.crypto_spread_bps)
                + float(self.settings.crypto_fee_bps)
            )
        return (
            float(self.settings.stock_slippage_bps)
            + float(self.settings.stock_spread_bps)
            + float(self.settings.stock_fee_bps)
        )

    def _friction_multiplier(self, scenario: str) -> float:
        if scenario == "worst":
            return 2.5
        if scenario == "stressed":
            return 1.5
        return 1.0

    def _apply_friction_to_return(
        self,
        value: float | None,
        *,
        asset_type: str,
        scenario: str = "base",
    ) -> float | None:
        if value is None:
            return None
        friction = (self._friction_bps_for_asset_type(asset_type) * self._friction_multiplier(scenario)) / 100.0
        return round(value - friction, 4)

    def _age_bucket_for_row(self, row: SignalOutcomeORM) -> str:
        generated_at = getattr(row, "generated_at", None)
        evaluated_at = getattr(row, "evaluated_at_1h", None) or getattr(row, "evaluated_at_15m", None) or getattr(row, "evaluated_at_1d", None)
        if generated_at is None or evaluated_at is None:
            return "unknown"
        comparable_generated_at, comparable_evaluated_at = self._normalize_comparable_datetimes(
            generated_at,
            evaluated_at,
        )
        age_minutes = max((comparable_evaluated_at - comparable_generated_at).total_seconds() / 60, 0.0)
        if age_minutes <= 5:
            return "0-5m"
        if age_minutes <= 15:
            return "5-15m"
        if age_minutes <= 30:
            return "15-30m"
        return "30m+"

    def _strategy_metadata_for_result(
        self,
        *,
        signal: DecisionSignal,
        calibration_source: str,
        gate_passed: bool,
        data_quality: str,
        provider_status: str,
        provider_warnings: list[str] | None = None,
        layer_details: dict | None = None,
    ):
        metadata = build_strategy_evaluation_metadata(
            signal=signal,
            gate_passed=gate_passed,
            calibration_source=calibration_source,
            data_quality=data_quality,
            provider_status=provider_status,
            provider_warnings=provider_warnings or [],
        )
        review_flags = list(((layer_details or {}).get("execution") or {}).get("review_flags") or [])
        if review_flags and metadata.execution_eligibility == "eligible":
            return replace(metadata, execution_eligibility="review", data_grade="research")
        return metadata

    def _strategy_metadata_from_row(self, row: ScanResultORM):
        return self._strategy_metadata_for_result(
            signal=self._resolve_decision_signal(row),
            calibration_source=getattr(row, "calibration_source", "raw") or "raw",
            gate_passed=bool(getattr(row, "gate_passed", False)),
            data_quality=getattr(row, "data_quality", "ok") or "ok",
            provider_status=getattr(row, "provider_status", "ok") or "ok",
            provider_warnings=self._deserialize_list(getattr(row, "provider_warnings_json", None)),
            layer_details=self._deserialize_dict(getattr(row, "layer_details_json", None)),
        )

    def _build_validation_bucket(
        self,
        *,
        key: str,
        rows: list[SignalOutcomeORM],
        horizon: str | None = None,
        friction_scenario: str = "base",
    ) -> ValidationBucket:
        selected_horizon = horizon or self._validation_horizon()
        evaluated_rows = [
            (row, value)
            for row in rows
            for value in [self._return_for_horizon(row, selected_horizon)]
            if value is not None
        ]
        returns = [value for _, value in evaluated_rows]
        friction_adjusted_returns = [
            self._apply_friction_to_return(
                value,
                asset_type=getattr(
                    row,
                    "asset_type",
                    self._asset_type_for_symbol(getattr(row, "ticker", "AAPL")),
                ),
                scenario=friction_scenario,
            )
            for row, value in evaluated_rows
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
        adjusted_expectancy = None
        adjusted_avg_return = self._avg(
            [value for value in friction_adjusted_returns if value is not None]
        )
        adjusted_wins = [
            value for value in friction_adjusted_returns
            if value is not None and self._is_validation_win(value)
        ]
        adjusted_losses = [
            value for value in friction_adjusted_returns
            if value is not None and not self._is_validation_win(value)
        ]
        if friction_adjusted_returns:
            adjusted_expectancy = round(
                ((len(adjusted_wins) / len(friction_adjusted_returns)) * (self._avg(adjusted_wins) or 0.0))
                + ((len(adjusted_losses) / len(friction_adjusted_returns)) * (self._avg(adjusted_losses) or 0.0)),
                4,
            )
        min_sample_met = len(returns) >= self.settings.validation_min_sample_size
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
            avg_return_after_friction=adjusted_avg_return,
            expectancy_after_friction=adjusted_expectancy,
            false_positive_rate=false_positive_rate,
            min_sample_met=min_sample_met,
            is_underpowered=not min_sample_met,
        )

    def _normalize_report_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def _filter_loaded_signal_outcome_rows(
        self,
        rows: list[SignalOutcomeORM],
        *,
        asset_type: AssetType | None = None,
        generated_at_start: datetime | None = None,
        generated_at_end: datetime | None = None,
        gate_passed: bool | None = None,
    ) -> list[SignalOutcomeORM]:
        normalized_start = self._normalize_report_datetime(generated_at_start)
        normalized_end = self._normalize_report_datetime(generated_at_end)
        filtered = [row for row in rows if self._is_actionable_signal(row.signal)]
        if asset_type is not None:
            filtered = [
                row
                for row in filtered
                if (getattr(row, "asset_type", self._asset_type_for_symbol(row.ticker)) or "stock") == asset_type
            ]
        if gate_passed is not None:
            filtered = [row for row in filtered if bool(getattr(row, "gate_passed", False)) is gate_passed]
        if normalized_start is None and normalized_end is None:
            return filtered
        exact_filtered: list[SignalOutcomeORM] = []
        for row in filtered:
            generated_at = self._normalize_report_datetime(row.generated_at)
            if normalized_start is not None and generated_at is not None and generated_at < normalized_start:
                continue
            if normalized_end is not None and generated_at is not None and generated_at >= normalized_end:
                continue
            exact_filtered.append(row)
        return exact_filtered

    def _build_horizon_metrics(
        self,
        *,
        key: str,
        rows: list[SignalOutcomeORM],
        horizon: str,
        min_evaluated_count: int,
        friction_scenario: str = "base",
    ) -> HorizonMetrics:
        bucket = self._build_validation_bucket(
            key=key,
            rows=rows,
            horizon=horizon,
            friction_scenario=friction_scenario,
        )
        meets_min_sample = bucket.evaluated_count >= min_evaluated_count
        return HorizonMetrics(
            horizon=horizon,
            total_signals=bucket.total_signals,
            evaluated_count=bucket.evaluated_count,
            pending_count=bucket.pending_count,
            win_count=bucket.win_count,
            loss_count=bucket.loss_count,
            false_positive_count=bucket.false_positive_count,
            win_rate=bucket.win_rate,
            mean_return=bucket.avg_return,
            median_return=bucket.median_return,
            avg_win_return=bucket.avg_win_return,
            avg_loss_return=bucket.avg_loss_return,
            expectancy=bucket.expectancy,
            false_positive_rate=bucket.false_positive_rate,
            meets_min_sample=meets_min_sample,
            insufficient_sample=not meets_min_sample,
        )

    def _build_multi_horizon_slice(
        self,
        *,
        key: str,
        rows: list[SignalOutcomeORM],
        min_evaluated_count: int,
        friction_scenario: str = "base",
    ) -> OutcomePerformanceSlice:
        return OutcomePerformanceSlice(
            key=key,
            total_signals=len(rows),
            metrics_15m=self._build_horizon_metrics(
                key=key,
                rows=rows,
                horizon="15m",
                min_evaluated_count=min_evaluated_count,
                friction_scenario=friction_scenario,
            ),
            metrics_1h=self._build_horizon_metrics(
                key=key,
                rows=rows,
                horizon="1h",
                min_evaluated_count=min_evaluated_count,
                friction_scenario=friction_scenario,
            ),
            metrics_1d=self._build_horizon_metrics(
                key=key,
                rows=rows,
                horizon="1d",
                min_evaluated_count=min_evaluated_count,
                friction_scenario=friction_scenario,
            ),
        )

    def _slice_metrics(self, slice_summary: OutcomePerformanceSlice, *, horizon: str) -> HorizonMetrics:
        if horizon == "15m":
            return slice_summary.metrics_15m
        if horizon == "1d":
            return slice_summary.metrics_1d
        return slice_summary.metrics_1h

    def _sort_outcome_slices(self, slices: list[OutcomePerformanceSlice]) -> list[OutcomePerformanceSlice]:
        primary_horizon = self._validation_horizon()
        return sorted(
            slices,
            key=lambda bucket: (
                -self._slice_metrics(bucket, horizon=primary_horizon).evaluated_count,
                -bucket.total_signals,
                bucket.key,
            ),
        )

    def _group_outcome_performance_slices(
        self,
        rows: list[SignalOutcomeORM],
        *,
        key_fn,
        min_evaluated_count: int,
        friction_scenario: str = "base",
    ) -> list[OutcomePerformanceSlice]:
        grouped: dict[str, list[SignalOutcomeORM]] = {}
        for row in rows:
            key = key_fn(row)
            grouped.setdefault(key, []).append(row)
        slices = [
            self._build_multi_horizon_slice(
                key=key,
                rows=group_rows,
                min_evaluated_count=min_evaluated_count,
                friction_scenario=friction_scenario,
            )
            for key, group_rows in grouped.items()
        ]
        return self._sort_outcome_slices(slices)

    def _build_outcome_baseline_summary(
        self,
        *,
        slices_by_key: dict[str, OutcomePerformanceSlice],
    ) -> OutcomeBaselineSummary:
        primary_horizon = self._validation_horizon()
        min_evaluated_count = self.settings.outcome_baseline_min_evaluated_per_horizon
        min_mean_return_pct = self.settings.outcome_baseline_min_mean_return_pct
        checks: list[OutcomeBaselineCheck] = []
        details: list[str] = []

        for key in ("BUY:passed", "SELL:passed"):
            slice_summary = slices_by_key.get(key)
            metrics = (
                self._slice_metrics(slice_summary, horizon=primary_horizon)
                if slice_summary is not None
                else HorizonMetrics(
                    horizon=primary_horizon,
                    total_signals=0,
                    evaluated_count=0,
                    pending_count=0,
                    win_count=0,
                    loss_count=0,
                    false_positive_count=0,
                    meets_min_sample=False,
                    insufficient_sample=True,
                )
            )
            passes_mean_return = (metrics.mean_return or 0.0) >= min_mean_return_pct
            passed = metrics.meets_min_sample and passes_mean_return
            if not metrics.meets_min_sample:
                reason = (
                    f"{key} has only {metrics.evaluated_count} evaluated {primary_horizon} outcomes; "
                    f"needs {min_evaluated_count}."
                )
            elif not passes_mean_return:
                reason = (
                    f"{key} mean return {metrics.mean_return or 0.0:.4f}% is below "
                    f"{min_mean_return_pct:.4f}%."
                )
            else:
                reason = (
                    f"{key} meets the baseline with {metrics.evaluated_count} evaluated "
                    f"{primary_horizon} outcomes."
                )
            checks.append(
                OutcomeBaselineCheck(
                    key=key,
                    horizon=primary_horizon,
                    evaluated_count=metrics.evaluated_count,
                    mean_return=metrics.mean_return,
                    meets_min_sample=metrics.meets_min_sample,
                    passes_mean_return=passes_mean_return,
                    passed=passed,
                    reason=reason,
                )
            )
            details.append(reason)

        return OutcomeBaselineSummary(
            primary_horizon=primary_horizon,
            min_evaluated_per_horizon=min_evaluated_count,
            min_mean_return_pct=min_mean_return_pct,
            passes_baseline=all(check.passed for check in checks),
            details=details,
            checks=checks,
        )

    def _serialize_gate_checks(self, checks: list[GateCheck]) -> str | None:
        if not checks:
            return None
        return json.dumps([check.model_dump() for check in checks])

    def _serialize_list(self, values: list[str]) -> str | None:
        if not values:
            return None
        return json.dumps(values)

    def _serialize_dict(self, value: dict | None) -> str | None:
        if not value:
            return None
        return json.dumps(value)

    def _serialize_model(self, value) -> str | None:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            return json.dumps(value.model_dump())
        return json.dumps(value)

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

    def _deserialize_dict(self, raw_value: str | None) -> dict:
        if not raw_value:
            return {}
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}

    def _deserialize_comparison(self, raw_value: str | None) -> VariantComparison | None:
        payload = self._deserialize_dict(raw_value)
        if not payload:
            return None
        try:
            return VariantComparison(**payload)
        except Exception:
            return None

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

    def evaluate_signal_gate(
        self,
        *,
        asset_type: AssetType,
        signal: DecisionSignal,
        score_band: str,
        horizon: str,
        observed_at: datetime | None = None,
    ) -> EvidenceGateEvaluation:
        window = self._trust_window_bounds(observed_at=observed_at)
        summary = self.get_signal_outcome_summary(
            asset_type=asset_type,
            generated_at_start=window.start,
            generated_at_end=window.end,
        )
        signal_bucket = next((bucket for bucket in summary.by_signal if bucket.key == signal), None)
        score_band_bucket = next(
            (bucket for bucket in summary.by_signal_score_bucket if bucket.key == f"{signal}:{score_band}"),
            None,
        )
        signal_count, signal_win_rate, signal_avg_return = self._bucket_metrics(
            signal_bucket,
            horizon=horizon,
        )
        score_band_count, score_band_win_rate, score_band_avg_return = self._bucket_metrics(
            score_band_bucket,
            horizon=horizon,
        )
        min_count = self.settings.trade_gate_min_evaluated_count
        min_win_rate = self.settings.trade_gate_min_win_rate
        min_avg_return = self.settings.trade_gate_min_avg_return
        checks = [
            GateCheck(
                name="sample_size",
                passed=(signal_count or 0) >= min_count,
                detail=(
                    f"{asset_type} {signal} bucket has {signal_count or 0} "
                    f"{horizon} outcomes; need {min_count}"
                ),
            ),
            GateCheck(
                name="win_rate",
                passed=(signal_win_rate or 0) >= min_win_rate,
                detail=(
                    f"{asset_type} win rate {signal_win_rate or 0:.2f}% vs "
                    f"min {min_win_rate:.2f}%"
                ),
            ),
            GateCheck(
                name="avg_return",
                passed=(signal_avg_return or 0) >= min_avg_return,
                detail=(
                    f"{asset_type} avg return {signal_avg_return or 0:.4f}% vs "
                    f"min {min_avg_return:.4f}%"
                ),
            ),
        ]
        if (score_band_count or 0) >= min_count:
            checks.extend(
                [
                    GateCheck(
                        name="score_band_win_rate",
                        passed=(score_band_win_rate or 0) >= min_win_rate,
                        detail=(
                            f"score band {score_band} win rate {score_band_win_rate or 0:.2f}% vs "
                            f"min {min_win_rate:.2f}%"
                        ),
                    ),
                    GateCheck(
                        name="score_band_avg_return",
                        passed=(score_band_avg_return or 0) >= min_avg_return,
                        detail=(
                            f"score band {score_band} avg return {score_band_avg_return or 0:.4f}% vs "
                            f"min {min_avg_return:.4f}%"
                        ),
                    ),
                ]
            )
        passed = all(check.passed for check in checks)
        if passed:
            if (score_band_count or 0) >= min_count:
                reason = f"{asset_type.capitalize()} signal passed signal-level and score-band evidence gates."
            else:
                reason = (
                    f"{asset_type.capitalize()} signal passed signal-level evidence gates. "
                    f"Score-band bucket {score_band} is still maturing with {score_band_count or 0} evaluated outcomes."
                )
        else:
            first_failed = next(check for check in checks if not check.passed)
            reason = f"Blocked by {first_failed.name}: {first_failed.detail}."
        reason = f"{reason} {self._window_reason_suffix(window=window, horizon=horizon)}"
        return EvidenceGateEvaluation(
            passed=passed,
            reason=reason,
            horizon=horizon,
            evidence_basis=self._evidence_basis_label(window=window),
            trust_window_start=window.start,
            trust_window_end=window.end,
            signal_count=signal_count,
            signal_win_rate=signal_win_rate,
            signal_avg_return=signal_avg_return,
            score_band_count=score_band_count,
            score_band_win_rate=score_band_win_rate,
            score_band_avg_return=score_band_avg_return,
            checks=checks,
        )

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

        if (band_count or 0) >= self.settings.calibration_min_score_band_samples and band_win_rate is not None:
            return (
                blend(base_score=raw_score, win_rate=band_win_rate, avg_return=band_avg_return, weight=0.65),
                score_band,
                "score_band",
            )
        if (signal_count or 0) >= self.settings.calibration_min_signal_samples and signal_win_rate is not None:
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
        observed_at: datetime | None = None,
    ) -> tuple[float, str, str]:
        window = self._trust_window_bounds(observed_at=observed_at)
        summary = self.get_signal_outcome_summary(
            asset_type=asset_type,
            generated_at_start=window.start,
            generated_at_end=window.end,
        )
        calibrated_confidence, score_band, source = self._calibrate_confidence(
            signal=signal,
            raw_score=raw_score,
            summary=summary,
            horizon=horizon,
        )
        if source != "raw":
            return calibrated_confidence, score_band, source
        fallback_summary = self.get_signal_outcome_summary(
            generated_at_start=window.start,
            generated_at_end=window.end,
        )
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
        strategy_metadata = self._strategy_metadata_from_row(result)
        calibrated_confidence = round(getattr(result, "calibrated_confidence", result.score) or result.score, 2)
        calibration_source = getattr(result, "calibration_source", "raw") or "raw"
        if summary is not None and self._is_actionable_signal(decision_signal):
            calibrated_confidence, _, calibration_source = self._calibrate_confidence(
                signal=decision_signal,
                raw_score=result.score,
                summary=summary,
                horizon=horizon,
            )
        execution_eligibility = strategy_metadata.execution_eligibility
        if decision_signal == "HOLD":
            recommended_action = "ignore"
        elif execution_eligibility == "eligible":
            recommended_action = "dry_run"
        elif execution_eligibility == "review":
            recommended_action = "review"
        else:
            recommended_action = "blocked"
        layer_details = self._deserialize_dict(getattr(result, "layer_details_json", None))
        age = _signal_age_minutes(
            observed_at=datetime.now(timezone.utc),
            signal_created_at=result.created_at,
        )
        return DecisionRow(
            symbol=result.ticker,
            asset_type=getattr(result, "asset_type", self._asset_type_for_symbol(result.ticker)),
            signal=decision_signal,
            confidence=calibrated_confidence,
            raw_score=result.score,
            calibration_source=calibration_source,
            confidence_label=strategy_metadata.confidence_label,
            evidence_quality=strategy_metadata.evidence_quality,
            evidence_quality_score=strategy_metadata.evidence_quality_score,
            evidence_quality_reasons=strategy_metadata.evidence_quality_reasons,
            data_grade=getattr(result, "data_grade", strategy_metadata.data_grade),
            execution_eligibility=execution_eligibility,
            provider_status=getattr(result, "provider_status", "ok") or "ok",
            gate_passed=bool(getattr(result, "gate_passed", False)),
            bar_age_minutes=getattr(result, "bar_age_minutes", None),
            signal_age_minutes=age,
            freshness_flags=self._deserialize_dict(getattr(result, "freshness_flags_json", None)) or None,
            recommended_action=recommended_action,
            score_contributions=(
                ((layer_details.get("directional") or {}).get("score_contributions") or {})
                if isinstance(layer_details, dict)
                else {}
            ),
            strategy_version=strategy_metadata.strategy_version,
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
                    strategy_variant=getattr(run, "strategy_variant", "layered-v4") or "layered-v4",
                    shadow_enabled=bool(getattr(run, "shadow_enabled", False)),
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
                        strategy_variant=getattr(result, "strategy_variant", getattr(run, "strategy_variant", "layered-v4")) or "layered-v4",
                        score=getattr(result, "raw_score", result.score) or result.score,
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
                        data_grade=getattr(result, "data_grade", "research"),
                        bar_age_minutes=getattr(result, "bar_age_minutes", None),
                        freshness_flags_json=self._serialize_dict(
                            getattr(result, "freshness_flags", {})
                        ),
                        layer_details_json=self._serialize_dict(getattr(result, "layer_details", {})),
                        comparison_json=self._serialize_model(getattr(result, "comparison", None)),
                    )
                )
                if self._is_actionable_signal(result.decision_signal):
                    session.add(
                        SignalOutcomeORM(
                            run_id=run.run_id,
                            ticker=result.ticker,
                            asset_type=result.asset_type,
                            strategy_variant=getattr(result, "strategy_variant", getattr(run, "strategy_variant", "layered-v4")) or "layered-v4",
                            signal=result.decision_signal,
                            confidence=result.calibrated_confidence,
                            calibrated_confidence=result.calibrated_confidence,
                            calibration_source=result.calibration_source,
                            raw_score=getattr(result, "raw_score", result.score) or result.score,
                            score_band=self._score_band(getattr(result, "raw_score", result.score) or result.score),
                            scoring_version=result.scoring_version,
                            market_status=result.market_status,
                            buy_score=result.buy_score,
                            sell_score=result.sell_score,
                            signal_label=result.signal_label,
                            gate_passed=result.gate_passed,
                            gate_reason=result.gate_reason,
                            data_grade=getattr(result, "data_grade", "research"),
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
            strategy_variant=getattr(run, "strategy_variant", "layered-v4") or "layered-v4",
            shadow_enabled=bool(getattr(run, "shadow_enabled", False)),
            scan_count=run.scan_count,
            watchlist_size=run.watchlist_size,
            alerts_sent=run.alerts_sent,
            fear_greed_value=getattr(run, "fear_greed_value", None),
            fear_greed_label=getattr(run, "fear_greed_label", None),
            results=[
                ScanResult(
                    ticker=r.ticker,
                    asset_type=getattr(r, "asset_type", "stock") or "stock",
                    strategy_variant=getattr(r, "strategy_variant", getattr(run, "strategy_variant", "layered-v4")) or "layered-v4",
                    score=r.score,
                    raw_score=r.score,
                    calibrated_confidence=getattr(r, "calibrated_confidence", r.score) or r.score,
                    calibration_source=getattr(r, "calibration_source", "raw") or "raw",
                    confidence_label=self._strategy_metadata_from_row(r).confidence_label,
                    strategy_id=self._strategy_metadata_from_row(r).strategy_id,
                    strategy_version=self._strategy_metadata_from_row(r).strategy_version,
                    strategy_primary_horizon=self._strategy_metadata_from_row(r).primary_holding_horizon,
                    strategy_entry_assumption=self._strategy_metadata_from_row(r).entry_assumption,
                    strategy_exit_assumption=self._strategy_metadata_from_row(r).exit_assumption,
                    evidence_quality=self._strategy_metadata_from_row(r).evidence_quality,
                    evidence_quality_score=self._strategy_metadata_from_row(r).evidence_quality_score,
                    evidence_quality_reasons=list(self._strategy_metadata_from_row(r).evidence_quality_reasons),
                    data_grade=getattr(r, "data_grade", self._strategy_metadata_from_row(r).data_grade),
                    execution_eligibility=self._strategy_metadata_from_row(r).execution_eligibility,
                    buy_score=getattr(r, "buy_score", 0.0) or 0.0,
                    sell_score=getattr(r, "sell_score", 0.0) or 0.0,
                    decision_signal=self._resolve_decision_signal(r),
                    scoring_version=getattr(r, "scoring_version", "v4.0-layered") or "v4.0-layered",
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
                    bar_age_minutes=getattr(r, "bar_age_minutes", None),
                    freshness_flags=self._deserialize_dict(
                        getattr(r, "freshness_flags_json", None)
                    ),
                    layer_details=self._deserialize_dict(getattr(r, "layer_details_json", None)),
                    comparison=self._deserialize_comparison(getattr(r, "comparison_json", None)),
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
            trust_window_start, trust_window_end = self.trust_window_bounds_for(observed_at=latest.created_at)
            summaries = {
                "stock": self.get_signal_outcome_summary(
                    asset_type="stock",
                    generated_at_start=trust_window_start,
                    generated_at_end=trust_window_end,
                ),
                "crypto": self.get_signal_outcome_summary(
                    asset_type="crypto",
                    generated_at_start=trust_window_start,
                    generated_at_end=trust_window_end,
                ),
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

            trust_window_start, trust_window_end = self.trust_window_bounds_for(observed_at=row.created_at)
            return self._build_decision_row(
                row,
                summary=self.get_signal_outcome_summary(
                    asset_type=getattr(row, "asset_type", self._asset_type_for_symbol(row.ticker)),
                    generated_at_start=trust_window_start,
                    generated_at_end=trust_window_end,
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
            gate_checks = self._deserialize_gate_checks(getattr(row, "gate_checks_json", None))
            outcome_row = None
            if self._is_actionable_signal(signal):
                outcome_row = session.execute(
                    select(SignalOutcomeORM)
                    .where(
                        SignalOutcomeORM.run_id == row.run_id,
                        SignalOutcomeORM.ticker == row.ticker,
                        SignalOutcomeORM.signal == signal,
                    )
                    .order_by(desc(SignalOutcomeORM.generated_at), desc(SignalOutcomeORM.id))
                    .limit(1)
                ).scalar_one_or_none()
                calibrated_confidence, score_band, calibration_source = self.calibrate_signal(
                    asset_type=getattr(row, "asset_type", self._asset_type_for_symbol(symbol)),
                    signal=signal,
                    raw_score=row.score,
                    horizon=self.settings.trade_gate_horizon,
                    observed_at=row.created_at,
                )
            signal_window = self._trust_window_bounds(observed_at=row.created_at)
            stored_gate_passed = bool(
                getattr(outcome_row, "gate_passed", getattr(row, "gate_passed", False))
            )
            stored_gate_reason = (
                getattr(outcome_row, "gate_reason", None)
                or getattr(row, "gate_reason", "Signal gate not evaluated.")
                or "Signal gate not evaluated."
            )
            return LatestSignalContext(
                signal_outcome_id=outcome_row.id if outcome_row is not None else None,
                run_id=row.run_id,
                symbol=row.ticker,
                asset_type=getattr(row, "asset_type", self._asset_type_for_symbol(symbol)),
                strategy_variant=getattr(row, "strategy_variant", "layered-v4") or "layered-v4",
                signal=signal,
                raw_score=row.score,
                calibrated_confidence=calibrated_confidence,
                calibration_source=calibration_source,
                score_band=score_band,
                signal_generated_at=row.created_at,
                last_updated=row.created_at,
                gate_passed=stored_gate_passed,
                gate_reason=stored_gate_reason,
                gate_checks=gate_checks,
                gate_evaluation_mode="scan_time_window_locked",
                evidence_basis=self._evidence_basis_label(window=signal_window),
                trust_window_start=signal_window.start,
                trust_window_end=signal_window.end,
                data_quality=getattr(row, "data_quality", "ok") or "ok",
                provider_status=getattr(row, "provider_status", "ok") or "ok",
                provider_warnings=self._deserialize_list(getattr(row, "provider_warnings_json", None)),
                layer_details=self._deserialize_dict(getattr(row, "layer_details_json", None)),
            )

    def get_latest_run_timestamp(self) -> datetime | None:
        with SessionLocal() as session:
            latest = session.execute(
                select(ScanRunORM.created_at).order_by(desc(ScanRunORM.created_at)).limit(1)
            ).scalar_one_or_none()
            return latest

    def get_due_outcome_counts(self, *, observed_at: datetime | None = None) -> dict[str, int]:
        pending = self.list_due_signal_outcome_evaluations(
            observed_at=observed_at or datetime.now(timezone.utc),
            limit=5000,
        )
        counts = {"15m": 0, "1h": 0, "1d": 0}
        for item in pending:
            counts[item.horizon] = counts.get(item.horizon, 0) + 1
        return counts

    def get_integrity_report(self, *, observed_at: datetime | None = None) -> dict[str, object]:
        mismatches_by_horizon = {"15m": 0, "1h": 0, "1d": 0}
        with SessionLocal() as session:
            rows = session.execute(select(SignalOutcomeORM)).scalars().all()
        actionable_rows = [row for row in rows if self._is_actionable_signal(row.signal)]
        for row in actionable_rows:
            for horizon in self._OUTCOME_HORIZONS:
                if self._stored_return_for_horizon(row, horizon) != self._return_for_horizon(row, horizon):
                    mismatches_by_horizon[horizon] += 1
        due_counts = self.get_due_outcome_counts(observed_at=observed_at)
        return {
            "total_actionable_outcomes": len(actionable_rows),
            "return_mismatch_count": sum(mismatches_by_horizon.values()),
            "return_mismatches_by_horizon": mismatches_by_horizon,
            "pending_due_by_horizon": due_counts,
        }

    def get_trust_readiness_snapshot(
        self,
        *,
        observed_at: datetime | None = None,
        asset_type: AssetType | None = None,
    ) -> TrustReadinessSnapshot:
        window = self._trust_window_bounds(observed_at=observed_at)
        summary = self.get_signal_validation_summary(
            asset_type=asset_type,
            start=window.start,
            end=window.end,
        )
        threshold = self.get_validation_threshold_sweep(
            asset_type=asset_type,
            start=window.start,
            end=window.end,
        )
        due_counts = self.get_due_outcome_counts(observed_at=observed_at)
        return TrustReadinessSnapshot(
            window=window,
            summary=summary,
            threshold=threshold,
            pending_due_15m_count=due_counts.get("15m", 0),
            pending_due_1h_count=due_counts.get("1h", 0),
            pending_due_1d_count=due_counts.get("1d", 0),
        )

    def backfill_execution_audit_signal_links(self) -> int:
        updated_count = 0
        with SessionLocal() as session:
            audit_rows = session.execute(
                select(ExecutionAuditORM)
                .order_by(desc(ExecutionAuditORM.created_at), desc(ExecutionAuditORM.id))
            ).scalars().all()
            for audit in audit_rows:
                outcome_row = None
                if getattr(audit, "signal_outcome_id", None):
                    outcome_row = session.get(SignalOutcomeORM, audit.signal_outcome_id)
                if outcome_row is None and audit.signal_run_id:
                    outcome_row = session.execute(
                        select(SignalOutcomeORM)
                        .where(
                            SignalOutcomeORM.run_id == audit.signal_run_id,
                            SignalOutcomeORM.ticker == audit.ticker,
                        )
                        .order_by(desc(SignalOutcomeORM.generated_at), desc(SignalOutcomeORM.id))
                        .limit(1)
                    ).scalar_one_or_none()
                if outcome_row is None:
                    outcome_row = session.execute(
                        select(SignalOutcomeORM)
                        .where(
                            SignalOutcomeORM.ticker == audit.ticker,
                            SignalOutcomeORM.generated_at <= audit.created_at,
                        )
                        .order_by(desc(SignalOutcomeORM.generated_at), desc(SignalOutcomeORM.id))
                        .limit(1)
                    ).scalar_one_or_none()
                if outcome_row is None:
                    continue

                changed = False
                if getattr(audit, "signal_outcome_id", None) != outcome_row.id:
                    audit.signal_outcome_id = outcome_row.id
                    changed = True
                if audit.signal_run_id != outcome_row.run_id:
                    audit.signal_run_id = outcome_row.run_id
                    changed = True
                if audit.signal_generated_at != outcome_row.generated_at:
                    audit.signal_generated_at = outcome_row.generated_at
                    changed = True
                if not audit.latest_signal:
                    audit.latest_signal = outcome_row.signal
                    changed = True
                if getattr(audit, "trade_gate_horizon", None) in {None, ""}:
                    audit.trade_gate_horizon = self.settings.trade_gate_horizon
                    changed = True
                if getattr(audit, "evidence_basis", None) in {None, ""}:
                    audit.evidence_basis = self._evidence_basis_label(
                        window=self._trust_window_bounds(observed_at=audit.created_at)
                    )
                    changed = True
                if getattr(audit, "trust_window_start", None) is None or getattr(audit, "trust_window_end", None) is None:
                    window = self._trust_window_bounds(observed_at=audit.created_at)
                    audit.trust_window_start = window.start
                    audit.trust_window_end = window.end
                    changed = True
                if changed:
                    audit.updated_at = datetime.now(timezone.utc)
                    updated_count += 1
            if updated_count:
                session.commit()
        return updated_count

    def list_execution_audits(
        self,
        *,
        limit: int = 50,
        lifecycle_status: str | None = None,
    ) -> list[ExecutionAuditSummary]:
        def preview_trade_gate_metadata(row: ExecutionAuditORM) -> dict:
            if not getattr(row, "preview_payload", None):
                return {}
            try:
                preview_payload = json.loads(row.preview_payload)
            except json.JSONDecodeError:
                return {}
            trade_gate = preview_payload.get("trade_gate") or {}
            return trade_gate if isinstance(trade_gate, dict) else {}

        with SessionLocal() as session:
            query = select(ExecutionAuditORM).order_by(desc(ExecutionAuditORM.created_at)).limit(limit)
            if lifecycle_status is not None:
                query = (
                    select(ExecutionAuditORM)
                    .where(ExecutionAuditORM.lifecycle_status == lifecycle_status)
                    .order_by(desc(ExecutionAuditORM.created_at))
                    .limit(limit)
                )
            rows = session.execute(query).scalars().all()
            return [
                ExecutionAuditSummary(
                    id=row.id,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    ticker=row.ticker,
                    asset_type=getattr(row, "asset_type", "stock") or "stock",
                    side=row.side,
                    order_type=row.order_type,
                    qty=row.qty,
                    dry_run=bool(getattr(row, "dry_run", False)),
                    lifecycle_status=row.lifecycle_status,
                    latest_price=row.latest_price,
                    notional_estimate=row.notional_estimate,
                    signal_outcome_id=getattr(row, "signal_outcome_id", None),
                    signal_run_id=row.signal_run_id,
                    signal_generated_at=row.signal_generated_at,
                    latest_signal=row.latest_signal,
                    confidence=row.confidence,
                    raw_score=preview_trade_gate_metadata(row).get("raw_score"),
                    evidence_quality=preview_trade_gate_metadata(row).get("evidence_quality"),
                    execution_eligibility=preview_trade_gate_metadata(row).get("execution_eligibility"),
                    trade_gate_horizon=getattr(row, "trade_gate_horizon", None),
                    gate_evaluation_mode=preview_trade_gate_metadata(row).get("gate_evaluation_mode"),
                    evidence_basis=getattr(row, "evidence_basis", None),
                    trust_window_start=getattr(row, "trust_window_start", None),
                    trust_window_end=getattr(row, "trust_window_end", None),
                    latest_scan_age_minutes=preview_trade_gate_metadata(row).get("latest_scan_age_minutes"),
                    latest_scan_fresh=preview_trade_gate_metadata(row).get("latest_scan_fresh"),
                    stored_gate_passed=preview_trade_gate_metadata(row).get("stored_gate_passed"),
                    stored_gate_reason=preview_trade_gate_metadata(row).get("stored_gate_reason"),
                    gate_consistent_with_signal=preview_trade_gate_metadata(row).get("gate_consistent_with_signal"),
                    trade_gate_allowed=row.trade_gate_allowed,
                    trade_gate_reason=row.trade_gate_reason,
                    submitted=bool(getattr(row, "submitted", False)),
                    broker_order_id=row.broker_order_id,
                    broker_status=row.broker_status,
                    error_message=row.error_message,
                )
                for row in rows
            ]

    def list_paper_positions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        symbol: str | None = None,
    ) -> list[PaperPositionSummary]:
        with SessionLocal() as session:
            query = select(PaperPositionORM).order_by(desc(PaperPositionORM.opened_at), desc(PaperPositionORM.id))
            if status is not None:
                query = query.where(PaperPositionORM.status == status)
            if symbol is not None:
                query = query.where(PaperPositionORM.ticker == symbol.upper())
            rows = session.execute(query.offset(offset).limit(limit)).scalars().all()
            return [
                PaperPositionSummary(
                    id=row.id,
                    intent_key=row.intent_key,
                    execution_audit_id=row.execution_audit_id,
                    ticker=row.ticker,
                    asset_type=row.asset_type or "stock",
                    side=row.side,
                    quantity=row.quantity,
                    simulated_fill_price=row.simulated_fill_price,
                    notional_usd=row.notional_usd,
                    cost_basis_usd=row.cost_basis_usd,
                    close_price=row.close_price,
                    realized_pnl=row.realized_pnl,
                    status=row.status or "open",
                    opened_at=row.opened_at,
                    closed_at=row.closed_at,
                    strategy_version=row.strategy_version,
                    confidence=row.confidence,
                )
                for row in rows
            ]

    def record_paper_position_from_audit(
        self,
        *,
        audit_id: int,
        simulated_fill_price: float,
        filled_at: datetime | None = None,
    ) -> int | None:
        from app.services.automation_repository import AutomationRepository

        return AutomationRepository().record_paper_position_from_audit(
            audit_id=audit_id,
            simulated_fill_price=simulated_fill_price,
            filled_at=filled_at,
        )

    def get_paper_ledger_summary(self) -> PaperLedgerSummaryResponse:
        with SessionLocal() as session:
            rows = session.execute(select(PaperPositionORM)).scalars().all()
        open_rows = [row for row in rows if (row.status or "open") == "open"]
        closed_rows = [row for row in rows if (row.status or "open") == "closed"]
        winning_closed = [row for row in closed_rows if float(row.realized_pnl or 0.0) > 0]
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for row in sorted(closed_rows, key=lambda item: (item.closed_at or item.opened_at, item.id)):
            cumulative += float(row.realized_pnl or 0.0)
            peak = max(peak, cumulative)
            max_drawdown = max(max_drawdown, peak - cumulative)
        return PaperLedgerSummaryResponse(
            open_positions=len(open_rows),
            closed_positions=len(closed_rows),
            total_notional_usd=round(sum(float(row.notional_usd or 0.0) for row in open_rows), 2),
            total_realized_pnl=round(sum(float(row.realized_pnl or 0.0) for row in closed_rows), 2),
            total_closed_notional_usd=round(sum(float(row.notional_usd or 0.0) for row in closed_rows), 2),
            long_positions=sum(1 for row in open_rows if row.side == "buy"),
            short_positions=sum(1 for row in open_rows if row.side == "sell"),
            last_opened_at=max((row.opened_at for row in open_rows), default=None),
            last_closed_at=max((row.closed_at for row in closed_rows if row.closed_at is not None), default=None),
            total_count=len(rows),
            win_rate_pct=round((len(winning_closed) / len(closed_rows)) * 100, 2) if closed_rows else None,
            gross_pnl_usd=round(sum(float(row.realized_pnl or 0.0) for row in closed_rows), 2),
            max_drawdown_usd=round(max_drawdown, 2),
        )

    def reconcile_paper_loop(self) -> ReconciliationReportResponse:
        issues: list[ReconciliationIssue] = []
        generated_at = datetime.now(timezone.utc)
        with SessionLocal() as session:
            intents = {
                row.intent_key: row
                for row in session.execute(select(AutomationIntentORM)).scalars().all()
            }
            audits = {
                row.id: row
                for row in session.execute(select(ExecutionAuditORM)).scalars().all()
            }
            positions = session.execute(select(PaperPositionORM)).scalars().all()
        for position in positions:
            intent = intents.get(position.intent_key)
            audit = audits.get(position.execution_audit_id) if position.execution_audit_id is not None else None
            is_manual_audit_position = audit is not None and bool(getattr(audit, "dry_run", False))
            if intent is None and not is_manual_audit_position:
                issues.append(
                    ReconciliationIssue(
                        kind="paper_position_missing_intent",
                        detail=f"Paper position {position.id} has no matching automation intent.",
                        paper_position_id=position.id,
                    )
                )
            if position.execution_audit_id is not None and position.execution_audit_id not in audits:
                issues.append(
                    ReconciliationIssue(
                        kind="paper_position_missing_audit",
                        detail=f"Paper position {position.id} references missing audit {position.execution_audit_id}.",
                        paper_position_id=position.id,
                        execution_audit_id=position.execution_audit_id,
                    )
                )
        for intent in intents.values():
            if intent.status != "dry_run_complete":
                continue
            linked = [row for row in positions if row.intent_key == intent.intent_key]
            if not linked:
                issues.append(
                    ReconciliationIssue(
                        kind="dry_run_without_ledger",
                        detail=f"Intent {intent.id} is dry_run_complete without a paper ledger row.",
                        intent_id=intent.id,
                        execution_audit_id=intent.execution_audit_id,
                    )
                )
        return ReconciliationReportResponse(
            generated_at=generated_at,
            ok=not issues,
            total_issues=len(issues),
            issues=issues,
        )

    def get_portfolio_guardrail_snapshot(
        self,
        *,
        observed_at: datetime | None = None,
        horizon: str | None = None,
    ) -> dict:
        comparable_now = self._normalize_report_datetime(observed_at or datetime.now(timezone.utc))
        if comparable_now is None:
            comparable_now = datetime.now(timezone.utc).replace(tzinfo=None)
        start_of_day = comparable_now.replace(hour=0, minute=0, second=0, microsecond=0)
        evaluation_horizon = horizon or self.settings.trade_gate_horizon

        with SessionLocal() as session:
            audits = session.execute(
                select(ExecutionAuditORM)
                .where(ExecutionAuditORM.created_at >= start_of_day)
                .order_by(desc(ExecutionAuditORM.created_at), desc(ExecutionAuditORM.id))
            ).scalars().all()

            eligible_statuses = {"dry_run", "submitted"}
            deployed_audits = [row for row in audits if row.lifecycle_status in eligible_statuses]
            daily_notional = round(
                sum(float(getattr(row, "notional_estimate", 0.0) or 0.0) for row in deployed_audits),
                2,
            )

            symbol_notional: dict[str, float] = {}
            asset_type_notional: dict[str, float] = {}
            for row in deployed_audits:
                notional = float(getattr(row, "notional_estimate", 0.0) or 0.0)
                symbol_notional[row.ticker] = round(symbol_notional.get(row.ticker, 0.0) + notional, 2)
                asset_type = getattr(row, "asset_type", self._asset_type_for_symbol(row.ticker)) or "stock"
                asset_type_notional[asset_type] = round(asset_type_notional.get(asset_type, 0.0) + notional, 2)

            resolved_returns: list[tuple[datetime, float]] = []
            weighted_notionals: list[tuple[float, float]] = []
            for row in deployed_audits:
                if not getattr(row, "signal_outcome_id", None):
                    continue
                outcome = session.get(SignalOutcomeORM, row.signal_outcome_id)
                if outcome is None:
                    continue
                return_pct = self._stored_return_for_horizon(outcome, evaluation_horizon)
                if return_pct is None:
                    return_pct = self._return_for_horizon(outcome, evaluation_horizon)
                if return_pct is None:
                    continue
                resolved_returns.append((row.created_at, return_pct))
                weighted_notionals.append((float(getattr(row, "notional_estimate", 0.0) or 0.0), return_pct))

            weighted_daily_return = None
            if weighted_notionals:
                total_notional = sum(notional for notional, _ in weighted_notionals) or 0.0
                if total_notional > 0:
                    weighted_daily_return = round(
                        sum(notional * return_pct for notional, return_pct in weighted_notionals) / total_notional,
                        4,
                    )

            sorted_returns = [value for _, value in sorted(resolved_returns, key=lambda item: item[0], reverse=True)]
            loss_streak = 0
            win_threshold = self.settings.validation_win_threshold_pct
            for value in sorted_returns:
                if value > win_threshold:
                    break
                loss_streak += 1

            cumulative = 0.0
            peak = 0.0
            max_drawdown = 0.0
            for _, value in sorted(resolved_returns, key=lambda item: item[0]):
                cumulative += value
                peak = max(peak, cumulative)
                max_drawdown = max(max_drawdown, peak - cumulative)

            return {
                "daily_notional": daily_notional,
                "symbol_notional": symbol_notional,
                "asset_type_notional": asset_type_notional,
                "resolved_trade_count": len(resolved_returns),
                "weighted_daily_return_pct": weighted_daily_return,
                "loss_streak": loss_streak,
                "max_drawdown_pct": round(max_drawdown, 4),
                "horizon": evaluation_horizon,
            }

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

    def get_signal_outcome_summary(
        self,
        asset_type: AssetType | None = None,
        generated_at_start: datetime | None = None,
        generated_at_end: datetime | None = None,
        gate_passed: bool | None = None,
    ) -> SignalOutcomeSummary:
        rows = self._load_signal_outcome_rows(
            asset_type=asset_type,
            generated_at_start=generated_at_start,
            generated_at_end=generated_at_end,
            gate_passed=gate_passed,
        )

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
        generated_at_start: datetime | None = None,
        generated_at_end: datetime | None = None,
        gate_passed: bool | None = None,
    ) -> list[SignalOutcomeORM]:
        normalized_start = self._normalize_report_datetime(generated_at_start)
        normalized_end = self._normalize_report_datetime(generated_at_end)
        with SessionLocal() as session:
            query = select(SignalOutcomeORM).order_by(desc(SignalOutcomeORM.generated_at))
            if normalized_start is not None:
                query = query.where(SignalOutcomeORM.generated_at >= normalized_start)
            if normalized_end is not None:
                query = query.where(SignalOutcomeORM.generated_at < normalized_end)
            rows = session.execute(query).scalars().all()
        return self._filter_loaded_signal_outcome_rows(
            rows,
            asset_type=asset_type,
            generated_at_start=normalized_start,
            generated_at_end=normalized_end,
            gate_passed=gate_passed,
        )

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
        friction_scenario: str = "base",
    ) -> list[ValidationBucket]:
        grouped: dict[str, list[SignalOutcomeORM]] = {}
        for row in rows:
            key = key_fn(row)
            grouped.setdefault(key, []).append(row)
        buckets = [
            self._build_validation_bucket(
                key=key,
                rows=group_rows,
                friction_scenario=friction_scenario,
            )
            for key, group_rows in grouped.items()
        ]
        return self._sort_validation_buckets(buckets)

    def get_signal_outcome_performance_report(
        self,
        *,
        start: datetime,
        end: datetime,
        asset_type: AssetType | None = None,
        regime: str | None = None,
        friction_scenario: str = "base",
        strict_walkforward: bool = False,
    ) -> SignalOutcomePerformanceReportResponse:
        normalized_start = self._normalize_report_datetime(start)
        normalized_end = self._normalize_report_datetime(end)
        rows = self._load_signal_outcome_rows(
            asset_type=asset_type,
            generated_at_start=normalized_start,
            generated_at_end=normalized_end,
        )
        if regime is not None:
            rows = [row for row in rows if (getattr(row, "market_status", None) or "unknown") == regime]
        if strict_walkforward and normalized_end is not None:
            holdout_start = normalized_end - timedelta(days=self.settings.wf_holdout_days)
            rows = [
                row for row in rows
                if self._normalize_report_datetime(getattr(row, "generated_at", None)) is not None
                and self._normalize_report_datetime(getattr(row, "generated_at", None)) >= holdout_start
            ]
        min_evaluated_count = self.settings.outcome_report_min_evaluated_per_horizon
        overall = self._build_multi_horizon_slice(
            key="overall",
            rows=rows,
            min_evaluated_count=min_evaluated_count,
            friction_scenario=friction_scenario,
        )
        by_signal = self._group_outcome_performance_slices(
            rows,
            key_fn=lambda row: row.signal,
            min_evaluated_count=min_evaluated_count,
            friction_scenario=friction_scenario,
        )
        by_signal_and_gate = self._group_outcome_performance_slices(
            rows,
            key_fn=lambda row: (
                f"{row.signal}:{'passed' if getattr(row, 'gate_passed', False) else 'blocked'}"
            ),
            min_evaluated_count=min_evaluated_count,
            friction_scenario=friction_scenario,
        )
        by_asset_type = self._group_outcome_performance_slices(
            rows,
            key_fn=lambda row: getattr(row, "asset_type", self._asset_type_for_symbol(row.ticker)) or "stock",
            min_evaluated_count=min_evaluated_count,
            friction_scenario=friction_scenario,
        )
        slices_by_key = {slice_summary.key: slice_summary for slice_summary in by_signal_and_gate}
        return SignalOutcomePerformanceReportResponse(
            start=normalized_start or start,
            end=normalized_end or end,
            asset_type=asset_type,
            regime=regime,
            friction_scenario=friction_scenario,
            strict_walkforward=strict_walkforward,
            total_signals=len(rows),
            min_evaluated_per_horizon=min_evaluated_count,
            overall=overall,
            by_signal=by_signal,
            by_signal_and_gate=by_signal_and_gate,
            by_asset_type=by_asset_type,
            baseline=self._build_outcome_baseline_summary(slices_by_key=slices_by_key),
        )

    def _split_rows_for_out_of_sample(
        self,
        rows: list[SignalOutcomeORM],
    ) -> tuple[list[SignalOutcomeORM], list[SignalOutcomeORM]]:
        ordered = sorted(rows, key=lambda row: row.generated_at)
        if len(ordered) < 4:
            return ordered, []
        split_index = max(len(ordered) // 2, 1)
        return ordered[:split_index], ordered[split_index:]

    def _build_regime_advisories(
        self,
        *,
        market_status_buckets: list[ValidationBucket],
        volatility_buckets: list[ValidationBucket],
    ) -> list[str]:
        advisories: list[str] = []
        for bucket in market_status_buckets:
            if bucket.evaluated_count == 0:
                continue
            if bucket.key in {"bearish", "neutral"} and (bucket.expectancy_after_friction or bucket.expectancy or 0.0) < 0:
                advisories.append(
                    f"{bucket.key} market-status signals are negative after costs in the current validation window."
                )
        for bucket in volatility_buckets:
            if bucket.evaluated_count == 0:
                continue
            if bucket.key in {"hot", "extreme"} and (bucket.false_positive_rate or 0.0) > 50.0:
                advisories.append(
                    f"{bucket.key} volatility regimes are producing elevated false positives."
                )
        return advisories

    def get_signal_validation_summary(
        self,
        asset_type: AssetType | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        regime: str | None = None,
        data_grade: str | None = None,
        friction_scenario: str = "base",
    ) -> ValidationSummary:
        normalized_start = self._normalize_report_datetime(start)
        normalized_end = self._normalize_report_datetime(end)
        rows = self._load_signal_outcome_rows(
            asset_type=asset_type,
            generated_at_start=normalized_start,
            generated_at_end=normalized_end,
        )
        if regime is not None:
            rows = [row for row in rows if (getattr(row, "market_status", None) or "unknown") == regime]
        if data_grade is not None:
            rows = [row for row in rows if (getattr(row, "data_grade", None) or "research") == data_grade]
        overall = self._build_validation_bucket(
            key="overall",
            rows=rows,
            friction_scenario=friction_scenario,
        )
        in_sample_rows, out_of_sample_rows = self._split_rows_for_out_of_sample(rows)
        in_sample = (
            self._build_validation_bucket(
                key="in_sample",
                rows=in_sample_rows,
                friction_scenario=friction_scenario,
            )
            if in_sample_rows
            else None
        )
        out_of_sample = (
            self._build_validation_bucket(
                key="out_of_sample",
                rows=out_of_sample_rows,
                friction_scenario=friction_scenario,
            )
            if out_of_sample_rows
            else None
        )
        by_market_status = self._group_validation_buckets(
            rows,
            key_fn=lambda row: getattr(row, "market_status", None) or "unknown",
            friction_scenario=friction_scenario,
        )
        by_volatility_regime = self._group_validation_buckets(
            rows,
            key_fn=lambda row: getattr(row, "volatility_regime", None) or "unknown",
            friction_scenario=friction_scenario,
        )
        degradation_warnings: list[str] = []
        if in_sample and out_of_sample and in_sample.evaluated_count and out_of_sample.evaluated_count:
            in_sample_expectancy = in_sample.expectancy_after_friction or in_sample.expectancy or 0.0
            out_of_sample_expectancy = out_of_sample.expectancy_after_friction or out_of_sample.expectancy or 0.0
            if out_of_sample_expectancy < in_sample_expectancy:
                degradation_warnings.append(
                    "Out-of-sample expectancy is weaker than the earlier half of the selected window."
                )
            if (out_of_sample.false_positive_rate or 0.0) > (in_sample.false_positive_rate or 0.0):
                degradation_warnings.append(
                    "Out-of-sample false-positive rate is worse than the earlier half of the selected window."
                )
        return ValidationSummary(
            start=normalized_start or start,
            end=normalized_end or end,
            primary_horizon=self._validation_horizon(),
            win_threshold_pct=self.settings.validation_win_threshold_pct,
            false_positive_threshold_pct=self.settings.validation_false_positive_threshold_pct,
            total_signals=len(rows),
            evaluated_count=overall.evaluated_count,
            pending_count=overall.pending_count,
            overall=overall,
            in_sample=in_sample,
            out_of_sample=out_of_sample,
            degradation_warnings=degradation_warnings,
            regime_advisories=self._build_regime_advisories(
                market_status_buckets=by_market_status,
                volatility_buckets=by_volatility_regime,
            ),
            by_signal=self._group_validation_buckets(
                rows,
                key_fn=lambda row: row.signal,
                friction_scenario=friction_scenario,
            ),
            by_confidence_bucket=self._group_validation_buckets(
                rows,
                key_fn=lambda row: self._confidence_bucket(float(getattr(row, "calibrated_confidence", getattr(row, "confidence", 0.0)) or 0.0)),
                friction_scenario=friction_scenario,
            ),
            by_score_band=self._group_validation_buckets(
                rows,
                key_fn=lambda row: getattr(row, "score_band", self._score_band(self._raw_score_for(row))),
                friction_scenario=friction_scenario,
            ),
            by_age_bucket=self._group_validation_buckets(
                rows,
                key_fn=lambda row: self._age_bucket_for_row(row),
                friction_scenario=friction_scenario,
            ),
            by_signal_label=self._group_validation_buckets(
                rows,
                key_fn=lambda row: getattr(row, "signal_label", None) or "unknown",
                friction_scenario=friction_scenario,
            ),
            by_market_status=by_market_status,
            by_news_source=self._group_validation_buckets(
                rows,
                key_fn=lambda row: getattr(row, "news_source", None) or "unknown",
                friction_scenario=friction_scenario,
            ),
            by_volatility_regime=by_volatility_regime,
            by_data_quality=self._group_validation_buckets(
                rows,
                key_fn=lambda row: getattr(row, "data_quality", None) or "unknown",
                friction_scenario=friction_scenario,
            ),
            by_data_grade=self._group_validation_buckets(
                rows,
                key_fn=lambda row: getattr(row, "data_grade", None) or "research",
                friction_scenario=friction_scenario,
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
                friction_scenario=friction_scenario,
            ),
            by_signal_and_gate=self._group_validation_buckets(
                rows,
                key_fn=lambda row: (
                    f"{row.signal}:{'passed' if getattr(row, 'gate_passed', False) else 'blocked'}"
                ),
                friction_scenario=friction_scenario,
            ),
            by_gate_status=self._group_validation_buckets(
                rows,
                key_fn=lambda row: "passed" if getattr(row, "gate_passed", False) else "blocked",
                friction_scenario=friction_scenario,
            ),
            by_asset_type=self._group_validation_buckets(
                rows,
                key_fn=lambda row: getattr(row, "asset_type", self._asset_type_for_symbol(row.ticker)) or "stock",
                friction_scenario=friction_scenario,
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

    def _recommend_threshold_candidate(
        self,
        *,
        gate_buckets: list[ValidationBucket],
        candidates: list[ThresholdSweepRow],
    ) -> ThresholdRecommendation:
        warnings: list[str] = []
        gate_bucket_map = {bucket.key: bucket for bucket in gate_buckets}
        mature_gated_keys: list[str] = []
        for key in ("BUY:passed", "SELL:passed", "BUY:blocked", "SELL:blocked"):
            bucket = gate_bucket_map.get(key)
            if bucket is None or bucket.evaluated_count == 0:
                warnings.append(f"{key} has no evaluated outcomes in the selected window.")
            elif bucket.evaluated_count < self.settings.trade_gate_min_evaluated_count:
                warnings.append(
                    f"{key} has only {bucket.evaluated_count} evaluated outcomes; "
                    f"needs {self.settings.trade_gate_min_evaluated_count} for mature evidence."
                )
            if bucket is not None and bucket.evaluated_count >= self.settings.trade_gate_min_evaluated_count:
                mature_gated_keys.append(key)

        if (
            candidates
            and "BUY:passed" in mature_gated_keys
            and "SELL:passed" in mature_gated_keys
        ):
            candidate = candidates[0]
            return ThresholdRecommendation(
                min_evaluated_count=candidate.min_evaluated_count,
                min_win_rate=candidate.min_win_rate,
                min_avg_return=candidate.min_avg_return,
                score_band_required=candidate.score_band_required,
                source="candidate",
                evidence_status="ready",
                rationale=(
                    "Selected the strongest recent-window candidate after sorting by expectancy, "
                    "false-positive rate, and kept signals, with mature gated BUY and SELL cohorts available."
                ),
                warnings=warnings,
            )

        return ThresholdRecommendation(
            min_evaluated_count=self.settings.trade_gate_min_evaluated_count,
            min_win_rate=self.settings.trade_gate_min_win_rate,
            min_avg_return=self.settings.trade_gate_min_avg_return,
            score_band_required=False,
            source="configured_fallback",
            evidence_status="provisional",
            rationale=(
                "Recent evidence is still too sparse to lock thresholds from gated BUY and SELL cohorts. "
                "Keep the configured trade-gate thresholds as provisional defaults while more paper-trading "
                "and outcome data accumulates."
            ),
            warnings=warnings,
        )

    def get_validation_threshold_sweep(
        self,
        asset_type: AssetType | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> ThresholdSweepResponse:
        normalized_start = self._normalize_report_datetime(start)
        normalized_end = self._normalize_report_datetime(end)
        rows = self._load_signal_outcome_rows(
            asset_type=asset_type,
            generated_at_start=normalized_start,
            generated_at_end=normalized_end,
        )
        baseline = self._build_validation_bucket(key="baseline", rows=rows)
        by_signal_and_gate = self._group_validation_buckets(
            rows,
            key_fn=lambda row: f"{row.signal}:{'passed' if getattr(row, 'gate_passed', False) else 'blocked'}",
        )
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
                                avg_return_after_friction=kept_metrics.avg_return_after_friction,
                                expectancy_after_friction=kept_metrics.expectancy_after_friction,
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
            start=normalized_start or start,
            end=normalized_end or end,
            primary_horizon=self._validation_horizon(),
            win_threshold_pct=self.settings.validation_win_threshold_pct,
            false_positive_threshold_pct=self.settings.validation_false_positive_threshold_pct,
            baseline=baseline,
            by_signal_and_gate=by_signal_and_gate,
            recommendation=self._recommend_threshold_candidate(
                gate_buckets=by_signal_and_gate,
                candidates=candidates,
            ),
            candidates=candidates,
        )

    def _build_cohort_summary(
        self,
        *,
        cohort: str,
        rows: list[SignalOutcomeORM],
        friction_scenario: str = "base",
    ) -> CohortValidationSummary:
        metrics = self._build_validation_bucket(
            key=cohort,
            rows=rows,
            friction_scenario=friction_scenario,
        )
        return CohortValidationSummary(
            cohort=cohort,
            total_signals=metrics.total_signals,
            evaluated_count=metrics.evaluated_count,
            pending_count=metrics.pending_count,
            win_rate=metrics.win_rate,
            avg_return=metrics.avg_return,
            expectancy=metrics.expectancy,
            avg_return_after_friction=metrics.avg_return_after_friction,
            expectancy_after_friction=metrics.expectancy_after_friction,
            false_positive_rate=metrics.false_positive_rate,
            min_sample_met=metrics.min_sample_met,
            is_underpowered=metrics.is_underpowered,
        )

    def get_execution_alignment_summary(
        self,
        asset_type: AssetType | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        friction_scenario: str = "base",
    ) -> ExecutionAlignmentResponse:
        normalized_start = self._normalize_report_datetime(start)
        normalized_end = self._normalize_report_datetime(end)
        rows = self._load_signal_outcome_rows(
            asset_type=asset_type,
            generated_at_start=normalized_start,
            generated_at_end=normalized_end,
        )
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
        blocked_outcome_ids = {
            row.signal_outcome_id
            for row in audit_rows
            if getattr(row, "signal_outcome_id", None) is not None and row.trade_gate_allowed is False
        }
        blocked_keys = {
            (row.signal_run_id, row.ticker.upper())
            for row in audit_rows
            if row.signal_run_id and row.trade_gate_allowed is False
        }
        submitted_keys = {
            (row.signal_run_id, row.ticker.upper())
            for row in audit_rows
            if row.signal_run_id and bool(getattr(row, "submitted", False))
        }
        dry_run_keys = {
            (row.signal_run_id, row.ticker.upper())
            for row in audit_rows
            if row.signal_run_id and getattr(row, "lifecycle_status", None) == "dry_run"
        }
        taken_rows = [row for row in rows if (row.run_id, row.ticker.upper()) in submitted_keys]
        dry_run_rows = [row for row in rows if (row.run_id, row.ticker.upper()) in dry_run_keys]
        journal_taken_rows = [row for row in rows if (row.run_id, row.ticker.upper()) in taken_keys]
        skipped_rows = [
            row
            for row in rows
            if (row.run_id, row.ticker.upper()) in skipped_keys
            and (row.run_id, row.ticker.upper()) not in taken_keys
        ]
        blocked_rows = [
            row
            for row in rows
            if row.id in blocked_outcome_ids or (row.run_id, row.ticker.upper()) in blocked_keys
        ]
        return ExecutionAlignmentResponse(
            start=normalized_start or start,
            end=normalized_end or end,
            primary_horizon=self._validation_horizon(),
            win_threshold_pct=self.settings.validation_win_threshold_pct,
            false_positive_threshold_pct=self.settings.validation_false_positive_threshold_pct,
            all_signals=self._build_cohort_summary(
                cohort="all_signals",
                rows=rows,
                friction_scenario=friction_scenario,
            ),
            taken_trades=self._build_cohort_summary(
                cohort="taken_trades",
                rows=taken_rows,
                friction_scenario=friction_scenario,
            ),
            journal_took=self._build_cohort_summary(
                cohort="journal_took",
                rows=journal_taken_rows,
                friction_scenario=friction_scenario,
            ),
            skipped_or_watched=self._build_cohort_summary(
                cohort="skipped_or_watched",
                rows=skipped_rows,
                friction_scenario=friction_scenario,
            ),
            blocked_previews=self._build_cohort_summary(
                cohort="blocked_previews",
                rows=blocked_rows,
                friction_scenario=friction_scenario,
            ),
            automation_dry_run=self._build_cohort_summary(
                cohort="automation_dry_run",
                rows=dry_run_rows,
                friction_scenario=friction_scenario,
            ),
        )

    def get_projection_outcome_stats(
        self,
        *,
        signal: str,
        score_band: str,
        current_regime: str | None = None,
    ) -> ProjectionOutcomeStats:
        all_rows = self._load_signal_outcome_rows()
        signal_rows = [r for r in all_rows if r.signal == signal]

        band_rows = [
            r for r in signal_rows
            if getattr(r, "score_band", self._score_band(self._raw_score_for(r))) == score_band
        ]

        low_sample_size = len(band_rows) < 15
        effective_rows = signal_rows if low_sample_size else band_rows

        horizon = self.PROJECTION_HORIZON
        returns = [
            v for r in effective_rows
            for v in [self._return_for_horizon(r, horizon)]
            if v is not None
        ]

        if len(returns) < 2:
            fallback_bucket = self._build_validation_bucket(
                key="projection_fallback",
                rows=effective_rows,
                horizon=horizon,
            )
            if fallback_bucket.evaluated_count >= 2 and fallback_bucket.median_return is not None:
                med = fallback_bucket.median_return
                p25 = fallback_bucket.avg_loss_return if fallback_bucket.avg_loss_return is not None else med
                p75 = fallback_bucket.avg_win_return if fallback_bucket.avg_win_return is not None else med
                return ProjectionOutcomeStats(
                    signal=signal,
                    score_band=score_band,
                    sample_count=fallback_bucket.evaluated_count,
                    low_sample_size=True,
                    median_daily_return_pct=round(med, 4),
                    p25_daily_return_pct=round(p25, 4),
                    p75_daily_return_pct=round(p75, 4),
                    regime_shift_pct=None,
                    regime_data_available=False,
                    current_regime=current_regime,
                )
            return ProjectionOutcomeStats(
                signal=signal,
                score_band=score_band,
                sample_count=len(returns),
                low_sample_size=low_sample_size,
                median_daily_return_pct=None,
                p25_daily_return_pct=None,
                p75_daily_return_pct=None,
                regime_shift_pct=None,
                regime_data_available=False,
                current_regime=current_regime,
            )

        q1, _q2, q3 = quantiles(returns, n=4)
        median_val = float(median(returns))

        regime_shift: float | None = None
        regime_data_available = False
        if current_regime and current_regime != "neutral":
            regime_rows = [
                r for r in signal_rows
                if getattr(r, "market_status", None) == current_regime
            ]
            neutral_rows = [
                r for r in signal_rows
                if getattr(r, "market_status", None) == "neutral"
            ]
            regime_returns = [
                v for r in regime_rows
                for v in [self._return_for_horizon(r, horizon)]
                if v is not None
            ]
            neutral_returns = [
                v for r in neutral_rows
                for v in [self._return_for_horizon(r, horizon)]
                if v is not None
            ]
            if len(regime_returns) >= 5 and len(neutral_returns) >= 5:
                regime_avg = sum(regime_returns) / len(regime_returns)
                neutral_avg = sum(neutral_returns) / len(neutral_returns)
                regime_shift = round(regime_avg - neutral_avg, 4)
                regime_data_available = True

        return ProjectionOutcomeStats(
            signal=signal,
            score_band=score_band,
            sample_count=len(returns),
            low_sample_size=low_sample_size,
            median_daily_return_pct=round(median_val, 4),
            p25_daily_return_pct=round(float(q1), 4),
            p75_daily_return_pct=round(float(q3), 4),
            regime_shift_pct=regime_shift,
            regime_data_available=regime_data_available,
            current_regime=current_regime,
        )
