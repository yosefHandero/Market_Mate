from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, select

from app.brain.calibration import ReliabilityBin, reliability_map_from_payload
from app.db import SessionLocal, engine
from app.models.scan import WalkForwardPredictionORM, WalkForwardRunORM
from app.schemas import (
    WalkForwardAssetMetrics,
    WalkForwardBenchmark,
    WalkForwardCalibrationBucket,
    WalkForwardCoverageRow,
    WalkForwardPilotVerdict,
    WalkForwardRunSummary,
)


class WalkForwardRepository:
    """Persistence + read surface for historical walk-forward proof runs.

    Kept isolated from the live-forward ScanRepository so historical walk-forward
    evidence never mixes into live_paper_forward / out_of_sample live tracks.
    """

    def _tables_exist(self) -> bool:
        inspector = inspect(engine)
        names = set(inspector.get_table_names())
        if "walk_forward_runs" not in names or "walk_forward_predictions" not in names:
            return False
        run_columns = {column["name"] for column in inspector.get_columns("walk_forward_runs")}
        prediction_columns = {
            column["name"] for column in inspector.get_columns("walk_forward_predictions")
        }
        return {
            "policy_id",
            "policy_version",
            "decision_fingerprint",
            "learned_artifacts_fingerprint",
            "learned_artifacts_json",
        }.issubset(run_columns) and {
            "policy_id",
            "policy_version",
            "decision_fingerprint",
            "learned_artifacts_fingerprint",
        }.issubset(prediction_columns)

    def tables_ready(self) -> bool:
        return self._tables_exist()

    def persist_run(
        self,
        *,
        run_id: str,
        params: dict[str, Any],
        window_start: datetime | None,
        window_end: datetime | None,
        holdout_start: datetime | None,
        symbol_count: int,
        predictions: list[dict[str, Any]],
        metrics: dict[str, Any],
        verdict: dict[str, Any],
        coverage: list[dict[str, Any]],
        manifest: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        manifest = manifest or {}
        with SessionLocal() as session:
            # Deterministic run ids mean a rerun over identical stored bars reuses
            # the same id; replace any prior copy so reruns stay idempotent.
            session.query(WalkForwardPredictionORM).filter(
                WalkForwardPredictionORM.run_id == run_id
            ).delete(synchronize_session=False)
            session.query(WalkForwardRunORM).filter(
                WalkForwardRunORM.run_id == run_id
            ).delete(synchronize_session=False)
            session.add(
                WalkForwardRunORM(
                    run_id=run_id,
                    created_at=now,
                    status="complete",
                    params_json=json.dumps(params, default=str),
                    window_start=window_start,
                    window_end=window_end,
                    holdout_start=holdout_start,
                    validation_start=manifest.get("validation_start"),
                    symbol_count=symbol_count,
                    prediction_count=len(predictions),
                    metrics_json=json.dumps(metrics, default=str),
                    verdict_json=json.dumps(verdict, default=str),
                    coverage_json=json.dumps(coverage, default=str),
                    config_fingerprint=manifest.get("config_fingerprint"),
                    code_commit=manifest.get("code_commit"),
                    engine_version=manifest.get("engine_version"),
                    policy_id=manifest.get("policy_id"),
                    policy_version=manifest.get("policy_version"),
                    decision_fingerprint=manifest.get("decision_fingerprint"),
                    learned_artifacts_fingerprint=manifest.get("learned_artifacts_fingerprint"),
                    learned_artifacts_json=manifest.get("learned_artifacts_json"),
                    universe_json=json.dumps(manifest.get("universe") or [], default=str),
                    data_quality_json=json.dumps(
                        manifest.get("data_quality") or {}, default=str
                    ),
                )
            )
            for row in predictions:
                session.add(WalkForwardPredictionORM(run_id=run_id, **row))
            session.commit()

    def get_predictions(self, run_id: str) -> list[WalkForwardPredictionORM]:
        with SessionLocal() as session:
            return list(
                session.execute(
                    select(WalkForwardPredictionORM)
                    .where(WalkForwardPredictionORM.run_id == run_id)
                    .order_by(
                        WalkForwardPredictionORM.as_of.asc(),
                        WalkForwardPredictionORM.asset_type.asc(),
                        WalkForwardPredictionORM.selection_rank.asc(),
                    )
                ).scalars().all()
            )

    def get_latest_run(self) -> WalkForwardRunORM | None:
        if not self._tables_exist():
            return None
        with SessionLocal() as session:
            return session.execute(
                select(WalkForwardRunORM).order_by(WalkForwardRunORM.created_at.desc()).limit(1)
            ).scalars().first()

    def count_distinct_fingerprints(self) -> int:
        """Trials ledger: how many distinct configurations have been evaluated."""
        if not self._tables_exist():
            return 0
        with SessionLocal() as session:
            rows = session.execute(
                select(WalkForwardRunORM.config_fingerprint).distinct()
            ).scalars().all()
        return len([row for row in rows if row])

    def count_runs(self) -> int:
        if not self._tables_exist():
            return 0
        with SessionLocal() as session:
            return len(session.execute(select(WalkForwardRunORM.run_id)).scalars().all())

    def fingerprint_seen(self, fingerprint: str | None) -> bool:
        if not fingerprint or not self._tables_exist():
            return False
        with SessionLocal() as session:
            row = session.execute(
                select(WalkForwardRunORM.run_id)
                .where(WalkForwardRunORM.config_fingerprint == fingerprint)
                .limit(1)
            ).scalars().first()
        return row is not None

    def get_latest_reliability_map(
        self, asset_type: str, *, min_count: int = 0
    ) -> list[ReliabilityBin]:
        """Research-window reliability map for an asset from the latest proof run.

        Returns an empty list when no run exists or the run stored no map for the
        asset, so callers fall back to serving the raw probability unchanged.
        """
        run = self.get_latest_run()
        if run is None:
            return []
        metrics = _load_json(run.metrics_json)
        maps = metrics.get("reliability_maps") if isinstance(metrics, dict) else None
        if not isinstance(maps, dict):
            return []
        return reliability_map_from_payload(maps.get(asset_type), min_count=min_count)

    def get_latest_run_summary(self) -> WalkForwardRunSummary | None:
        run = self.get_latest_run()
        if run is None:
            return None
        return self.build_summary_from_run(run)

    def get_latest_applicable_run_summary(
        self,
        *,
        policy_id: str,
        policy_version: str,
        decision_fingerprint: str,
        learned_artifacts_fingerprint: str | None = None,
    ) -> WalkForwardRunSummary | None:
        if not self._tables_exist():
            return None
        columns = {column["name"] for column in inspect(engine).get_columns("walk_forward_runs")}
        required = {
            "policy_id",
            "policy_version",
            "decision_fingerprint",
            "learned_artifacts_fingerprint",
        }
        if not required.issubset(columns):
            return None
        with SessionLocal() as session:
            query = (
                select(WalkForwardRunORM)
                .where(WalkForwardRunORM.policy_id == policy_id)
                .where(WalkForwardRunORM.policy_version == policy_version)
                .where(WalkForwardRunORM.decision_fingerprint == decision_fingerprint)
                .order_by(WalkForwardRunORM.created_at.desc())
                .limit(1)
            )
            if learned_artifacts_fingerprint is not None:
                query = query.where(
                    WalkForwardRunORM.learned_artifacts_fingerprint
                    == learned_artifacts_fingerprint
                )
            run = session.execute(query).scalars().first()
        if run is None:
            return None
        return self.build_summary_from_run(run)

    def build_summary_from_run(self, run: WalkForwardRunORM) -> WalkForwardRunSummary:
        metrics = _load_json(run.metrics_json)
        verdict = _load_json(run.verdict_json)
        coverage = _load_json(run.coverage_json)
        params = _load_json(run.params_json)
        by_asset_track = [
            WalkForwardAssetMetrics.model_validate(item)
            for item in (metrics.get("by_asset_track") or [])
        ]
        calibration_buckets = [
            WalkForwardCalibrationBucket.model_validate(item)
            for item in (metrics.get("calibration_buckets") or [])
        ]
        benchmarks = [
            WalkForwardBenchmark.model_validate(item)
            for item in (metrics.get("benchmarks") or [])
        ]
        coverage_rows = [
            WalkForwardCoverageRow.model_validate(item)
            for item in (coverage if isinstance(coverage, list) else [])
        ]
        pilot = (
            WalkForwardPilotVerdict.model_validate(verdict)
            if verdict
            else WalkForwardPilotVerdict()
        )
        created_at = run.created_at
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        data_quality = _load_json(getattr(run, "data_quality_json", None))
        universe = _load_json(getattr(run, "universe_json", None))
        if not isinstance(universe, list):
            universe = []
        return WalkForwardRunSummary(
            run_id=run.run_id,
            created_at=created_at or datetime.now(timezone.utc),
            window_start=run.window_start,
            window_end=run.window_end,
            holdout_start=run.holdout_start,
            validation_start=getattr(run, "validation_start", None),
            target_years=int(params.get("target_years", 3) or 3),
            step_days=int(params.get("step_days", 7) or 7),
            forward_days=int(params.get("forward_days", 7) or 7),
            top_n_per_asset=int(params.get("top_n_per_asset", 5) or 5),
            symbol_count=int(run.symbol_count or 0),
            prediction_count=int(run.prediction_count or 0),
            resolved_count=int(metrics.get("resolved_count", 0) or 0),
            pending_count=int(metrics.get("pending_count", 0) or 0),
            by_asset_track=by_asset_track,
            calibration_buckets=calibration_buckets,
            benchmarks=benchmarks,
            coverage=coverage_rows,
            pilot_verdict=pilot,
            config_fingerprint=getattr(run, "config_fingerprint", None),
            code_commit=getattr(run, "code_commit", None),
            engine_version=getattr(run, "engine_version", None),
            policy_id=getattr(run, "policy_id", None),
            policy_version=getattr(run, "policy_version", None),
            decision_fingerprint=getattr(run, "decision_fingerprint", None),
            learned_artifacts_fingerprint=getattr(run, "learned_artifacts_fingerprint", None),
            ruler_version=params.get("ruler_version"),
            ruler_fingerprint=params.get("ruler_fingerprint"),
            universe=[str(sym) for sym in universe],
            universe_source=str(params.get("universe_source") or "current_watchlist"),
            data_quality_ok=(
                bool(data_quality.get("ok")) if isinstance(data_quality, dict) and data_quality else None
            ),
            data_quality_issues=(
                [str(item) for item in data_quality.get("issues", [])]
                if isinstance(data_quality, dict)
                else []
            ),
            overlap_status=str(params.get("overlap_status") or "") or None,
            note=metrics.get("note"),
        )


def _load_json(value: str | None) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}
