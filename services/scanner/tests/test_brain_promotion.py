"""Promotion gates, the champion switch, and shadow persistence.

A challenger becomes champion only through the promotion report: walk-forward
holdout (when replayable) plus a paired live-shadow comparison whose interval
clearly favors it, with calibration not significantly worse. The host applies
a requested non-default champion only when that report clears, and shadow
decisions never leak into production readiness surfaces.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.services.repository as repository_module
from app.brain.contracts import BrainDecision, EvidenceBasis, ExitPlan
from app.brain.evaluation.paired import PairedOutcome
from app.brain.evaluation.promotion import build_promotion_report
from app.brain.identity import RULER_VERSION, learned_artifact_identity
from app.config import Settings
from app.db import Base
from app.models.scan import EvidenceCampaignORM, PredictionSnapshotORM
from app.schemas import ScanResult, ScanRun, WeeklyPatternPrediction
from app.services.brain_runtime import BrainRuntime
from app.services.learned_inputs import LearnedInputBundle
from app.services.repository import ScanRepository


def _superior_pairs(n: int = 50) -> list[PairedOutcome]:
    return [
        PairedOutcome(
            key=f"scan-{i}",
            champion_return_pct=0.0,
            challenger_return_pct=1.0,
            resolution_week=f"2024-W{(i // 5) + 1:02d}",
        )
        for i in range(n)
    ]


def _report(**overrides):
    kwargs = dict(
        champion_policy_id="hybrid_legacy",
        challenger_policy_id="weekly_probability",
        challenger_replayable=True,
        champion_decision_fingerprint="fp-champion",
        challenger_decision_fingerprint="fp-challenger",
        ruler_config_payload={"promotion_min_pairs": 40},
        walk_forward_holdout_passed=True,
        return_pairs=_superior_pairs(),
        brier_pairs=None,
        min_pairs=40,
    )
    kwargs.update(overrides)
    return build_promotion_report(**kwargs)


class PromotionReportGateTests(unittest.TestCase):
    def test_all_gates_green_clears(self) -> None:
        report = _report()
        self.assertTrue(report.gates_cleared)
        self.assertEqual(
            [check.name for check in report.checks],
            [
                "walk_forward_holdout",
                "paired_live_shadow_returns",
                "paired_calibration_not_worse",
            ],
        )

    def test_wf_holdout_failure_blocks_replayable_challenger(self) -> None:
        report = _report(walk_forward_holdout_passed=False)
        self.assertFalse(report.gates_cleared)
        wf_check = next(c for c in report.checks if c.name == "walk_forward_holdout")
        self.assertFalse(wf_check.passed)

    def test_non_replayable_challenger_skips_wf_gate(self) -> None:
        report = _report(challenger_replayable=False, walk_forward_holdout_passed=False)
        wf_check = next(c for c in report.checks if c.name == "walk_forward_holdout")
        self.assertTrue(wf_check.passed)
        self.assertTrue(report.gates_cleared)

    def test_insufficient_pairs_never_clears(self) -> None:
        report = _report(return_pairs=_superior_pairs(10))
        self.assertFalse(report.gates_cleared)
        self.assertFalse(report.paired_returns.sufficient_pairs)

    def test_significantly_worse_calibration_blocks(self) -> None:
        # Stored as negated Brier (higher is better): the challenger is
        # consistently worse calibrated even though its returns are superior.
        worse_brier = [
            PairedOutcome(
                key=f"b-{i}",
                champion_return_pct=-9.0,
                challenger_return_pct=-25.0,
                resolution_week=f"2024-W{(i // 5) + 1:02d}",
            )
            for i in range(50)
        ]
        report = _report(brier_pairs=worse_brier)
        self.assertFalse(report.gates_cleared)
        calibration = next(
            c for c in report.checks if c.name == "paired_calibration_not_worse"
        )
        self.assertFalse(calibration.passed)

    def test_same_week_duplicate_calibration_observations_do_not_false_block(self) -> None:
        worse_brier = [
            PairedOutcome(
                key=f"b-{i}",
                champion_return_pct=-9.0,
                challenger_return_pct=-25.0,
                resolution_week="2024-W01",
            )
            for i in range(50)
        ]
        report = _report(brier_pairs=worse_brier)
        calibration = next(
            c for c in report.checks if c.name == "paired_calibration_not_worse"
        )
        self.assertTrue(calibration.passed)
        self.assertEqual(report.paired_brier.n_resolution_clusters, 1)
        self.assertFalse(report.paired_brier.challenger_inferior)

    def test_report_stamps_ruler_and_decision_identities(self) -> None:
        report = _report()
        self.assertEqual(report.ruler_version, RULER_VERSION)
        self.assertTrue(report.ruler_fingerprint)
        self.assertEqual(report.champion_decision_fingerprint, "fp-champion")
        self.assertEqual(report.challenger_decision_fingerprint, "fp-challenger")


def _runtime(*, requested: str, wf_ready: bool, pairs: dict) -> BrainRuntime:
    settings = Settings(_env_file=None, brain_champion_policy_id=requested)
    repository = SimpleNamespace(
        list_paired_policy_outcomes=lambda **kwargs: pairs,
        get_weekly_pattern_stats=lambda **kwargs: None,
    )
    walk_forward = SimpleNamespace(
        get_latest_applicable_run_summary=lambda **kwargs: SimpleNamespace(
            pilot_verdict=SimpleNamespace(ready=wf_ready)
        )
    )
    runtime = BrainRuntime(
        settings=settings,
        repository=repository,  # type: ignore[arg-type]
        walk_forward_repository=walk_forward,  # type: ignore[arg-type]
    )
    runtime.refresh_weekly_inputs(
        LearnedInputBundle(
            reliability_maps={},
            extra_stats={},
            identity=learned_artifact_identity(
                artifact_type="weekly_probability_inputs",
                content_payload={"reliability_maps": {}, "pattern_stats": []},
            ),
        )
    )
    return runtime


_GREEN_PAIRS = {"returns": _superior_pairs(), "brier": []}


class ChampionSwitchTests(unittest.TestCase):
    def test_default_champion_is_hybrid(self) -> None:
        runtime = _runtime(
            requested="hybrid_legacy",
            wf_ready=False,
            pairs={"returns": [], "brier": []},
        )
        self.assertEqual(runtime.effective_champion_id(), "hybrid_legacy")

    def test_weekly_takes_effect_only_when_gates_clear(self) -> None:
        runtime = _runtime(requested="weekly_probability", wf_ready=True, pairs=_GREEN_PAIRS)
        self.assertEqual(runtime.effective_champion_id(), "weekly_probability")

    def test_weekly_request_without_pairs_stays_hybrid(self) -> None:
        runtime = _runtime(
            requested="weekly_probability",
            wf_ready=True,
            pairs={"returns": _superior_pairs(5), "brier": []},
        )
        self.assertEqual(runtime.effective_champion_id(), "hybrid_legacy")

    def test_weekly_request_without_wf_holdout_stays_hybrid(self) -> None:
        runtime = _runtime(requested="weekly_probability", wf_ready=False, pairs=_GREEN_PAIRS)
        self.assertEqual(runtime.effective_champion_id(), "hybrid_legacy")

    def test_unknown_policy_request_falls_back_to_hybrid(self) -> None:
        runtime = _runtime(requested="quantum_oracle", wf_ready=True, pairs=_GREEN_PAIRS)
        self.assertEqual(runtime.effective_champion_id(), "hybrid_legacy")

    def test_promotion_report_response_exposes_effective_vs_requested(self) -> None:
        runtime = _runtime(
            requested="weekly_probability",
            wf_ready=True,
            pairs={"returns": _superior_pairs(5), "brier": []},
        )
        response = runtime.promotion_report_response()
        self.assertEqual(response.requested_champion_policy_id, "weekly_probability")
        self.assertEqual(response.effective_champion_policy_id, "hybrid_legacy")
        self.assertFalse(response.gates_cleared)
        self.assertEqual(response.ruler_version, RULER_VERSION)
        self.assertTrue(response.ruler_fingerprint)
        self.assertEqual(response.paired_returns_resolution_clusters, 1)
        self.assertTrue(response.paired_returns_cluster_metadata_complete)


def _scan_result(*, created_at: datetime) -> ScanResult:
    return ScanResult(
        ticker="AAPL",
        asset_type="stock",
        strategy_variant="layered-v4",
        score=82.0,
        raw_score=82.0,
        calibrated_confidence=82.0,
        calibration_source="signal",
        confidence_label="calibrated_confidence",
        strategy_id="scanner-directional",
        strategy_version="v4.0-layered",
        strategy_primary_horizon="1h",
        strategy_entry_assumption="trend",
        strategy_exit_assumption="flip",
        evidence_quality="high",
        evidence_quality_score=0.8,
        evidence_quality_reasons=[],
        execution_eligibility="eligible",
        buy_score=84.0,
        sell_score=10.0,
        decision_signal="BUY",
        scoring_version="v4.2-budget-normalized",
        explanation="Strong setup.",
        price=200.0,
        price_change_pct=3.2,
        relative_volume=1.8,
        sentiment_score=0.4,
        filing_flag=False,
        breakout_flag=True,
        market_status="bullish",
        sector_strength_score=0.6,
        relative_strength_pct=2.1,
        options_flow_score=67.0,
        options_flow_summary="Bullish flow.",
        options_flow_bullish=True,
        options_call_put_ratio=1.3,
        alert_sent=False,
        news_checked=True,
        news_source="marketaux",
        news_cache_label="fresh",
        signal_label="strong",
        data_quality="ok",
        volatility_regime="normal",
        benchmark_ticker="SPY",
        benchmark_change_pct=1.1,
        gate_passed=True,
        gate_reason="Eligible.",
        gate_checks=[],
        coingecko_price_change_pct_24h=None,
        coingecko_market_cap_rank=None,
        fear_greed_value=None,
        fear_greed_label=None,
        provider_status="ok",
        provider_warnings=[],
        layer_details={},
        is_top_pick=True,
        selection_rank=1,
        readiness_score=82.0,
        readiness_band="high",
        readiness_hard_stop=False,
        readiness_reason="Actionable: gates passed and data is fresh.",
        recommended_action="dry_run",
        created_at=created_at,
        weekly_prediction=WeeklyPatternPrediction(
            pattern_name="uptrend_ma_stack",
            directional_bias="bullish",
            range_low=194.0,
            range_high=212.0,
            upside_probability_pct=64.0,
            historical_hit_rate_pct=61.0,
            avg_forward_1w_return_pct=1.4,
            sample_size=48,
            data_quality="ok",
            evidence_basis="historical_only",
        ),
    )


def _shadow_decision(*, as_of: datetime, action: str = "BUY") -> BrainDecision:
    return BrainDecision(
        policy_id="weekly_probability",
        policy_version="weekly-prob-v1",
        decision_fingerprint="fp-weekly",
        symbol="AAPL",
        asset_type="stock",
        as_of=as_of,
        action=action,  # type: ignore[arg-type]
        p_up_calibrated=61.5 if action == "BUY" else None,
        expected_value_pct=1.2 if action == "BUY" else None,
        exit_plan=(
            ExitPlan(entry_price=200.0, target_price=210.0, stop_price=195.0, horizon_days=7)
            if action == "BUY"
            else None
        ),
        evidence_basis=EvidenceBasis(),
        reasons=() if action == "BUY" else ("wilson_lb_below_floor",),
        pattern_name="uptrend_ma_stack",
    )


class ShadowPersistenceTests(unittest.TestCase):
    def _build_session_local(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_path = Path(temp_dir.name) / "scanner.db"
        engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        self.addCleanup(engine.dispose)
        SessionLocal = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        Base.metadata.create_all(engine)
        # Campaign provenance binds to the app database at import time; drop
        # the campaigns table so save_run cleanly skips provenance here.
        EvidenceCampaignORM.__table__.drop(engine)
        return engine, SessionLocal

    def _save_run_with_shadow(self, SessionLocal) -> ScanRun:
        created_at = datetime.now(timezone.utc)
        run = ScanRun(
            run_id="run-shadow-1",
            created_at=created_at,
            market_status="bullish",
            strategy_variant="layered-v4",
            scan_count=1,
            watchlist_size=1,
            alerts_sent=0,
            fear_greed_value=60,
            fear_greed_label="Greed",
            results=[_scan_result(created_at=created_at)],
        )
        repo = ScanRepository()
        with patch.object(repository_module, "SessionLocal", SessionLocal):
            repo.save_run(
                run,
                shadow_decisions=[_shadow_decision(as_of=created_at)],
                champion_policy_id="hybrid_legacy",
                champion_fingerprint="fp-hybrid",
                champion_policy_version="hybrid-v4.2",
                learned_artifacts_fingerprint="artifact-weekly-1",
            )
        return run

    def test_shadow_decisions_persist_separately_from_production(self) -> None:
        _, SessionLocal = self._build_session_local()
        self._save_run_with_shadow(SessionLocal)
        with SessionLocal() as session:
            rows = session.execute(select(PredictionSnapshotORM)).scalars().all()
        by_role = {row.decision_role: row for row in rows}
        self.assertEqual(set(by_role), {"production", "shadow"})
        production = by_role["production"]
        self.assertEqual(production.policy_id, "hybrid_legacy")
        self.assertEqual(production.decision_fingerprint, "fp-hybrid")
        self.assertEqual(production.learned_artifacts_fingerprint, "artifact-weekly-1")
        shadow = by_role["shadow"]
        self.assertEqual(shadow.policy_id, "weekly_probability")
        self.assertEqual(shadow.decision_fingerprint, "fp-weekly")
        self.assertEqual(shadow.learned_artifacts_fingerprint, "artifact-weekly-1")
        self.assertEqual(shadow.status, "pending")
        self.assertEqual(shadow.range_low, 195.0)
        self.assertEqual(shadow.range_high, 210.0)

    def test_shadow_rows_are_excluded_from_production_accuracy(self) -> None:
        _, SessionLocal = self._build_session_local()
        self._save_run_with_shadow(SessionLocal)
        repo = ScanRepository()
        with patch.object(repository_module, "SessionLocal", SessionLocal):
            metrics = repo.get_prediction_accuracy_summary()
        # Only the production snapshot counts; the shadow BUY stays out.
        self.assertEqual(metrics.pending_count, 1)

    def test_resolved_shadow_and_production_rows_pair_up(self) -> None:
        _, SessionLocal = self._build_session_local()
        run = self._save_run_with_shadow(SessionLocal)
        with SessionLocal() as session:
            rows = session.execute(select(PredictionSnapshotORM)).scalars().all()
            for row in rows:
                row.status = "resolved"
                row.price_at_horizon = 206.0
                row.hold_return_pct = 3.0
                row.evaluated_at = run.created_at + timedelta(days=7)
            session.commit()
        repo = ScanRepository()
        with patch.object(repository_module, "SessionLocal", SessionLocal):
            pairs = repo.list_paired_policy_outcomes(
                champion_policy_id="hybrid_legacy",
                challenger_policy_id="weekly_probability",
            )
        self.assertEqual(len(pairs["returns"]), 1)
        pair = pairs["returns"][0]
        self.assertIsNotNone(pair.champion_return_pct)
        self.assertIsNotNone(pair.challenger_return_pct)
        self.assertEqual(pair.key, f"{run.run_id}:AAPL")
        self.assertIsNotNone(pair.resolution_week)
        self.assertIsNotNone(pairs["brier"][0].resolution_week)

    def test_incompatible_or_ambiguous_rows_are_excluded_from_identity_specific_pairs(self) -> None:
        _, SessionLocal = self._build_session_local()
        run = self._save_run_with_shadow(SessionLocal)
        with SessionLocal() as session:
            rows = session.execute(select(PredictionSnapshotORM)).scalars().all()
            for row in rows:
                row.status = "resolved"
                row.price_at_horizon = 206.0
                row.hold_return_pct = 3.0
                row.evaluated_at = run.created_at + timedelta(days=7)
            shadow = next(row for row in rows if row.decision_role == "shadow")
            shadow.decision_fingerprint = "old-weekly-fingerprint"
            session.add(
                PredictionSnapshotORM(
                    run_id="legacy-run",
                    ticker="AAPL",
                    asset_type="stock",
                    signal="BUY",
                    evidence_grade="Weak",
                    entry_price=200.0,
                    range_low=195.0,
                    range_high=210.0,
                    horizon="1w",
                    invalidation="",
                    methodology="pattern_recognition",
                    generated_at=run.created_at,
                    status="resolved",
                    price_at_horizon=206.0,
                    hold_return_pct=3.0,
                    evaluated_at=run.created_at + timedelta(days=7),
                )
            )
            session.commit()

        repo = ScanRepository()
        with patch.object(repository_module, "SessionLocal", SessionLocal):
            pairs = repo.list_paired_policy_outcomes(
                champion_policy_id="hybrid_legacy",
                champion_policy_version="hybrid-v4.2",
                champion_decision_fingerprint="fp-hybrid",
                challenger_policy_id="weekly_probability",
                challenger_policy_version="weekly-prob-v1",
                challenger_decision_fingerprint="fp-weekly",
            )

        self.assertEqual(pairs["returns"], [])
        self.assertEqual(
            pairs["exclusions"].get("weekly_probability_fingerprint_mismatch"),
            1,
        )
        self.assertEqual(pairs["exclusions"].get("ambiguous_legacy_or_null_policy"), 1)
        with SessionLocal() as session:
            unchanged = session.execute(
                select(PredictionSnapshotORM).where(
                    PredictionSnapshotORM.policy_id == "weekly_probability"
                )
            ).scalar_one()
        self.assertEqual(unchanged.decision_fingerprint, "old-weekly-fingerprint")

    def test_learned_artifact_mismatch_is_excluded_even_when_policy_fingerprint_matches(self) -> None:
        _, SessionLocal = self._build_session_local()
        run = self._save_run_with_shadow(SessionLocal)
        with SessionLocal() as session:
            rows = session.execute(select(PredictionSnapshotORM)).scalars().all()
            for row in rows:
                row.status = "resolved"
                row.price_at_horizon = 206.0
                row.hold_return_pct = 3.0
                row.evaluated_at = run.created_at + timedelta(days=7)
            shadow = next(row for row in rows if row.decision_role == "shadow")
            shadow.learned_artifacts_fingerprint = "artifact-old"
            session.commit()

        repo = ScanRepository()
        with patch.object(repository_module, "SessionLocal", SessionLocal):
            pairs = repo.list_paired_policy_outcomes(
                champion_policy_id="hybrid_legacy",
                champion_policy_version="hybrid-v4.2",
                champion_decision_fingerprint="fp-hybrid",
                champion_learned_artifacts_fingerprint="artifact-weekly-1",
                challenger_policy_id="weekly_probability",
                challenger_policy_version="weekly-prob-v1",
                challenger_decision_fingerprint="fp-weekly",
                challenger_learned_artifacts_fingerprint="artifact-weekly-1",
            )

        self.assertEqual(pairs["returns"], [])
        self.assertEqual(
            pairs["exclusions"].get("weekly_probability_learned_artifact_mismatch"),
            1,
        )


if __name__ == "__main__":
    unittest.main()
