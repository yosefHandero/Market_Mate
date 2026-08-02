from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from statistics import median, quantiles
import time

from sqlalchemy import desc, func, inspect, or_, select, update
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.core.decision_presentation import (
    build_decision_enrichment,
    build_exit_window,
    cap_confidence_by_data_quality,
    evidence_grade_label,
)
from app.core.freshness import signal_age_minutes as _signal_age_minutes
from app.core.structural_prediction import evaluate_exit_window_outcome_with_disambiguation, evaluate_prediction_accuracy
from app.core.weekly_backtest import PatternBacktestStats
from app.core.weekly_evidence import evaluate_weekly_pattern_evidence
from app.core.freshness_policy import enrich_scan_run_freshness
from app.core.ranking import display_sort_key, is_buy_candidate
from app.core.signals import map_score_to_decision_signal
from app.core.strategy_contract import build_strategy_evaluation_metadata, determine_recommended_action
from app.db import SessionLocal, engine
from app.models.journal import JournalEntryORM
from app.models.scan import (
    AutomationIntentORM,
    ExecutionAuditORM,
    PaperPositionORM,
    PredictionSnapshotORM,
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
    ConfidenceCalibration,
    ConfidenceCalibrationBucket,
    ConfidencePerformance,
    ConfidenceRanking,
    ConfidenceTierBucket,
    ExitWindowAccuracyMetrics,
    ExitWindowAssetMetrics,
    PaperLedgerSummaryResponse,
    PaperPositionSummary,
    PredictionAccuracyMetrics,
    PricePrediction,
    PromotionGateResult,
    PromotionReadinessResponse,
    SampleSource,
    ScanRun,
    ScanResult,
    SignalOutcomePerformanceBucket,
    SignalOutcomePerformanceReportResponse,
    SignalOutcomeSummary,
    TickerScanHistoryRow,
    TickerSignalOutcomeEvidence,
    TickerSignalOutcomeRecord,
    ThresholdRecommendation,
    ThresholdSweepResponse,
    ThresholdSweepRow,
    ValidationBucket,
    ValidationSummary,
    VariantComparison,
    WeeklyEvidenceProgress,
    WeeklyPatternPrediction,
)


logger = logging.getLogger(__name__)


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


_SQLITE_LOCK_RETRY_ATTEMPTS = 3
_SQLITE_LOCK_RETRY_BACKOFF_SECONDS = 0.25
_SQLITE_LOCK_MESSAGES = (
    "database is locked",
    "database table is locked",
    "database schema is locked",
)


def _is_transient_sqlite_lock(exc: OperationalError) -> bool:
    message = str(exc).lower()
    return any(lock_message in message for lock_message in _SQLITE_LOCK_MESSAGES)


@dataclass(frozen=True)
class PendingPredictionEvaluation:
    snapshot_id: int
    ticker: str
    asset_type: str
    horizon: str
    generated_at: datetime
    target_at: datetime
    expires_at: datetime
    decision_signal: str
    range_low: float
    range_high: float
    entry_price: float
    estimated_exit_price: float | None
    invalidation_level: float | None


@dataclass(frozen=True)
class PredictionEvaluationUpdate:
    snapshot_id: int
    status: str
    price: float | None
    evaluated_at: datetime
    exit_window_status: str | None = None
    exit_hit: bool | None = None
    invalidation_hit: bool | None = None
    protected_return_pct: float | None = None
    hold_return_pct: float | None = None
    exit_window_helped: bool | None = None


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
    pattern_name: str | None = None
    real_money_trust_blocked: bool | None = None


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
    real_money_trust_blocked: bool | None = None


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
    pending_due_1w_count: int = 0


@dataclass(frozen=True)
class PaperPositionDueForClose:
    id: int
    ticker: str
    asset_type: str


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
        "1w": timedelta(days=7),
    }
    _OUTCOME_EXPIRY_WINDOWS = {
        "15m": timedelta(hours=24),
        "1h": timedelta(days=3),
        "1d": timedelta(days=7),
        "1w": timedelta(days=14),
    }
    def __init__(self) -> None:
        self.settings = get_settings()

    def _schema_inspection_bind(self):
        session_bind = getattr(SessionLocal, "kw", {}).get("bind")
        return session_bind or engine

    def _prediction_snapshots_table_exists(self) -> bool:
        return inspect(self._schema_inspection_bind()).has_table("prediction_snapshots")

    def _has_exit_window_columns(self) -> bool:
        if not self._prediction_snapshots_table_exists():
            return False
        columns = {
            column["name"]
            for column in inspect(self._schema_inspection_bind()).get_columns("prediction_snapshots")
        }
        return "estimated_exit_price" in columns and "exit_window_helped" in columns

    def _has_provenance_columns(self) -> bool:
        if not self._prediction_snapshots_table_exists():
            return False
        columns = {
            column["name"]
            for column in inspect(self._schema_inspection_bind()).get_columns("prediction_snapshots")
        }
        return "campaign_id" in columns and "record_hash" in columns

    def _expected_friction_bps(self, asset_type: str) -> float:
        settings = self.settings
        if str(asset_type or "").lower() == "crypto":
            return float(
                (getattr(settings, "crypto_slippage_bps", 0.0) or 0.0)
                + (getattr(settings, "crypto_spread_bps", 0.0) or 0.0)
                + (getattr(settings, "crypto_fee_bps", 0.0) or 0.0)
            )
        return float(
            (getattr(settings, "stock_slippage_bps", 0.0) or 0.0)
            + (getattr(settings, "stock_spread_bps", 0.0) or 0.0)
            + (getattr(settings, "stock_fee_bps", 0.0) or 0.0)
        )

    def _rejection_reason_for(self, result) -> str:
        signal = getattr(result, "decision_signal", "HOLD")
        if signal == "HOLD":
            return "hold_no_directional_edge"
        if not bool(getattr(result, "gate_passed", True)):
            reason = getattr(result, "gate_reason", None)
            return f"gate_rejected:{reason}" if reason else "gate_rejected"
        return "not_selected"

    def _apply_snapshot_provenance(
        self,
        snapshot_kwargs: dict,
        *,
        result,
        campaign,
        selection_status: str,
        rejection_reason: str | None,
    ) -> None:
        """Stamp immutable campaign provenance + record hash onto a snapshot row."""
        from app.services.db_integrity import record_hash_for_snapshot

        asset_type = getattr(result, "asset_type", "stock")
        generated_at = snapshot_kwargs.get("generated_at") or result.created_at
        forward_days = int(getattr(self.settings, "weekly_forward_days", 7) or 7)
        # A one-day grace beyond the evaluation horizon; snapshots resolved after
        # this are flagged resolved_late for the outcome-catch-up diagnostics.
        resolve_due_at = generated_at + timedelta(days=forward_days + 1)
        # Record the ACTUAL bar source the scan used, not an asset-type assumption.
        # Crypto bars often come from Alpaca (with an optional Coinbase WS overlay),
        # so hardcoding "coinbase" mislabels provenance on live-forward evidence.
        # Fall back to the asset-type default only when the scan did not report one.
        actual_source = getattr(result, "price_source", None)
        if actual_source:
            provider_source = str(actual_source)
        else:
            provider_source = "coinbase" if str(asset_type).lower() == "crypto" else "alpaca"
        data_cutoff_at = getattr(result, "bar_as_of", None) or generated_at

        snapshot_kwargs.update(
            {
                "campaign_id": campaign.campaign_id,
                "strategy_version": campaign.strategy_version,
                "code_commit": campaign.code_commit,
                "config_fingerprint": campaign.config_fingerprint,
                "feature_version": campaign.feature_version,
                "provider_source": provider_source,
                "data_cutoff_at": data_cutoff_at,
                "expected_friction_bps": self._expected_friction_bps(asset_type),
                "candidate_rank": getattr(result, "selection_rank", None),
                "selection_status": selection_status,
                "rejection_reason": rejection_reason,
                "resolve_due_at": resolve_due_at,
                "resolved_late": False,
            }
        )
        snapshot_kwargs["record_hash"] = record_hash_for_snapshot(snapshot_kwargs)

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

    def _tracks_outcome_signal(self, signal: str) -> bool:
        if signal in {"BUY", "SELL"}:
            return True
        return signal == "HOLD" and self.settings.track_hold_outcomes

    def _live_forward_sample_source(self, ticker: str) -> str:
        """Deterministically assign a live outcome to the in-sample live_paper_forward
        track or the out-of-sample holdout, by ticker. The holdout's real forward
        outcomes are never used for calibration, so they form a genuine out-of-sample
        evidence track that can accrue automatically alongside live_paper_forward."""
        ratio = float(getattr(self.settings, "weekly_out_of_sample_holdout_ratio", 0.0) or 0.0)
        if ratio <= 0.0:
            return "live_paper_forward"
        ratio = min(ratio, 1.0)
        digest = hashlib.md5((ticker or "").strip().upper().encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) / 0xFFFFFFFF
        return "out_of_sample" if bucket < ratio else "live_paper_forward"

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
        elif signal == "HOLD":
            return round(raw_return, 4)
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
        if horizon == "1w":
            return self._signal_return(
                signal=row.signal,
                entry_price=row.entry_price,
                future_price=getattr(row, "price_after_1w", None),
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
        if horizon == "1w":
            return getattr(row, "return_after_1w", None)
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
        if horizon == "1w":
            row.return_after_1w = value
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

    def _trust_window_days(self, *, horizon: str | None = None) -> int:
        if (horizon or self.settings.trade_gate_horizon) == "1w":
            return max(int(self.settings.weekly_trust_window_days), 1)
        return max(int(self.settings.trust_recent_window_days), 1)

    def _trust_window_bounds(self, *, observed_at: datetime | None = None, horizon: str | None = None) -> TrustWindowBounds:
        comparable_end = self._normalize_report_datetime(observed_at or datetime.now(timezone.utc))
        if comparable_end is None:
            comparable_end = datetime.now(timezone.utc).replace(tzinfo=None)
        days = self._trust_window_days(horizon=horizon)
        return TrustWindowBounds(
            start=comparable_end - timedelta(days=days),
            end=comparable_end,
            days=days,
        )

    def trust_window_bounds_for(
        self,
        *,
        observed_at: datetime | None = None,
        horizon: str | None = None,
    ) -> tuple[datetime, datetime]:
        window = self._trust_window_bounds(observed_at=observed_at, horizon=horizon)
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
            provider_status=self._normalize_provider_status(getattr(row, "provider_status", "ok")),
            provider_warnings=self._deserialize_list(getattr(row, "provider_warnings_json", None)),
            layer_details=self._deserialize_dict(getattr(row, "layer_details_json", None)),
        )

    def _recommended_action_from_row(self, row: ScanResultORM, strategy_metadata) -> str:
        return determine_recommended_action(
            signal=self._resolve_decision_signal(row),
            execution_eligibility=strategy_metadata.execution_eligibility,
            evidence_quality=strategy_metadata.evidence_quality,
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
            metrics_1w=self._build_horizon_metrics(
                key=key,
                rows=rows,
                horizon="1w",
                min_evaluated_count=min_evaluated_count,
                friction_scenario=friction_scenario,
            ),
        )

    def _slice_metrics(self, slice_summary: OutcomePerformanceSlice, *, horizon: str) -> HorizonMetrics:
        if horizon == "15m":
            return slice_summary.metrics_15m
        if horizon == "1d":
            return slice_summary.metrics_1d
        if horizon == "1w":
            return slice_summary.metrics_1w
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
        if not isinstance(decoded, list):
            return []
        checks: list[GateCheck] = []
        for item in decoded:
            if not isinstance(item, dict):
                continue
            try:
                checks.append(GateCheck(**item))
            except Exception:
                continue
        return checks

    @staticmethod
    def _normalize_provider_status(value: str | None) -> str:
        normalized = (value or "ok").strip().lower()
        if normalized in {"ok", "degraded", "critical"}:
            return normalized
        return "degraded"

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
        if horizon == "1w":
            return bucket.evaluated_1w_count, bucket.win_rate_1w, bucket.avg_return_1w
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
        window = self._trust_window_bounds(observed_at=observed_at, horizon=horizon)
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
        # Crypto BUY is underpowered and weak after friction/out-of-sample; require a
        # higher sample bar before it can clear the gate. Stricter only.
        if asset_type == "crypto" and signal == "BUY":
            min_count = max(min_count, self.settings.trade_gate_crypto_buy_min_evaluated_count)
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
        window = self._trust_window_bounds(observed_at=observed_at, horizon=horizon)
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
        def _rank_scan_result(row: ScanResultORM) -> ScanResult:
            meta = self._strategy_metadata_from_row(row)
            return ScanResult(
                ticker=row.ticker,
                asset_type=getattr(row, "asset_type", "stock") or "stock",
                score=row.score,
                raw_score=row.score,
                explanation=row.explanation or "",
                price=row.price,
                price_change_pct=row.price_change_pct,
                relative_volume=row.relative_volume,
                sentiment_score=row.sentiment_score,
                filing_flag=row.filing_flag,
                breakout_flag=row.breakout_flag,
                market_status=row.market_status,
                sector_strength_score=row.sector_strength_score,
                gate_passed=bool(getattr(row, "gate_passed", False)),
                decision_signal=self._resolve_decision_signal(row),
                execution_eligibility=meta.execution_eligibility,
                provider_status=self._normalize_provider_status(getattr(row, "provider_status", "ok")),
                bar_age_minutes=getattr(row, "bar_age_minutes", None),
                created_at=row.created_at,
            )

        return sorted(
            rows,
            key=lambda row: display_sort_key(
                row,
                settings=self.settings,
                resolve_signal=self._resolve_decision_signal,
                scan_result=_rank_scan_result(row),
            ),
        )

    def scan_run_freshness_fields(
        self,
        created_at: datetime | None,
    ) -> tuple[float | None, bool | None]:
        return enrich_scan_run_freshness(created_at=created_at, settings=self.settings)

    def _decision_fields_from_layers(
        self,
        *,
        layer_details: dict,
        result_row: ScanResultORM,
        strategy_metadata,
    ) -> tuple[str, list[str], PricePrediction | None]:
        decision_block = (layer_details or {}).get("decision") or {}
        directional = (layer_details or {}).get("directional") or {}
        evidence_grade = decision_block.get("evidence_grade") or evidence_grade_label(
            getattr(strategy_metadata, "evidence_quality", "low") or "low"
        )
        top_reasons = list(decision_block.get("top_reasons") or [])
        prediction_payload = decision_block.get("prediction")
        price_prediction: PricePrediction | None = None
        if isinstance(prediction_payload, dict) and prediction_payload:
            try:
                price_prediction = PricePrediction.model_validate(prediction_payload)
            except Exception:
                price_prediction = None
        if not top_reasons:
            enrichment = build_decision_enrichment(
                price=float(getattr(result_row, "price", 0) or 0),
                decision_signal=self._resolve_decision_signal(result_row),
                volatility_regime=getattr(result_row, "volatility_regime", "normal") or "normal",
                horizon=getattr(strategy_metadata, "primary_holding_horizon", "1h") or "1h",
                asset_type=getattr(result_row, "asset_type", "stock") or "stock",
                evidence_quality=getattr(strategy_metadata, "evidence_quality", "low") or "low",
                directional_reasons=directional.get("reasons") or [],
                score_contributions=directional.get("score_contributions") or {},
                evidence_quality_reasons=getattr(strategy_metadata, "evidence_quality_reasons", ()) or (),
                explanation=getattr(result_row, "explanation", None),
                gate_reason=getattr(result_row, "gate_reason", None),
                gate_passed=bool(getattr(result_row, "gate_passed", False)),
            )
            evidence_grade = enrichment.evidence_grade
            top_reasons = enrichment.top_reasons
            if price_prediction is None:
                price_prediction = enrichment.price_prediction
        return evidence_grade, top_reasons, price_prediction

    def _weekly_prediction_from_layers(self, layer_details: dict) -> WeeklyPatternPrediction | None:
        decision_block = (layer_details or {}).get("decision") or {}
        payload = decision_block.get("weekly_prediction")
        if not isinstance(payload, dict) or not payload:
            return None
        try:
            return WeeklyPatternPrediction.model_validate(payload)
        except Exception:
            return None

    def _buy_candidate_presentation(
        self,
        *,
        price: float,
        decision_signal: DecisionSignal,
        weekly_prediction: WeeklyPatternPrediction | None,
        price_prediction: PricePrediction | None,
        evidence_quality: str,
        data_quality: str,
        calibrated_confidence: float,
    ):
        upside_probability_pct = (
            getattr(weekly_prediction, "upside_probability_pct", None)
            if weekly_prediction is not None
            else None
        )
        evidence_provenance = (
            getattr(weekly_prediction, "evidence_basis", None)
            if weekly_prediction is not None
            else None
        ) or "insufficient"
        confidence_score = cap_confidence_by_data_quality(calibrated_confidence, data_quality)
        buy_candidate = is_buy_candidate(
            decision_signal=decision_signal,
            weekly_directional_bias=(
                getattr(weekly_prediction, "directional_bias", None)
                if weekly_prediction is not None
                else None
            ),
            upside_probability_pct=upside_probability_pct,
        )
        exit_window = build_exit_window(
            price=price,
            weekly_prediction=weekly_prediction,
            price_prediction=price_prediction,
            decision_signal=decision_signal,
            evidence_quality=evidence_quality,
            data_quality=data_quality,
            forward_days=self.settings.weekly_forward_days,
        )
        return (
            upside_probability_pct,
            confidence_score,
            evidence_provenance,
            buy_candidate,
            exit_window,
        )

    def _build_decision_row(
        self,
        result: ScanResultORM,
        *,
        summary: SignalOutcomeSummary | None = None,
        horizon: str = "1h",
        rank: int | None = None,
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
        evidence_quality = strategy_metadata.evidence_quality
        recommended_action = determine_recommended_action(
            signal=decision_signal,
            execution_eligibility=execution_eligibility,
            evidence_quality=evidence_quality,
        )
        layer_details = self._deserialize_dict(getattr(result, "layer_details_json", None))
        evidence_grade, top_reasons, price_prediction = self._decision_fields_from_layers(
            layer_details=layer_details if isinstance(layer_details, dict) else {},
            result_row=result,
            strategy_metadata=strategy_metadata,
        )
        weekly_prediction = self._weekly_prediction_from_layers(layer_details if isinstance(layer_details, dict) else {})
        data_quality = getattr(result, "data_quality", "ok") or "ok"
        (
            upside_probability_pct,
            confidence_score,
            evidence_provenance,
            buy_candidate,
            exit_window,
        ) = self._buy_candidate_presentation(
            price=getattr(result, "price", 0.0) or 0.0,
            decision_signal=decision_signal,
            weekly_prediction=weekly_prediction,
            price_prediction=price_prediction,
            evidence_quality=evidence_quality,
            data_quality=data_quality,
            calibrated_confidence=calibrated_confidence,
        )
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
            evidence_quality=evidence_quality,
            evidence_quality_score=strategy_metadata.evidence_quality_score,
            evidence_quality_reasons=strategy_metadata.evidence_quality_reasons,
            data_grade=getattr(result, "data_grade", strategy_metadata.data_grade),
            execution_eligibility=execution_eligibility,
            provider_status=self._normalize_provider_status(getattr(result, "provider_status", "ok")),
            gate_passed=bool(getattr(result, "gate_passed", False)),
            bar_age_minutes=getattr(result, "bar_age_minutes", None),
            signal_age_minutes=age,
            freshness_flags=self._deserialize_dict(getattr(result, "freshness_flags_json", None)) or None,
            recommended_action=recommended_action,
            readiness_score=getattr(result, "readiness_score", None),
            readiness_band=getattr(result, "readiness_band", None),
            readiness_hard_stop=bool(getattr(result, "readiness_hard_stop", False)),
            readiness_reason=getattr(result, "readiness_reason", None),
            selection_rank=getattr(result, "selection_rank", None),
            is_top_pick=bool(getattr(result, "is_top_pick", False)),
            score_contributions=(
                ((layer_details.get("directional") or {}).get("score_contributions") or {})
                if isinstance(layer_details, dict)
                else {}
            ),
            evidence_grade=evidence_grade,
            top_reasons=top_reasons,
            price_prediction=price_prediction,
            weekly_prediction=weekly_prediction,
            exit_window=exit_window,
            upside_probability_pct=upside_probability_pct,
            confidence_score=confidence_score,
            evidence_provenance=evidence_provenance,
            is_buy_candidate=buy_candidate,
            strategy_version=strategy_metadata.strategy_version,
            short_metric_summary=(
                f"{result.price_change_pct:.1f}% day | "
                f"{result.relative_volume:.1f}x vol | "
                f"flow {result.options_flow_score:.0f}"
            ),
            rank=getattr(result, "rank", None),
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
        returns_1w = [
            value
            for value in (self._return_for_horizon(row, "1w") for row in rows)
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
            evaluated_1w_count=len(returns_1w),
            win_rate_1w=win_rate(returns_1w),
            avg_return_1w=self._avg(returns_1w),
        )

    def save_run(self, run: ScanRun) -> None:
        for attempt in range(_SQLITE_LOCK_RETRY_ATTEMPTS):
            try:
                self._save_run_once(run)
                return
            except OperationalError as exc:
                if not _is_transient_sqlite_lock(exc) or attempt == _SQLITE_LOCK_RETRY_ATTEMPTS - 1:
                    raise
                time.sleep(_SQLITE_LOCK_RETRY_BACKOFF_SECONDS * (attempt + 1))

    def _campaign_provenance(self):
        """Resolve (or open) the active evidence campaign for stamping snapshots.

        Computed before the run transaction opens so the campaign session does not
        nest inside ``SessionLocal.begin()``. Returns ``None`` when provenance
        columns or the campaigns table are unavailable (older databases), so the
        write path degrades gracefully."""
        if not self._has_provenance_columns():
            return None
        try:
            if not inspect(self._schema_inspection_bind()).has_table("evidence_campaigns"):
                return None
            from app.services.evidence_campaign import EvidenceCampaignService

            return EvidenceCampaignService(settings=self.settings).get_or_create_active_campaign()
        except Exception:  # pragma: no cover - campaign is best-effort provenance
            logger.exception("failed to resolve evidence campaign for scan run")
            return None

    def _save_run_once(self, run: ScanRun) -> None:
        campaign = self._campaign_provenance()
        with SessionLocal.begin() as session:
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
                        bar_as_of=getattr(result, "bar_as_of", None),
                        freshness_flags_json=self._serialize_dict(
                            getattr(result, "freshness_flags", {})
                        ),
                        layer_details_json=self._serialize_dict(getattr(result, "layer_details", {})),
                        comparison_json=self._serialize_model(getattr(result, "comparison", None)),
                        readiness_score=getattr(result, "readiness_score", 0.0) or 0.0,
                        readiness_band=getattr(result, "readiness_band", "none") or "none",
                        readiness_hard_stop=bool(getattr(result, "readiness_hard_stop", False)),
                        readiness_reason=getattr(result, "readiness_reason", None),
                        selection_rank=getattr(result, "selection_rank", None),
                        is_top_pick=bool(getattr(result, "is_top_pick", False)),
                    )
                )
                if self._tracks_outcome_signal(result.decision_signal):
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
                            sample_source=self._live_forward_sample_source(result.ticker),
                            pattern_name=(
                                getattr(result.weekly_prediction, "pattern_name", None)
                                if getattr(result, "weekly_prediction", None) is not None
                                else None
                            ),
                        )
                    )
                prediction = getattr(result, "weekly_prediction", None) or getattr(result, "price_prediction", None)
                if (
                    prediction
                    and self._tracks_outcome_signal(result.decision_signal)
                    and self._prediction_snapshots_table_exists()
                ):
                    metadata = None
                    if getattr(result, "weekly_prediction", None) is not None:
                        metadata = result.weekly_prediction.model_dump(mode="json")
                    exit_window = getattr(result, "exit_window", None)
                    snapshot_kwargs: dict = {
                        "run_id": run.run_id,
                        "ticker": result.ticker,
                        "asset_type": result.asset_type,
                        "signal": result.decision_signal,
                        "evidence_grade": getattr(result, "evidence_grade", "Weak") or "Weak",
                        "entry_price": result.price,
                        "range_low": prediction.range_low,
                        "range_high": prediction.range_high,
                        "horizon": getattr(prediction, "horizon", "1w"),
                        "invalidation": getattr(prediction, "invalidation", ""),
                        "methodology": getattr(prediction, "methodology", "pattern_recognition"),
                        "generated_at": result.created_at,
                        "status": "pending",
                        "sample_source": self._live_forward_sample_source(result.ticker),
                        "pattern_name": getattr(prediction, "pattern_name", None),
                        "pattern_metadata_json": self._serialize_dict(metadata) if metadata else None,
                    }
                    if self._has_exit_window_columns() and exit_window is not None:
                        snapshot_kwargs["estimated_exit_price"] = exit_window.estimated_exit_price
                        snapshot_kwargs["invalidation_level"] = exit_window.invalidation_level
                        snapshot_kwargs["projected_range_high"] = exit_window.projected_range_high
                        snapshot_kwargs["exit_window_status"] = "pending"
                    if self._has_provenance_columns() and campaign is not None:
                        self._apply_snapshot_provenance(
                            snapshot_kwargs,
                            result=result,
                            campaign=campaign,
                            selection_status="selected"
                            if bool(getattr(result, "is_top_pick", False))
                            else "accepted_outside_top_n",
                            rejection_reason=None,
                        )
                    session.add(PredictionSnapshotORM(**snapshot_kwargs))
                elif (
                    prediction
                    and campaign is not None
                    and self._has_provenance_columns()
                    and self._prediction_snapshots_table_exists()
                ):
                    # Counterfactual honesty: record candidates that were evaluated but
                    # not actioned (e.g. HOLD) with their rejection reason. These carry
                    # no outcome tracking (status "rejected_no_outcome") so they never
                    # enter the pending-resolution path, but they preserve full
                    # provenance for after-the-fact selection analysis.
                    rejected_kwargs: dict = {
                        "run_id": run.run_id,
                        "ticker": result.ticker,
                        "asset_type": result.asset_type,
                        "signal": result.decision_signal,
                        "evidence_grade": getattr(result, "evidence_grade", "Weak") or "Weak",
                        "entry_price": result.price,
                        "range_low": prediction.range_low,
                        "range_high": prediction.range_high,
                        "horizon": getattr(prediction, "horizon", "1w"),
                        "invalidation": getattr(prediction, "invalidation", ""),
                        "methodology": getattr(prediction, "methodology", "pattern_recognition"),
                        "generated_at": result.created_at,
                        "status": "rejected_no_outcome",
                        "sample_source": self._live_forward_sample_source(result.ticker),
                        "pattern_name": getattr(prediction, "pattern_name", None),
                    }
                    self._apply_snapshot_provenance(
                        rejected_kwargs,
                        result=result,
                        campaign=campaign,
                        selection_status="rejected",
                        rejection_reason=self._rejection_reason_for(result),
                    )
                    session.add(PredictionSnapshotORM(**rejected_kwargs))

    def _map_run(self, run: ScanRunORM, results: list[ScanResultORM]) -> ScanRun:
        sorted_results = self._sort_results_for_display(results)
        scan_age_minutes, scan_fresh = self.scan_run_freshness_fields(run.created_at)
        mapped_results: list[ScanResult] = []
        for index, r in enumerate(sorted_results):
            meta = self._strategy_metadata_from_row(r)
            layer_details = self._deserialize_dict(getattr(r, "layer_details_json", None))
            provider_health = (layer_details or {}).get("provider_health") or {}
            evidence_grade, top_reasons, price_prediction = self._decision_fields_from_layers(
                layer_details=layer_details if isinstance(layer_details, dict) else {},
                result_row=r,
                strategy_metadata=meta,
            )
            weekly_prediction = self._weekly_prediction_from_layers(layer_details if isinstance(layer_details, dict) else {})
            row_decision_signal = self._resolve_decision_signal(r)
            row_data_quality = getattr(r, "data_quality", "ok") or "ok"
            row_calibrated_confidence = getattr(r, "calibrated_confidence", r.score) or r.score
            (
                row_upside_probability_pct,
                row_confidence_score,
                row_evidence_provenance,
                row_buy_candidate,
                row_exit_window,
            ) = self._buy_candidate_presentation(
                price=r.price,
                decision_signal=row_decision_signal,
                weekly_prediction=weekly_prediction,
                price_prediction=price_prediction,
                evidence_quality=meta.evidence_quality,
                data_quality=row_data_quality,
                calibrated_confidence=row_calibrated_confidence,
            )
            mapped_results.append(
                ScanResult(
                    ticker=r.ticker,
                    asset_type=getattr(r, "asset_type", "stock") or "stock",
                    strategy_variant=getattr(r, "strategy_variant", getattr(run, "strategy_variant", "layered-v4")) or "layered-v4",
                    score=r.score,
                    raw_score=r.score,
                    calibrated_confidence=getattr(r, "calibrated_confidence", r.score) or r.score,
                    calibration_source=getattr(r, "calibration_source", "raw") or "raw",
                    confidence_label=meta.confidence_label,
                    strategy_id=meta.strategy_id,
                    strategy_version=meta.strategy_version,
                    strategy_primary_horizon=meta.primary_holding_horizon,
                    strategy_entry_assumption=meta.entry_assumption,
                    strategy_exit_assumption=meta.exit_assumption,
                    evidence_quality=meta.evidence_quality,
                    evidence_quality_score=meta.evidence_quality_score,
                    evidence_quality_reasons=list(meta.evidence_quality_reasons),
                    evidence_grade=evidence_grade,
                    top_reasons=top_reasons,
                    price_prediction=price_prediction,
                    weekly_prediction=weekly_prediction,
                    exit_window=row_exit_window,
                    upside_probability_pct=row_upside_probability_pct,
                    confidence_score=row_confidence_score,
                    evidence_provenance=row_evidence_provenance,
                    is_buy_candidate=row_buy_candidate,
                    data_grade=getattr(r, "data_grade", meta.data_grade),
                    execution_eligibility=meta.execution_eligibility,
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
                    provider_status=self._normalize_provider_status(getattr(r, "provider_status", "ok")),
                    provider_warnings=self._deserialize_list(
                        getattr(r, "provider_warnings_json", None)
                    ),
                    price_source=provider_health.get("price_source", "alpaca"),
                    fallback_used=bool(provider_health.get("fallback_used", False)),
                    bar_age_minutes=getattr(r, "bar_age_minutes", None),
                    bar_as_of=getattr(r, "bar_as_of", None),
                    freshness_flags=self._deserialize_dict(
                        getattr(r, "freshness_flags_json", None)
                    ),
                    layer_details=layer_details,
                    comparison=self._deserialize_comparison(getattr(r, "comparison_json", None)),
                    recommended_action=self._recommended_action_from_row(r, meta),
                    readiness_score=float(getattr(r, "readiness_score", 0.0) or 0.0),
                    readiness_band=getattr(r, "readiness_band", "none") or "none",
                    readiness_hard_stop=bool(getattr(r, "readiness_hard_stop", False)),
                    readiness_reason=getattr(r, "readiness_reason", None),
                    selection_rank=getattr(r, "selection_rank", None),
                    is_top_pick=bool(getattr(r, "is_top_pick", False)),
                    rank=index + 1,
                    created_at=r.created_at,
                )
            )
        top_stocks = sorted(
            [row for row in mapped_results if row.is_top_pick and row.asset_type == "stock"],
            key=lambda row: row.selection_rank or 999,
        )
        top_crypto = sorted(
            [row for row in mapped_results if row.is_top_pick and row.asset_type == "crypto"],
            key=lambda row: row.selection_rank or 999,
        )
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
            scan_age_minutes=scan_age_minutes,
            scan_fresh=scan_fresh,
            results=mapped_results,
            top_stocks=top_stocks,
            top_crypto=top_crypto,
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

    def get_ticker_scan_history(
        self,
        *,
        ticker: str,
        limit: int = 200,
        offset: int = 0,
    ) -> list[TickerScanHistoryRow]:
        symbol = ticker.strip().upper()
        if not symbol:
            return []
        with SessionLocal() as session:
            rows = session.execute(
                select(ScanResultORM, ScanRunORM)
                .join(ScanRunORM, ScanRunORM.run_id == ScanResultORM.run_id)
                .where(ScanResultORM.ticker == symbol)
                .order_by(desc(ScanResultORM.created_at), desc(ScanRunORM.created_at))
                .offset(offset)
                .limit(limit)
            ).all()

            history: list[TickerScanHistoryRow] = []
            for result_row, run_row in rows:
                mapped_result = self._map_run(run_row, [result_row]).results[0]
                history.append(
                    TickerScanHistoryRow(
                        run_id=run_row.run_id,
                        run_created_at=run_row.created_at,
                        market_status=run_row.market_status,
                        result=mapped_result,
                    )
                )
            return history

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
                    rank=index + 1,
                )
                for index, r in enumerate(sorted_rows)
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
            layer_details = self._deserialize_dict(getattr(row, "layer_details_json", None))
            pattern_name, weekly_trust_blocked = self._resolve_current_weekly_pattern(
                session=session,
                symbol=row.ticker,
                layer_details=layer_details,
                outcome_row=outcome_row,
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
                layer_details=layer_details,
                pattern_name=pattern_name,
                real_money_trust_blocked=weekly_trust_blocked,
            )

    def _resolve_current_weekly_pattern(
        self,
        *,
        session,
        symbol: str,
        layer_details: dict | None,
        outcome_row: SignalOutcomeORM | None,
    ) -> tuple[str | None, bool | None]:
        decision_block = (layer_details or {}).get("decision") or {}
        weekly_payload = decision_block.get("weekly_prediction")
        if isinstance(weekly_payload, dict) and weekly_payload.get("pattern_name"):
            return (
                weekly_payload.get("pattern_name"),
                weekly_payload.get("real_money_trust_blocked"),
            )
        outcome_pattern = getattr(outcome_row, "pattern_name", None)
        if outcome_pattern:
            return outcome_pattern, None
        if self._prediction_snapshots_table_exists():
            snapshot_pattern = session.execute(
                select(PredictionSnapshotORM.pattern_name)
                .where(
                    PredictionSnapshotORM.ticker == symbol.upper(),
                    PredictionSnapshotORM.pattern_name.isnot(None),
                )
                .order_by(desc(PredictionSnapshotORM.created_at), desc(PredictionSnapshotORM.id))
                .limit(1)
            ).scalar_one_or_none()
            if snapshot_pattern:
                return snapshot_pattern, None
        return None, None

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
        counts = {"15m": 0, "1h": 0, "1d": 0, "1w": 0}
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
        window = self._trust_window_bounds(
            observed_at=observed_at,
            horizon=self.settings.trade_gate_horizon,
        )
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
            pending_due_1w_count=due_counts.get("1w", 0),
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

    def get_paper_ledger_summary(
        self,
        *,
        mark_prices: dict[str, float] | None = None,
    ) -> PaperLedgerSummaryResponse:
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
        total_unrealized = 0.0
        has_unrealized = False
        if mark_prices:
            for row in open_rows:
                mark = mark_prices.get(row.ticker)
                if mark is None or mark <= 0:
                    continue
                side_multiplier = 1.0 if (row.side or "buy") == "buy" else -1.0
                total_unrealized += (
                    (float(mark) - float(row.simulated_fill_price or 0.0))
                    * float(row.quantity or 0.0)
                    * side_multiplier
                )
                has_unrealized = True
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
            total_unrealized_pnl=round(total_unrealized, 2) if has_unrealized else None,
        )

    def reconcile_paper_loop(self) -> ReconciliationReportResponse:
        issues: list[ReconciliationIssue] = []
        generated_at = datetime.now(timezone.utc)

        def preview_strategy_version(row: ExecutionAuditORM | None) -> str | None:
            if row is None or not getattr(row, "preview_payload", None):
                return None
            try:
                preview_payload = json.loads(row.preview_payload)
            except json.JSONDecodeError:
                return None
            trade_gate = preview_payload.get("trade_gate") if isinstance(preview_payload, dict) else None
            if not isinstance(trade_gate, dict):
                return None
            strategy_version = trade_gate.get("strategy_version")
            return str(strategy_version) if strategy_version is not None else None

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
        positions_by_intent_key = {row.intent_key: row for row in positions}
        for position in positions:
            intent = intents.get(position.intent_key)
            audit = audits.get(position.execution_audit_id) if position.execution_audit_id is not None else None
            is_manual_audit_position = audit is not None and bool(getattr(audit, "dry_run", False))
            quantity = float(position.quantity or 0.0)
            cost_basis_usd = float(position.cost_basis_usd or 0.0)
            if quantity <= 0 or cost_basis_usd <= 0:
                issues.append(
                    ReconciliationIssue(
                        kind="paper_position_invalid_quantity",
                        detail=f"Paper position {position.id} has invalid quantity or cost basis.",
                        paper_position_id=position.id,
                        execution_audit_id=position.execution_audit_id,
                    )
                )
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
            if audit is not None:
                audit_idempotency_key = (audit.idempotency_key or "").strip()
                if (
                    audit_idempotency_key
                    and position.intent_key != audit_idempotency_key
                    and not position.intent_key.startswith("manual-audit-")
                ):
                    issues.append(
                        ReconciliationIssue(
                            kind="paper_position_intent_key_audit_mismatch",
                            detail=(
                                f"Paper position {position.id} intent key does not match "
                                f"audit {audit.id} idempotency key."
                            ),
                            paper_position_id=position.id,
                            execution_audit_id=audit.id,
                        )
                    )
                audit_strategy_version = preview_strategy_version(audit)
                if (
                    position.strategy_version is not None
                    and audit_strategy_version is not None
                    and str(position.strategy_version) != audit_strategy_version
                ):
                    issues.append(
                        ReconciliationIssue(
                            kind="paper_position_strategy_version_mismatch",
                            detail=(
                                f"Paper position {position.id} strategy_version "
                                f"{position.strategy_version} differs from audit {audit.id} "
                                f"trade_gate strategy_version {audit_strategy_version}."
                            ),
                            paper_position_id=position.id,
                            execution_audit_id=audit.id,
                        )
                    )
        for intent in intents.values():
            if intent.status != "dry_run_complete":
                continue
            if intent.intent_key not in positions_by_intent_key:
                issues.append(
                    ReconciliationIssue(
                        kind="dry_run_without_ledger",
                        detail=f"Intent {intent.id} is dry_run_complete without a paper ledger row.",
                        intent_id=intent.id,
                        execution_audit_id=intent.execution_audit_id,
                    )
                )
        for audit in audits.values():
            audit_idempotency_key = (audit.idempotency_key or "").strip()
            expected_position_keys = {f"manual-audit-{audit.id}"}
            if audit_idempotency_key:
                expected_position_keys.add(audit_idempotency_key)
            has_matching_position = any(key in positions_by_intent_key for key in expected_position_keys)
            if (
                bool(getattr(audit, "dry_run", False))
                and audit.lifecycle_status == "dry_run"
                and audit.trade_gate_allowed is True
                and not has_matching_position
            ):
                issues.append(
                    ReconciliationIssue(
                        kind="dry_run_audit_without_ledger",
                        detail=f"Audit {audit.id} is dry_run without a matching paper ledger row.",
                        execution_audit_id=audit.id,
                    )
                )
            if (
                bool(getattr(audit, "dry_run", False))
                and (audit.side or "").lower() == "sell"
                and audit.lifecycle_status == "failed"
                and audit.error_message == "sell_without_open_position"
            ):
                issues.append(
                    ReconciliationIssue(
                        kind="sell_without_open_position",
                        detail=f"Audit {audit.id} attempted a paper SELL without an open BUY position.",
                        execution_audit_id=audit.id,
                    )
                )
        issues_by_kind = Counter(issue.kind for issue in issues)
        return ReconciliationReportResponse(
            generated_at=generated_at,
            ok=not issues,
            total_issues=len(issues),
            issues=issues,
            issues_by_kind=dict(issues_by_kind),
        )

    def repair_paper_reconcile_safe(self) -> ReconciliationReportResponse:
        """Apply deterministic, safe reconciliation repairs then re-run reconcile."""
        from app.services.automation_repository import AutomationRepository

        automation = AutomationRepository()
        with SessionLocal() as session:
            audits = session.execute(
                select(ExecutionAuditORM).where(ExecutionAuditORM.lifecycle_status == "dry_run")
            ).scalars().all()
            positions = {
                row.intent_key
                for row in session.execute(select(PaperPositionORM)).scalars().all()
            }
            for audit in audits:
                if audit.trade_gate_allowed is not True:
                    continue
                expected_keys = {f"manual-audit-{audit.id}"}
                if audit.idempotency_key:
                    expected_keys.add(audit.idempotency_key.strip())
                if any(key in positions for key in expected_keys):
                    continue
                fill_price = float(audit.latest_price or 0.0)
                if fill_price <= 0:
                    continue
                automation.record_paper_position_from_audit(
                    audit_id=audit.id,
                    simulated_fill_price=fill_price,
                )
        return self.reconcile_paper_loop()

    def persist_strategy_replay_run(
        self,
        *,
        replay_id: str,
        request_payload: dict,
        response_payload: dict,
        symbol_count: int,
        snapshot_count: int,
    ) -> None:
        from app.models.scan import StrategyReplayRunORM

        now = datetime.now(timezone.utc)
        with SessionLocal() as session:
            session.add(
                StrategyReplayRunORM(
                    replay_id=replay_id,
                    created_at=now,
                    request_json=json.dumps(request_payload, default=str),
                    response_json=json.dumps(response_payload, default=str),
                    symbol_count=symbol_count,
                    snapshot_count=snapshot_count,
                )
            )
            session.commit()

    def list_paper_positions_due_for_horizon_close(
        self,
        *,
        observed_at: datetime | None = None,
    ) -> list[PaperPositionDueForClose]:
        now = observed_at or datetime.now(timezone.utc)
        horizon = self.settings.trade_gate_horizon
        horizon_delta = {
            "15m": timedelta(minutes=15),
            "1h": timedelta(hours=1),
            "1d": timedelta(days=1),
            "1w": timedelta(days=self.settings.weekly_forward_days),
        }[horizon]
        due: list[PaperPositionDueForClose] = []
        with SessionLocal() as session:
            open_rows = session.execute(
                select(PaperPositionORM).where(
                    PaperPositionORM.status == "open",
                    PaperPositionORM.side == "buy",
                )
            ).scalars().all()
            for row in open_rows:
                opened_at = row.opened_at
                if opened_at.tzinfo is None:
                    opened_at = opened_at.replace(tzinfo=timezone.utc)
                if now - opened_at < horizon_delta:
                    continue
                due.append(
                    PaperPositionDueForClose(
                        id=row.id,
                        ticker=row.ticker,
                        asset_type=row.asset_type or "stock",
                    )
                )
        return due

    def close_open_positions_past_horizon(
        self,
        *,
        observed_at: datetime | None = None,
        market_prices: dict[str, float] | None = None,
    ) -> int:
        """Close open BUY paper positions that exceeded the primary trade-gate horizon."""
        now = observed_at or datetime.now(timezone.utc)
        horizon = self.settings.trade_gate_horizon
        horizon_delta = {
            "15m": timedelta(minutes=15),
            "1h": timedelta(hours=1),
            "1d": timedelta(days=1),
            "1w": timedelta(days=self.settings.weekly_forward_days),
        }[horizon]
        closed = 0
        with SessionLocal() as session:
            open_rows = session.execute(
                select(PaperPositionORM).where(
                    PaperPositionORM.status == "open",
                    PaperPositionORM.side == "buy",
                )
            ).scalars().all()
            for row in open_rows:
                opened_at = row.opened_at
                if opened_at.tzinfo is None:
                    opened_at = opened_at.replace(tzinfo=timezone.utc)
                if now - opened_at < horizon_delta:
                    continue
                entry_fill = float(row.simulated_fill_price or 0.0)
                if entry_fill <= 0:
                    continue
                if market_prices is not None:
                    close_price = market_prices.get(row.ticker)
                    if close_price is None or close_price <= 0:
                        continue
                    close_price = float(close_price)
                else:
                    close_price = entry_fill
                with SessionLocal() as close_session:
                    position = close_session.get(PaperPositionORM, row.id)
                    if position is None or position.status != "open":
                        continue
                    quantity = float(position.quantity or 0.0)
                    basis = float(position.cost_basis_usd or position.notional_usd or 0.0)
                    proceeds = round(quantity * close_price, 2)
                    position.close_price = close_price
                    position.realized_pnl = round(proceeds - basis, 2)
                    position.closed_at = now
                    position.status = "closed"
                    position.updated_at = now
                    close_session.commit()
                    closed += 1
        return closed

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
        limit: int | None = None,
    ) -> list[PendingSignalOutcomeEvaluation]:
        batch_limit = limit or self.settings.outcome_evaluation_batch_limit
        with SessionLocal() as session:
            rows = session.execute(
                select(SignalOutcomeORM)
                .where(
                    or_(
                        SignalOutcomeORM.price_after_15m.is_(None),
                        SignalOutcomeORM.price_after_1h.is_(None),
                        SignalOutcomeORM.price_after_1d.is_(None),
                        SignalOutcomeORM.price_after_1w.is_(None),
                    )
                )
                .order_by(SignalOutcomeORM.generated_at)
                .limit(batch_limit)
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
                    elif (
                        horizon == "1w"
                        and getattr(row, "price_after_1w", None) is None
                        and getattr(row, "status_1w", "pending") == "pending"
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
                elif evaluation.horizon == "1w" and getattr(row, "price_after_1w", None) is None:
                    row.evaluated_at_1w = evaluation.evaluated_at
                    row.status_1w = evaluation.status
                    if evaluation.price is not None:
                        row.price_after_1w = round(evaluation.price, 4)
                        row.return_after_1w = self._signal_return(
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
            pending_1w_count=due_pending_count("1w"),
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

    def get_ticker_signal_outcome_evidence(
        self,
        *,
        ticker: str,
        horizon: str = "1h",
        recent_limit: int = 20,
        max_rows: int = 1000,
    ) -> TickerSignalOutcomeEvidence:
        symbol = ticker.strip().upper()
        if horizon not in self._OUTCOME_HORIZONS:
            horizon = self.settings.trade_gate_horizon
        if not symbol:
            return TickerSignalOutcomeEvidence(
                ticker="",
                horizon=horizon,
                sample_size=0,
                evaluated_count=0,
                pending_count=0,
                win_count=0,
                loss_count=0,
                insufficient_sample=True,
                min_evaluated_for_rate=self.settings.outcome_report_min_evaluated_per_horizon,
                recent_outcomes=[],
            )

        with SessionLocal() as session:
            rows = session.execute(
                select(SignalOutcomeORM)
                .where(SignalOutcomeORM.ticker == symbol)
                .order_by(desc(SignalOutcomeORM.generated_at), desc(SignalOutcomeORM.id))
                .limit(max_rows)
            ).scalars().all()

        returns = [
            value
            for value in (self._return_for_horizon(row, horizon) for row in rows)
            if value is not None
        ]
        evaluated_count = len(returns)
        pending_count = max(len(rows) - evaluated_count, 0)
        win_count = sum(1 for value in returns if self._is_validation_win(value))
        loss_count = max(evaluated_count - win_count, 0)
        min_evaluated = self.settings.outcome_report_min_evaluated_per_horizon
        insufficient_sample = evaluated_count < min_evaluated
        variants = {
            getattr(row, "strategy_variant", None)
            for row in rows
            if getattr(row, "strategy_variant", None)
        }
        window = self._trust_window_bounds()

        def record(row: SignalOutcomeORM) -> TickerSignalOutcomeRecord:
            return_value = self._return_for_horizon(row, horizon)
            return TickerSignalOutcomeRecord(
                id=row.id,
                run_id=row.run_id,
                ticker=row.ticker,
                asset_type=getattr(row, "asset_type", self._asset_type_for_symbol(row.ticker))
                or "stock",
                signal=row.signal,
                confidence=row.confidence,
                raw_score=self._raw_score_for(row),
                generated_at=row.generated_at,
                entry_price=row.entry_price,
                horizon=horizon,
                status=getattr(row, f"status_{horizon}", "pending") or "pending",
                return_pct=return_value,
                evaluated_at=getattr(row, f"evaluated_at_{horizon}", None),
                strategy_variant=getattr(row, "strategy_variant", None),
                gate_passed=getattr(row, "gate_passed", None),
                gate_reason=getattr(row, "gate_reason", None),
            )

        return TickerSignalOutcomeEvidence(
            ticker=symbol,
            horizon=horizon,
            strategy_variant=next(iter(variants)) if len(variants) == 1 else None,
            trust_window_start=window.start,
            trust_window_end=window.end,
            sample_size=len(rows),
            evaluated_count=evaluated_count,
            pending_count=pending_count,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=(
                round((win_count / evaluated_count) * 100, 2)
                if evaluated_count and not insufficient_sample
                else None
            ),
            mean_return=self._avg(returns),
            median_return=self._median(returns),
            insufficient_sample=insufficient_sample,
            min_evaluated_for_rate=min_evaluated,
            recent_outcomes=[record(row) for row in rows[:recent_limit]],
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
        min_sample = self.settings.validation_min_sample_size
        sample_size_sufficient = overall.evaluated_count >= min_sample
        evaluated_fraction = (
            round(overall.evaluated_count / len(rows), 4) if rows else None
        )
        if sample_size_sufficient:
            confidence_note = (
                f"Evaluated sample ({overall.evaluated_count}) meets minimum ({min_sample})."
            )
        elif overall.evaluated_count > 0:
            confidence_note = (
                f"Evaluated sample ({overall.evaluated_count}) is below minimum ({min_sample}); "
                "validation metrics are provisional."
            )
        else:
            confidence_note = "No evaluated outcomes in the selected window."
        return ValidationSummary(
            start=normalized_start or start,
            end=normalized_end or end,
            primary_horizon=self._validation_horizon(),
            win_threshold_pct=self.settings.validation_win_threshold_pct,
            false_positive_threshold_pct=self.settings.validation_false_positive_threshold_pct,
            total_signals=len(rows),
            evaluated_count=overall.evaluated_count,
            pending_count=overall.pending_count,
            minimum_sample_size=min_sample,
            sample_size_sufficient=sample_size_sufficient,
            evaluated_fraction=evaluated_fraction,
            confidence_note=confidence_note,
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

    def list_due_prediction_evaluations(
        self,
        *,
        observed_at: datetime,
        limit: int | None = None,
    ) -> list[PendingPredictionEvaluation]:
        if not self._prediction_snapshots_table_exists():
            return []
        batch_limit = limit or self.settings.outcome_evaluation_batch_limit
        due_columns = [
            PredictionSnapshotORM.id,
            PredictionSnapshotORM.ticker,
            PredictionSnapshotORM.asset_type,
            PredictionSnapshotORM.horizon,
            PredictionSnapshotORM.generated_at,
            PredictionSnapshotORM.signal,
            PredictionSnapshotORM.range_low,
            PredictionSnapshotORM.range_high,
            PredictionSnapshotORM.entry_price,
        ]
        if self._has_exit_window_columns():
            due_columns.extend(
                [
                    PredictionSnapshotORM.estimated_exit_price,
                    PredictionSnapshotORM.invalidation_level,
                ]
            )
        with SessionLocal() as session:
            rows = session.execute(
                select(*due_columns)
                .where(PredictionSnapshotORM.status == "pending")
                .order_by(PredictionSnapshotORM.generated_at)
                .limit(batch_limit)
            ).all()

            due: list[PendingPredictionEvaluation] = []
            for row in rows:
                horizon = (row.horizon or "1h").strip().lower()
                if horizon not in self._OUTCOME_HORIZONS:
                    continue
                generated_at, comparable_observed_at = self._normalize_comparable_datetimes(
                    row.generated_at,
                    observed_at,
                )
                target_at = generated_at + self._OUTCOME_HORIZONS[horizon]
                if comparable_observed_at < target_at:
                    continue
                expires_at = target_at + self._OUTCOME_EXPIRY_WINDOWS[horizon]
                due.append(
                    PendingPredictionEvaluation(
                        snapshot_id=row.id,
                        ticker=row.ticker,
                        asset_type=getattr(row, "asset_type", "stock") or "stock",
                        horizon=horizon,
                        generated_at=generated_at,
                        target_at=target_at,
                        expires_at=expires_at,
                        decision_signal=row.signal,
                        range_low=float(row.range_low),
                        range_high=float(row.range_high),
                        entry_price=float(row.entry_price),
                        estimated_exit_price=(
                            float(row.estimated_exit_price)
                            if self._has_exit_window_columns() and row.estimated_exit_price is not None
                            else None
                        ),
                        invalidation_level=(
                            float(row.invalidation_level)
                            if self._has_exit_window_columns() and row.invalidation_level is not None
                            else None
                        ),
                    )
                )
            return due

    def apply_prediction_evaluations(
        self,
        evaluations: list[PredictionEvaluationUpdate],
    ) -> int:
        if not evaluations or not self._prediction_snapshots_table_exists():
            return 0

        has_provenance = self._has_provenance_columns()
        with SessionLocal() as session:
            select_columns = [
                PredictionSnapshotORM.id,
                PredictionSnapshotORM.signal,
                PredictionSnapshotORM.range_low,
                PredictionSnapshotORM.range_high,
                PredictionSnapshotORM.status,
            ]
            if has_provenance:
                select_columns.append(PredictionSnapshotORM.resolve_due_at)
            snapshot_rows = {
                row.id: row
                for row in session.execute(
                    select(*select_columns).where(
                        PredictionSnapshotORM.id.in_([item.snapshot_id for item in evaluations])
                    )
                ).all()
            }
            updated = 0
            for evaluation in evaluations:
                row = snapshot_rows.get(evaluation.snapshot_id)
                if row is None or row.status != "pending":
                    continue
                verdict = evaluate_prediction_accuracy(
                    decision_signal=row.signal,
                    range_low=float(row.range_low),
                    range_high=float(row.range_high),
                    price_at_horizon=evaluation.price,
                )
                values: dict = {
                    "status": evaluation.status,
                    "price_at_horizon": evaluation.price,
                    "accuracy_outcome": verdict.outcome,
                    "in_range": verdict.in_range,
                    "evaluated_at": evaluation.evaluated_at,
                }
                if has_provenance:
                    due_at = getattr(row, "resolve_due_at", None)
                    if due_at is not None and evaluation.evaluated_at is not None:
                        due_cmp, eval_cmp = self._normalize_comparable_datetimes(
                            due_at, evaluation.evaluated_at
                        )
                        values["resolved_late"] = bool(eval_cmp > due_cmp)
                if self._has_exit_window_columns() and evaluation.exit_window_status is not None:
                    values.update(
                        {
                            "exit_window_status": evaluation.exit_window_status,
                            "exit_hit": evaluation.exit_hit,
                            "invalidation_hit": evaluation.invalidation_hit,
                            "protected_return_pct": evaluation.protected_return_pct,
                            "hold_return_pct": evaluation.hold_return_pct,
                            "exit_window_helped": evaluation.exit_window_helped,
                        }
                    )
                session.execute(
                    update(PredictionSnapshotORM)
                    .where(PredictionSnapshotORM.id == evaluation.snapshot_id)
                    .values(**values)
                )
                updated += 1
            session.commit()
            return updated

    def get_top_rejection_reasons(self, *, limit: int = 8) -> list[dict[str, object]]:
        """Most common rejection reasons from recent prediction snapshots."""
        if not self._has_provenance_columns():
            return []
        with SessionLocal() as session:
            rows = session.execute(
                select(
                    PredictionSnapshotORM.rejection_reason,
                    func.count(PredictionSnapshotORM.id),
                )
                .where(
                    PredictionSnapshotORM.selection_status == "rejected",
                    PredictionSnapshotORM.rejection_reason.isnot(None),
                )
                .group_by(PredictionSnapshotORM.rejection_reason)
                .order_by(desc(func.count(PredictionSnapshotORM.id)))
                .limit(limit)
            ).all()
        return [
            {"reason": str(reason), "count": int(count)}
            for reason, count in rows
            if reason
        ]

    def get_pending_prediction_count(self) -> int:
        with SessionLocal() as session:
            return int(
                session.execute(
                    select(func.count(PredictionSnapshotORM.id)).where(
                        PredictionSnapshotORM.status == "pending"
                    )
                ).scalar_one()
                or 0
            )

    def get_live_forward_progress(self):
        """Campaign-scoped live-forward accumulation for the Proof page.

        Counts selected / accepted-outside-top-N / rejected snapshots and their
        resolution state for the active campaign, plus a scan-gap diagnostic
        (last scan age vs an expected cadence) so missed windows are visible.
        This is transparency/completion progress, not real-money readiness."""
        from app.schemas import LiveForwardAssetProgress, LiveForwardProgress

        if not self._has_provenance_columns():
            return LiveForwardProgress(
                note="Provenance columns not migrated yet. Run alembic upgrade head."
            )

        active = None
        try:
            from app.services.evidence_campaign import EvidenceCampaignService

            active = EvidenceCampaignService(settings=self.settings).get_active_campaign()
        except Exception:  # pragma: no cover - campaign lookup is best-effort
            logger.exception("failed to load active campaign for live-forward progress")

        last_scan_at = self.get_latest_run_timestamp()
        age_minutes, _ = self.scan_run_freshness_fields(last_scan_at) if last_scan_at else (None, None)
        max_gap = float(getattr(self.settings, "live_forward_max_scan_gap_minutes", 1560.0) or 1560.0)
        gap_exceeded = bool(age_minutes is not None and age_minutes > max_gap)

        progress = LiveForwardProgress(
            last_scan_at=last_scan_at,
            last_scan_age_minutes=age_minutes,
            scan_gap_exceeded=gap_exceeded,
            max_expected_scan_gap_minutes=max_gap,
        )
        if active is not None:
            progress.campaign_id = active.campaign_id
            progress.campaign_started_at = active.started_at
            progress.config_fingerprint = active.config_fingerprint
            progress.strategy_version = active.strategy_version
            progress.code_commit = active.code_commit

        if active is None:
            progress.note = "No active evidence campaign yet. Progress starts after the next scan."
            return progress

        with SessionLocal() as session:
            rows = session.execute(
                select(
                    PredictionSnapshotORM.asset_type,
                    PredictionSnapshotORM.selection_status,
                    PredictionSnapshotORM.status,
                    PredictionSnapshotORM.resolved_late,
                ).where(PredictionSnapshotORM.campaign_id == active.campaign_id)
            ).all()

        buckets: dict[str, LiveForwardAssetProgress] = {
            asset: LiveForwardAssetProgress(asset_type=asset) for asset in ("stock", "crypto")
        }
        for row in rows:
            asset = (row.asset_type or "stock") if row.asset_type in ("stock", "crypto") else "stock"
            bucket = buckets[asset]
            selection = row.selection_status or "selected"
            if selection == "selected":
                bucket.selected += 1
            elif selection == "accepted_outside_top_n":
                bucket.accepted_outside_top_n += 1
            elif selection == "rejected":
                bucket.rejected += 1
            if selection != "rejected":
                if row.status == "pending":
                    bucket.pending += 1
                elif row.status not in ("rejected_no_outcome",):
                    bucket.resolved += 1
            if row.resolved_late:
                bucket.resolved_late += 1

        progress.by_asset = [buckets[asset] for asset in ("stock", "crypto")]
        progress.selected_count = sum(b.selected for b in progress.by_asset)
        progress.accepted_outside_top_n_count = sum(b.accepted_outside_top_n for b in progress.by_asset)
        progress.rejected_count = sum(b.rejected for b in progress.by_asset)
        progress.resolved_count = sum(b.resolved for b in progress.by_asset)
        progress.pending_count = sum(b.pending for b in progress.by_asset)
        progress.resolved_late_count = sum(b.resolved_late for b in progress.by_asset)
        try:
            from app.services.scan_windows import ScanWindowService

            progress.missed_windows_14d = ScanWindowService().missed_count(lookback_days=14)
        except Exception:
            progress.missed_windows_14d = 0
        if gap_exceeded:
            progress.note = (
                f"Last scan was {age_minutes:.0f} min ago, beyond the {max_gap:.0f}-min "
                "expected cadence. A scheduled window may have been missed."
            )
        elif progress.missed_windows_14d:
            progress.note = (
                f"{progress.missed_windows_14d} expected scan window(s) missed in the last 14 days."
            )
        return progress

    def get_prediction_accuracy_summary(self) -> PredictionAccuracyMetrics:
        if not self._prediction_snapshots_table_exists():
            return PredictionAccuracyMetrics(
                note="Prediction snapshot table not migrated yet. Run alembic upgrade head.",
            )
        with SessionLocal() as session:
            rows = session.execute(
                select(
                    PredictionSnapshotORM.status,
                    PredictionSnapshotORM.accuracy_outcome,
                )
            ).all()
        if not rows:
            return PredictionAccuracyMetrics(
                note="No prediction snapshots yet. Accuracy tracking starts after the next BUY/SELL scans.",
            )
        pending = sum(1 for row in rows if row.status == "pending")
        evaluated = [
            row
            for row in rows
            if row.status not in ("pending", "rejected_no_outcome")
        ]
        in_range = sum(1 for row in evaluated if row.accuracy_outcome == "in_range")
        below = sum(1 for row in evaluated if row.accuracy_outcome == "below_range")
        above = sum(1 for row in evaluated if row.accuracy_outcome == "above_range")
        missed = sum(1 for row in evaluated if row.accuracy_outcome == "missed")
        evaluated_count = len(evaluated)
        rate = round((in_range / evaluated_count) * 100, 2) if evaluated_count else None
        note = (
            "Structural range accuracy at the primary horizon. Low sample sizes are not statistically meaningful."
            if evaluated_count < 30
            else "Structural range accuracy at the primary horizon."
        )
        return PredictionAccuracyMetrics(
            evaluated_count=evaluated_count,
            pending_count=pending,
            in_range_count=in_range,
            in_range_rate_pct=rate,
            below_range_count=below,
            above_range_count=above,
            missed_count=missed,
            note=note,
        )

    _SCORE_BAND_ORDER = ("0-59", "60-69", "70-79", "80-89", "90-100")
    _PROBABILITY_BAND_ORDER = ("<50", "50-59", "60-69", "70-79", "80-89", "90-100")

    def _probability_band(self, value: float) -> str:
        if value < 50:
            return "<50"
        if value < 60:
            return "50-59"
        if value < 70:
            return "60-69"
        if value < 80:
            return "70-79"
        if value < 90:
            return "80-89"
        return "90-100"

    def _score_band_rank(self, band: str) -> int:
        return self._SCORE_BAND_ORDER.index(band) if band in self._SCORE_BAND_ORDER else len(self._SCORE_BAND_ORDER)

    def _confidence_ranking_is_monotonic(
        self,
        buckets: list[ConfidenceTierBucket],
    ) -> bool | None:
        """Within each comparable group (asset_type/signal/sample_source), check that
        avg return does not fall as the confidence band rises. Returns None when no
        group has 2+ evaluated bands, since ranking cannot yet be judged."""
        groups: dict[tuple[str, str, str], list[ConfidenceTierBucket]] = {}
        for bucket in buckets:
            groups.setdefault((bucket.asset_type, bucket.signal, bucket.sample_source), []).append(bucket)
        checked_any = False
        for group in groups.values():
            ordered = sorted(group, key=lambda item: self._score_band_rank(item.score_band))
            values = [item.avg_return_pct for item in ordered if item.avg_return_pct is not None]
            if len(values) < 2:
                continue
            checked_any = True
            for index in range(1, len(values)):
                if values[index] < values[index - 1] - 1e-9:
                    return False
        return True if checked_any else None

    def get_confidence_tier_performance(self) -> ConfidenceRanking:
        """Resolved 1-week outcomes grouped by confidence band, split by asset type,
        signal, and evidence track, with after-friction (base + stressed) returns.
        Proves whether higher-confidence picks actually outperform lower-confidence
        picks - ranking, not just display."""
        sample_source_available = self._has_sample_source_column()
        with SessionLocal() as session:
            rows = session.execute(
                select(SignalOutcomeORM).where(SignalOutcomeORM.return_after_1w.isnot(None))
            ).scalars().all()
        if not rows:
            return ConfidenceRanking(
                note="No resolved 1-week outcomes yet. Confidence ranking starts once outcomes resolve.",
            )
        grouped: dict[tuple[str, str, str, str], list[SignalOutcomeORM]] = {}
        for row in rows:
            band = getattr(row, "score_band", None) or self._score_band(self._raw_score_for(row))
            asset_type = getattr(row, "asset_type", None) or self._asset_type_for_symbol(row.ticker)
            source = (
                (getattr(row, "sample_source", None) or "live_paper_forward")
                if sample_source_available
                else "unknown"
            )
            grouped.setdefault((asset_type, row.signal, source, band), []).append(row)
        buckets: list[ConfidenceTierBucket] = []
        for (asset_type, signal, source, band), group_rows in grouped.items():
            returns = [float(r.return_after_1w) for r in group_rows if r.return_after_1w is not None]
            if not returns:
                continue
            wins = sum(1 for value in returns if self._is_validation_win(value))
            base_adjusted = [
                self._apply_friction_to_return(value, asset_type=asset_type, scenario="base")
                for value in returns
            ]
            stressed_adjusted = [
                self._apply_friction_to_return(value, asset_type=asset_type, scenario="stressed")
                for value in returns
            ]
            buckets.append(
                ConfidenceTierBucket(
                    score_band=band,
                    asset_type=asset_type,
                    signal=signal,
                    sample_source=source,
                    evaluated_count=len(returns),
                    win_rate_pct=round((wins / len(returns)) * 100, 2),
                    avg_return_pct=self._avg(returns),
                    avg_return_after_friction_base_pct=self._avg(
                        [value for value in base_adjusted if value is not None]
                    ),
                    avg_return_after_friction_stressed_pct=self._avg(
                        [value for value in stressed_adjusted if value is not None]
                    ),
                )
            )
        buckets.sort(
            key=lambda bucket: (
                bucket.asset_type,
                bucket.signal,
                bucket.sample_source,
                self._score_band_rank(bucket.score_band),
            )
        )
        monotonic = self._confidence_ranking_is_monotonic(buckets)
        if monotonic is None:
            note = "Not enough confidence bands with resolved outcomes yet to judge ranking."
        elif monotonic:
            note = "Higher-confidence bands are not underperforming lower bands in the resolved sample."
        else:
            note = "At least one group shows higher-confidence bands underperforming lower bands."
        return ConfidenceRanking(buckets=buckets, monotonic_by_group=monotonic, note=note)

    def get_confidence_calibration(self) -> ConfidenceCalibration:
        """Predicted upside probability vs realized up-rate, bucketed by probability
        band and split by asset type. Proves calibration: a predicted 70% should
        resolve up about 70% of the time."""
        if not self._prediction_snapshots_table_exists():
            return ConfidenceCalibration(
                note="Prediction snapshot table not migrated yet. Run alembic upgrade head.",
            )
        with SessionLocal() as session:
            rows = session.execute(
                select(
                    PredictionSnapshotORM.status,
                    PredictionSnapshotORM.price_at_horizon,
                    PredictionSnapshotORM.entry_price,
                    PredictionSnapshotORM.pattern_metadata_json,
                    PredictionSnapshotORM.asset_type,
                ).where(
                    PredictionSnapshotORM.status != "pending",
                    PredictionSnapshotORM.price_at_horizon.isnot(None),
                )
            ).all()
        samples: list[tuple[float, float, str]] = []
        for row in rows:
            metadata = self._deserialize_dict(row.pattern_metadata_json)
            predicted = metadata.get("upside_probability_pct") if isinstance(metadata, dict) else None
            if predicted is None:
                continue
            entry = float(row.entry_price)
            horizon_price = row.price_at_horizon
            if horizon_price is None or entry <= 0:
                continue
            realized_up = 1.0 if float(horizon_price) > entry else 0.0
            asset_type = row.asset_type or "stock"
            samples.append((float(predicted), realized_up, asset_type))
        if not samples:
            return ConfidenceCalibration(
                note="No resolved snapshots with a predicted upside probability yet.",
            )
        grouped: dict[tuple[str, str], list[tuple[float, float]]] = {}
        for predicted, realized_up, asset_type in samples:
            grouped.setdefault((asset_type, self._probability_band(predicted)), []).append(
                (predicted, realized_up)
            )
        buckets: list[ConfidenceCalibrationBucket] = []
        gaps: list[float] = []
        for (asset_type, band), items in grouped.items():
            predicted_values = [predicted for predicted, _ in items]
            realized_values = [realized for _, realized in items]
            avg_predicted = round(sum(predicted_values) / len(predicted_values), 2)
            realized_up_rate = round((sum(realized_values) / len(realized_values)) * 100, 2)
            gap = round(avg_predicted - realized_up_rate, 2)
            gaps.append(abs(gap))
            buckets.append(
                ConfidenceCalibrationBucket(
                    probability_band=band,
                    asset_type=asset_type,
                    evaluated_count=len(items),
                    avg_predicted_pct=avg_predicted,
                    realized_up_rate_pct=realized_up_rate,
                    reliability_gap_pct=gap,
                )
            )
        buckets.sort(
            key=lambda bucket: (
                bucket.asset_type,
                self._PROBABILITY_BAND_ORDER.index(bucket.probability_band)
                if bucket.probability_band in self._PROBABILITY_BAND_ORDER
                else len(self._PROBABILITY_BAND_ORDER),
            )
        )
        return ConfidenceCalibration(
            buckets=buckets,
            mean_abs_reliability_gap_pct=round(sum(gaps) / len(gaps), 2) if gaps else None,
            note=(
                "Predicted upside probability vs realized up-rate. "
                "Low per-bucket counts are not statistically meaningful."
            ),
        )

    def get_confidence_performance(self) -> ConfidencePerformance:
        return ConfidencePerformance(
            ranking=self.get_confidence_tier_performance(),
            calibration=self.get_confidence_calibration(),
        )

    def get_exit_window_accuracy_summary(self) -> ExitWindowAccuracyMetrics:
        if not self._prediction_snapshots_table_exists():
            return ExitWindowAccuracyMetrics(
                note="Prediction snapshot table not migrated yet. Run alembic upgrade head.",
            )
        if not self._has_exit_window_columns():
            return ExitWindowAccuracyMetrics(
                note="Exit-window columns not migrated yet. Run alembic upgrade head.",
            )
        with SessionLocal() as session:
            summary_columns = [
                PredictionSnapshotORM.status,
                PredictionSnapshotORM.exit_window_status,
                PredictionSnapshotORM.exit_window_helped,
                PredictionSnapshotORM.protected_return_pct,
                PredictionSnapshotORM.hold_return_pct,
                PredictionSnapshotORM.asset_type,
            ]
            rows = session.execute(select(*summary_columns)).all()
        if not rows:
            return ExitWindowAccuracyMetrics(
                note="No prediction snapshots yet. Exit-window proof starts after BUY scans with exit targets.",
            )
        pending = sum(
            1
            for row in rows
            if row.status != "rejected_no_outcome"
            and ((row.exit_window_status or "pending") == "pending" or row.status == "pending")
        )
        evaluated = [
            row
            for row in rows
            if row.exit_window_status == "resolved" and row.exit_window_helped is not None
        ]
        helped = sum(1 for row in evaluated if row.exit_window_helped)
        evaluated_count = len(evaluated)
        helped_rate = round((helped / evaluated_count) * 100, 2) if evaluated_count else None
        by_asset: list[ExitWindowAssetMetrics] = []
        for asset_type in ("stock", "crypto"):
            asset_rows = [
                row for row in evaluated if (getattr(row, "asset_type", "stock") or "stock") == asset_type
            ]
            asset_pending = sum(
                1
                for row in rows
                if (getattr(row, "asset_type", "stock") or "stock") == asset_type
                and row.status != "rejected_no_outcome"
                and ((row.exit_window_status or "pending") == "pending" or row.status == "pending")
            )
            if not asset_rows and asset_pending == 0:
                continue
            protected = [float(row.protected_return_pct) for row in asset_rows if row.protected_return_pct is not None]
            hold = [float(row.hold_return_pct) for row in asset_rows if row.hold_return_pct is not None]
            protected_stressed = [
                self._apply_friction_to_return(value, asset_type=asset_type, scenario="stressed")
                for value in protected
            ]
            hold_stressed = [
                self._apply_friction_to_return(value, asset_type=asset_type, scenario="stressed")
                for value in hold
            ]
            asset_helped = sum(1 for row in asset_rows if row.exit_window_helped)
            by_asset.append(
                ExitWindowAssetMetrics(
                    asset_type=asset_type,
                    evaluated_count=len(asset_rows),
                    pending_count=asset_pending,
                    helped_count=asset_helped,
                    helped_rate_pct=(
                        round((asset_helped / len(asset_rows)) * 100, 2) if asset_rows else None
                    ),
                    avg_protected_return_pct=self._avg(protected),
                    avg_hold_return_pct=self._avg(hold),
                    avg_protected_after_friction_stressed_pct=self._avg(
                        [value for value in protected_stressed if value is not None]
                    ),
                    avg_hold_after_friction_stressed_pct=self._avg(
                        [value for value in hold_stressed if value is not None]
                    ),
                )
            )
        note = (
            "Exit-window vs hold-to-horizon at 1 week. Low sample sizes are not statistically meaningful."
            if evaluated_count < 30
            else "Exit-window vs hold-to-horizon at 1 week."
        )
        return ExitWindowAccuracyMetrics(
            evaluated_count=evaluated_count,
            pending_count=pending,
            helped_count=helped,
            helped_rate_pct=helped_rate,
            by_asset_type=by_asset,
            note=note,
        )

    def _has_sample_source_column(self) -> bool:
        return "sample_source" in {column["name"] for column in inspect(engine).get_columns("signal_outcomes")}

    def get_weekly_pattern_stats(
        self,
        *,
        pattern_name: str,
        asset_type: str,
        sample_source: SampleSource,
        signal: str | None = None,
    ) -> PatternBacktestStats:
        column_present = self._has_sample_source_column()
        # Fail closed: trust sources (live/out-of-sample) require the provenance column.
        # Without it we cannot prove a sample is genuinely live/out-of-sample, so report
        # zero rather than silently merging calibration and trust evidence together.
        if not column_present and sample_source in ("live_paper_forward", "out_of_sample"):
            return PatternBacktestStats(
                pattern_name=pattern_name,
                sample_size=0,
                hit_rate_pct=None,
                avg_forward_return_pct=None,
            )
        with SessionLocal() as session:
            query = select(SignalOutcomeORM).where(
                SignalOutcomeORM.asset_type == asset_type,
                SignalOutcomeORM.return_after_1w.isnot(None),
            )
            if column_present:
                query = query.where(SignalOutcomeORM.sample_source == sample_source)
            if signal is not None:
                query = query.where(SignalOutcomeORM.signal == signal)
            rows = session.execute(query).scalars().all()

        filtered = [
            row
            for row in rows
            if (getattr(row, "pattern_name", None) or "") == pattern_name
        ]
        if not filtered:
            return PatternBacktestStats(
                pattern_name=pattern_name,
                sample_size=0,
                hit_rate_pct=None,
                avg_forward_return_pct=None,
            )
        returns = [float(row.return_after_1w) for row in filtered if row.return_after_1w is not None]
        wins = sum(1 for value in returns if self._is_validation_win(value))
        return PatternBacktestStats(
            pattern_name=pattern_name,
            sample_size=len(returns),
            hit_rate_pct=round((wins / len(returns)) * 100, 2) if returns else None,
            avg_forward_return_pct=round(sum(returns) / len(returns), 4) if returns else None,
        )

    def get_weekly_evidence_progress(self) -> WeeklyEvidenceProgress:
        """Aggregate resolved 1w outcome counts per evidence track, for a transparency
        progress view. This is a sample-count gate only; per-candidate performance and
        per-pattern checks (see evaluate_weekly_pattern_gate) remain authoritative and
        are shown on each decision card."""
        counts = {
            "historical": 0,
            "backfilled_replay": 0,
            "live_paper_forward": 0,
            "out_of_sample": 0,
        }
        if self._has_sample_source_column():
            with SessionLocal() as session:
                sources = session.execute(
                    select(SignalOutcomeORM.sample_source).where(
                        SignalOutcomeORM.return_after_1w.isnot(None)
                    )
                ).scalars().all()
            for source in sources:
                key = source or "live_paper_forward"
                if key in counts:
                    counts[key] += 1
        s = self.settings
        trust_sample_gate_met = (
            counts["live_paper_forward"] >= s.weekly_pattern_gate_min_live_forward_samples
            and counts["out_of_sample"] >= s.weekly_pattern_gate_min_out_of_sample_samples
        )
        calibration_sample_gate_met = (
            counts["historical"] >= s.weekly_pattern_gate_min_historical_samples
            or counts["backfilled_replay"] >= s.weekly_pattern_gate_min_backfilled_samples
        )
        return WeeklyEvidenceProgress(
            live_forward_samples=counts["live_paper_forward"],
            out_of_sample_samples=counts["out_of_sample"],
            historical_samples=counts["historical"],
            backfilled_replay_samples=counts["backfilled_replay"],
            min_live_forward_samples=s.weekly_pattern_gate_min_live_forward_samples,
            min_out_of_sample_samples=s.weekly_pattern_gate_min_out_of_sample_samples,
            min_historical_samples=s.weekly_pattern_gate_min_historical_samples,
            min_backfilled_replay_samples=s.weekly_pattern_gate_min_backfilled_samples,
            trust_sample_gate_met=trust_sample_gate_met,
            calibration_sample_gate_met=calibration_sample_gate_met,
        )

    def evaluate_weekly_pattern_gate(
        self,
        *,
        pattern_name: str,
        asset_type: AssetType,
        observed_at: datetime | None = None,
        signal: str | None = None,
    ) -> EvidenceGateEvaluation:
        stats_by_source = {
            source: self.get_weekly_pattern_stats(
                pattern_name=pattern_name,
                asset_type=asset_type,
                sample_source=source,
                signal=signal,
            )
            for source in ("historical", "backfilled_replay", "live_paper_forward", "out_of_sample")
        }
        verdict = evaluate_weekly_pattern_evidence(
            stats_by_source=stats_by_source,
            settings=self.settings,
            asset_type=asset_type,
            signal=signal,
        )
        window = self._trust_window_bounds(observed_at=observed_at, horizon="1w")
        calibration_ready = (
            verdict.pattern_has_enough_historical_samples
            or verdict.pattern_has_enough_backfilled_replay_samples
        )
        passed = calibration_ready
        reason = verdict.summary
        if verdict.real_money_trust_blocked:
            reason = f"{reason} Real-money trust remains blocked."
        return EvidenceGateEvaluation(
            passed=passed,
            reason=reason,
            horizon="1w",
            evidence_basis=verdict.evidence_basis,
            trust_window_start=window.start,
            trust_window_end=window.end,
            signal_count=stats_by_source["historical"].sample_size + stats_by_source["backfilled_replay"].sample_size,
            signal_win_rate=stats_by_source["historical"].hit_rate_pct,
            signal_avg_return=stats_by_source["historical"].avg_forward_return_pct,
            score_band_count=stats_by_source["live_paper_forward"].sample_size,
            score_band_win_rate=stats_by_source["live_paper_forward"].hit_rate_pct,
            score_band_avg_return=stats_by_source["live_paper_forward"].avg_forward_return_pct,
            checks=list(verdict.checks),
            real_money_trust_blocked=verdict.real_money_trust_blocked,
        )

    def persist_weekly_backfill_outcomes(
        self,
        *,
        outcomes: list[dict],
    ) -> int:
        if not outcomes:
            return 0
        inserted = 0
        with SessionLocal() as session:
            for item in outcomes:
                session.add(
                    SignalOutcomeORM(
                        run_id=item["run_id"],
                        ticker=item["ticker"],
                        asset_type=item["asset_type"],
                        strategy_variant=item.get("strategy_variant", "layered-v4"),
                        signal=item["signal"],
                        confidence=item.get("confidence", 0.0),
                        calibrated_confidence=item.get("calibrated_confidence", 0.0),
                        calibration_source=item.get("calibration_source", "raw"),
                        raw_score=item.get("raw_score", 0.0),
                        score_band=item.get("score_band", "0-59"),
                        scoring_version=item.get("scoring_version", "weekly-pattern-v1"),
                        market_status=item.get("market_status"),
                        buy_score=item.get("buy_score", 0.0),
                        sell_score=item.get("sell_score", 0.0),
                        signal_label=item.get("signal_label", "watch"),
                        gate_passed=item.get("gate_passed", False),
                        gate_reason=item.get("gate_reason"),
                        data_grade=item.get("data_grade", "research"),
                        news_source=item.get("news_source", "skipped"),
                        relative_volume=item.get("relative_volume"),
                        price_change_pct=item.get("price_change_pct"),
                        relative_strength_pct=item.get("relative_strength_pct"),
                        options_flow_score=item.get("options_flow_score"),
                        options_flow_bullish=item.get("options_flow_bullish"),
                        volatility_regime=item.get("volatility_regime"),
                        data_quality=item.get("data_quality"),
                        benchmark_change_pct=item.get("benchmark_change_pct"),
                        entry_price=item["entry_price"],
                        generated_at=item["generated_at"],
                        price_after_1w=item.get("price_after_1w"),
                        return_after_1w=item.get("return_after_1w"),
                        evaluated_at_1w=item.get("evaluated_at_1w"),
                        status_1w=item.get("status_1w", "resolved"),
                        sample_source=item.get("sample_source", "backfilled_replay"),
                        pattern_name=item.get("pattern_name"),
                    )
                )
                inserted += 1
            session.commit()
        return inserted
