from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import Base
from app.services.historical_bar_store import BarCoverage
from app.services.repository import ScanRepository
from app.services.walk_forward_proof import (
    WalkForwardProofService,
    _benchmark_regime,
    _candidate_filter_diagnostic_rows,
    _max_drawdown_pct,
    _rejection_diagnostic_rows,
    _selection_stage_diagnostic_rows,
    _spearman_ic,
    _wilson_lower_bound_pct,
    _worst_decile_mean,
)
from app.services.walk_forward_repository import WalkForwardRepository


def make_uptrend_bars(
    *,
    count: int,
    last_day: datetime,
    start_price: float = 100.0,
    daily_drift: float = 0.4,
) -> list[dict]:
    """Deterministic gently-rising daily series so a bullish BUY pattern is detected."""
    bars: list[dict] = []
    for offset in reversed(range(count)):
        day = last_day - timedelta(days=offset)
        index = count - 1 - offset
        close = start_price + daily_drift * index
        bars.append(
            {
                "t": day.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                "o": round(close - 0.2, 4),
                "h": round(close + 0.6, 4),
                "l": round(close - 0.6, 4),
                "c": round(close, 4),
                "v": 1000,
            }
        )
    return bars


def proof_settings(**overrides) -> Settings:
    base = dict(
        proof_lookback_context_months_min=2,
        proof_lookback_context_months_max=24,
        proof_min_pattern_samples=3,
        proof_holdout_months=3,
        proof_step_days=14,
        weekly_forward_days=7,
        weekly_forward_tolerance_days=3,
        weekly_daily_lookback_bars_min=60,
        weekly_daily_lookback_bars_preferred=120,
        # Relax RSI/pattern-edge gates so the deterministic monotonic test series
        # still yields candidates; dedicated tests below exercise those filters.
        proof_rsi_overbought=101.0,
        proof_min_pattern_edge_pct=0.0,
        proof_require_buy_hold_baseline=False,
    )
    base.update(overrides)
    return Settings(**base)


class FakeBarStore:
    def __init__(self, bars_by_symbol: dict[str, list[dict]]) -> None:
        self._bars = bars_by_symbol

    @staticmethod
    def resolve_asset_type(symbol: str, asset_type: str | None = None) -> str:
        return asset_type or ("crypto" if "/" in symbol else "stock")

    async def ensure_history(self, symbol, *, asset_type=None, years=None, force_refresh=False) -> BarCoverage:
        resolved = self.resolve_asset_type(symbol, asset_type)
        bars = self._bars.get(symbol.upper(), [])
        return BarCoverage(
            symbol=symbol.upper(),
            asset_type=resolved,
            bar_count=len(bars),
            first_date=bars[0]["t"][:10] if bars else None,
            last_date=bars[-1]["t"][:10] if bars else None,
            years_available=float(years or 2),
            source="cache",
            sufficient=bool(bars),
        )

    def load_bars(self, symbol, *, asset_type=None) -> list[dict]:
        return list(self._bars.get(symbol.upper(), []))


class DateSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WalkForwardProofService(
            settings=proof_settings(), scan_repository=ScanRepository()
        )

    def test_select_replay_dates_weekly_grid(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 3, 1, tzinfo=timezone.utc)
        dates = self.service.select_replay_dates(window_start=start, window_end=end, step_days=7)
        self.assertGreater(len(dates), 1)
        self.assertEqual(dates[0], start)
        self.assertEqual((dates[1] - dates[0]).days, 7)
        self.assertTrue(all(d <= end for d in dates))

    def test_track_split_at_holdout_boundary(self) -> None:
        holdout = datetime(2026, 1, 1, tzinfo=timezone.utc)
        validation = datetime(2025, 10, 1, tzinfo=timezone.utc)
        self.assertEqual(
            self.service._track_for(
                datetime(2025, 6, 1, tzinfo=timezone.utc), holdout, validation
            ),
            "historical",
        )
        self.assertEqual(
            self.service._track_for(
                datetime(2025, 11, 1, tzinfo=timezone.utc), holdout, validation
            ),
            "validation",
        )
        self.assertEqual(
            self.service._track_for(
                datetime(2026, 2, 1, tzinfo=timezone.utc), holdout, validation
            ),
            "out_of_sample",
        )


class NoLookaheadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WalkForwardProofService(
            settings=proof_settings(), scan_repository=ScanRepository()
        )

    def test_prediction_ignores_future_bars(self) -> None:
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        full = make_uptrend_bars(count=400, last_day=last_day)
        as_of = datetime(2025, 7, 1, tzinfo=timezone.utc)
        truncated = [b for b in full if datetime.fromisoformat(b["t"]) <= as_of]

        with_future = self.service.build_prediction_at(
            symbol="AAA", asset_type="stock", bars=full, as_of=as_of
        )
        without_future = self.service.build_prediction_at(
            symbol="AAA", asset_type="stock", bars=truncated, as_of=as_of
        )
        self.assertIsNotNone(with_future)
        self.assertIsNotNone(without_future)
        # Appending real future bars must not change the point-in-time prediction.
        for key in (
            "pattern_name",
            "confidence",
            "upside_probability_pct",
            "historical_hit_rate_pct",
            "sample_size",
            "entry_price",
            "projected_range_low",
            "projected_range_high",
            "estimated_exit_price",
        ):
            self.assertEqual(with_future[key], without_future[key], msg=key)

    def test_insufficient_context_returns_none(self) -> None:
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        short = make_uptrend_bars(count=30, last_day=last_day)
        result = self.service.build_prediction_at(
            symbol="AAA", asset_type="stock", bars=short, as_of=last_day
        )
        self.assertIsNone(result)


class ResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WalkForwardProofService(
            settings=proof_settings(), scan_repository=ScanRepository()
        )

    def test_resolution_sets_forward_return_and_range(self) -> None:
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = make_uptrend_bars(count=400, last_day=last_day)
        as_of = datetime(2025, 7, 1, tzinfo=timezone.utc)
        prediction = self.service.build_prediction_at(
            symbol="AAA", asset_type="stock", bars=bars, as_of=as_of
        )
        self.assertIsNotNone(prediction)
        resolved = self.service.resolve_prediction(prediction, bars=bars)
        self.assertEqual(resolved["status"], "resolved")
        self.assertIsNotNone(resolved["price_after_1w"])
        # Rising series => positive 1-week forward return for a BUY.
        self.assertGreater(resolved["return_after_1w"], 0)
        self.assertIn(resolved["accuracy_outcome"], {"in_range", "above_range", "below_range"})
        self.assertEqual(resolved["exit_window_status"], "resolved")


class SelectionTests(unittest.TestCase):
    def test_run_selects_top_n_per_asset_separately(self) -> None:
        last_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        bars = {
            "AAA": make_uptrend_bars(count=760, last_day=last_day, daily_drift=0.5),
            "BBB": make_uptrend_bars(count=760, last_day=last_day, daily_drift=0.3),
            "CCC/USD": make_uptrend_bars(count=760, last_day=last_day, daily_drift=0.4),
        }
        service = WalkForwardProofService(
            settings=proof_settings(),
            bar_store=FakeBarStore(bars),
            scan_repository=ScanRepository(),
        )

        async def run():
            return await service.run(
                symbols=["AAA", "BBB", "CCC/USD"],
                years=2,
                step_days=14,
                top_n_per_asset=3,
                persist=False,
            )

        run_id, summary = asyncio.run(run())
        self.assertTrue(run_id.startswith("wf-"))
        self.assertGreater(summary["prediction_count"], 0)

        # Group by (as_of, asset_type) and verify per-date top-N cap and contiguous ranks.
        # Reconstruct from the persisted-shape prediction rows via a fresh run capture.
        # Here we assert asset separation and rank bounds from the metric rows instead.
        tracks = {(row["asset_type"], row["track"]) for row in summary["by_asset_track"]}
        asset_types = {asset for asset, _ in tracks}
        self.assertIn("stock", asset_types)
        self.assertIn("crypto", asset_types)
        self.assertLessEqual(summary["top_n_per_asset"], 5)
        self.assertGreaterEqual(summary["top_n_per_asset"], 3)

    def test_run_ranks_and_caps_per_date(self) -> None:
        last_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        # Four stock symbols, top_n=3 => at most 3 per date.
        bars = {
            sym: make_uptrend_bars(count=760, last_day=last_day, daily_drift=drift)
            for sym, drift in (("AAA", 0.6), ("BBB", 0.5), ("CCC", 0.4), ("DDD", 0.3))
        }
        service = WalkForwardProofService(
            settings=proof_settings(),
            bar_store=FakeBarStore(bars),
            scan_repository=ScanRepository(),
        )
        captured: dict = {}
        real_metrics = service.compute_metrics

        def capture(predictions, **kwargs):
            captured["predictions"] = predictions
            return real_metrics(predictions, **kwargs)

        with patch.object(service, "compute_metrics", side_effect=capture):
            asyncio.run(
                service.run(
                    symbols=list(bars.keys()),
                    years=2,
                    step_days=28,
                    top_n_per_asset=3,
                    persist=False,
                )
            )
        predictions = captured["predictions"]
        by_date: dict = {}
        for prediction in predictions:
            by_date.setdefault((prediction["as_of"], prediction["asset_type"]), []).append(prediction)
        for rows in by_date.values():
            self.assertLessEqual(len(rows), 3)
            ranks = sorted(r["selection_rank"] for r in rows)
            self.assertEqual(ranks, list(range(1, len(rows) + 1)))
            ranked = sorted(rows, key=lambda r: r["selection_rank"])
            probs = [r["upside_probability_pct"] or 0.0 for r in ranked]
            self.assertEqual(probs, sorted(probs, reverse=True))


class CandidateFilterDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WalkForwardProofService(
            settings=proof_settings(), scan_repository=ScanRepository()
        )

    def _row(
        self,
        rows: list[dict],
        *,
        reject_reason: str,
        track: str = "research",
        pattern_name: str | None = None,
    ) -> dict:
        return next(
            row
            for row in rows
            if row["track"] == track
            and row["reject_reason"] == reject_reason
            and (pattern_name is None or row["pattern_name"] == pattern_name)
        )

    def _selection_row(
        self,
        rows: list[dict],
        *,
        selection_stage: str,
        track: str = "research",
        pattern_name: str | None = None,
    ) -> dict:
        return next(
            row
            for row in rows
            if row["track"] == track
            and row["selection_stage"] == selection_stage
            and (pattern_name is None or row["pattern_name"] == pattern_name)
        )

    def test_rejected_candidates_contribute_to_candidate_filter_diagnostics(self) -> None:
        tracker: dict[tuple[str, str, str, str], dict] = {}
        service = WalkForwardProofService(
            settings=proof_settings(proof_rsi_overbought=80.0),
            scan_repository=ScanRepository(),
        )
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        as_of = datetime(2025, 7, 1, tzinfo=timezone.utc)
        result = service.build_prediction_at(
            symbol="AAA",
            asset_type="stock",
            bars=make_uptrend_bars(count=400, last_day=last_day, daily_drift=0.4),
            market_bars=make_uptrend_bars(count=400, last_day=last_day, daily_drift=0.1),
            as_of=as_of,
            sample_source="historical",
            candidate_filter_tracker=tracker,
        )

        self.assertIsNone(result)
        row = self._row(
            _candidate_filter_diagnostic_rows(tracker),
            reject_reason="rsi_overbought",
        )
        self.assertEqual(row["sample_count"], 1)
        self.assertEqual(row["resolved_count"], 1)
        self.assertEqual(row["hit_rate_pct"], 100.0)
        self.assertIsNotNone(row["avg_return_after_friction_pct"])
        self.assertIsNotNone(row["avg_return_after_friction_stressed_pct"])
        self.assertIsNotNone(row["edge_vs_benchmark_pct"])

    def test_rejected_candidates_contribute_to_selection_stage_diagnostics(self) -> None:
        tracker: dict[tuple[str, str, str, str], dict] = {}
        service = WalkForwardProofService(
            settings=proof_settings(proof_rsi_overbought=80.0),
            scan_repository=ScanRepository(),
        )
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = service.build_prediction_at(
            symbol="AAA",
            asset_type="stock",
            bars=make_uptrend_bars(count=400, last_day=last_day),
            as_of=datetime(2025, 7, 1, tzinfo=timezone.utc),
            sample_source="historical",
            selection_stage_tracker=tracker,
        )

        self.assertIsNone(result)
        row = self._selection_row(
            _selection_stage_diagnostic_rows(tracker),
            selection_stage="rejected",
        )
        self.assertEqual(row["sample_count"], 1)
        self.assertEqual(row["resolved_count"], 1)
        self.assertEqual(row["hit_rate_pct"], 100.0)
        self.assertIsNotNone(row["avg_return_after_friction_stressed_pct"])

    def test_accepted_candidates_use_accepted_reject_reason(self) -> None:
        tracker: dict[tuple[str, str, str, str], dict] = {}
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = self.service.build_prediction_at(
            symbol="AAA",
            asset_type="stock",
            bars=make_uptrend_bars(count=400, last_day=last_day),
            as_of=datetime(2025, 7, 1, tzinfo=timezone.utc),
            sample_source="historical",
            candidate_filter_tracker=tracker,
        )

        self.assertIsNotNone(result)
        row = self._row(
            _candidate_filter_diagnostic_rows(tracker),
            reject_reason="accepted",
        )
        self.assertEqual(row["sample_count"], 1)
        self.assertEqual(row["resolved_count"], 1)
        self.assertEqual(row["hit_rate_pct"], 100.0)

    def test_accepted_but_not_top_n_candidates_are_included(self) -> None:
        last_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        bars = {
            sym: make_uptrend_bars(count=760, last_day=last_day, daily_drift=drift)
            for sym, drift in (
                ("AAA", 0.6),
                ("BBB", 0.5),
                ("CCC", 0.4),
                ("DDD", 0.3),
                ("SPY", 0.2),
            )
        }
        service = WalkForwardProofService(
            settings=proof_settings(),
            bar_store=FakeBarStore(bars),
            scan_repository=ScanRepository(),
        )
        _run_id, summary = asyncio.run(
            service.run(
                symbols=["AAA", "BBB", "CCC", "DDD"],
                years=2,
                step_days=28,
                top_n_per_asset=3,
                persist=False,
            )
        )

        accepted_samples = sum(
            row["sample_count"]
            for row in summary["candidate_filter_diagnostics"]
            if row["asset_type"] == "stock" and row["reject_reason"] == "accepted"
        )
        self.assertGreater(accepted_samples, summary["prediction_count"])

    def test_selection_stage_splits_accepted_candidates_after_top_n(self) -> None:
        last_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        bars = {
            sym: make_uptrend_bars(count=760, last_day=last_day, daily_drift=drift)
            for sym, drift in (
                ("AAA", 0.6),
                ("BBB", 0.5),
                ("CCC", 0.4),
                ("DDD", 0.3),
                ("SPY", 0.2),
            )
        }
        service = WalkForwardProofService(
            settings=proof_settings(),
            bar_store=FakeBarStore(bars),
            scan_repository=ScanRepository(),
        )
        _run_id, summary = asyncio.run(
            service.run(
                symbols=["AAA", "BBB", "CCC", "DDD"],
                years=2,
                step_days=28,
                top_n_per_asset=3,
                persist=False,
            )
        )

        accepted_pre_ranking = sum(
            row["sample_count"]
            for row in summary["candidate_filter_diagnostics"]
            if row["asset_type"] == "stock" and row["reject_reason"] == "accepted"
        )
        selected = sum(
            row["sample_count"]
            for row in summary["selection_stage_diagnostics"]
            if row["asset_type"] == "stock"
            and row["selection_stage"] == "selected_top_n"
        )
        accepted_not_selected = sum(
            row["sample_count"]
            for row in summary["selection_stage_diagnostics"]
            if row["asset_type"] == "stock"
            and row["selection_stage"] == "accepted_not_selected"
        )

        self.assertGreater(selected, 0)
        self.assertGreater(accepted_not_selected, 0)
        self.assertEqual(selected + accepted_not_selected, accepted_pre_ranking)
        selected_row = self._selection_row(
            summary["selection_stage_diagnostics"],
            selection_stage="selected_top_n",
        )
        self.assertIsNotNone(selected_row["avg_return_after_friction_stressed_pct"])
        self.assertIn("edge_vs_benchmark_pct", selected_row)

    def test_unresolved_candidates_do_not_inflate_resolved_count(self) -> None:
        tracker: dict[tuple[str, str, str, str], dict] = {}
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = self.service.build_prediction_at(
            symbol="AAA",
            asset_type="stock",
            bars=make_uptrend_bars(count=400, last_day=last_day),
            as_of=last_day,
            sample_source="historical",
            candidate_filter_tracker=tracker,
        )

        self.assertIsNotNone(result)
        row = self._row(
            _candidate_filter_diagnostic_rows(tracker),
            reject_reason="accepted",
        )
        self.assertEqual(row["sample_count"], 1)
        self.assertEqual(row["resolved_count"], 0)
        self.assertIsNone(row["hit_rate_pct"])
        self.assertIsNone(row["avg_return_after_friction_pct"])
        self.assertIsNone(row["avg_return_after_friction_stressed_pct"])

    def test_unresolved_selection_stage_candidates_do_not_inflate_resolved_count(self) -> None:
        tracker: dict[tuple[str, str, str, str], dict] = {}
        service = WalkForwardProofService(
            settings=proof_settings(proof_rsi_overbought=80.0),
            scan_repository=ScanRepository(),
        )
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = service.build_prediction_at(
            symbol="AAA",
            asset_type="stock",
            bars=make_uptrend_bars(count=400, last_day=last_day),
            as_of=last_day,
            sample_source="historical",
            selection_stage_tracker=tracker,
        )

        self.assertIsNone(result)
        row = self._selection_row(
            _selection_stage_diagnostic_rows(tracker),
            selection_stage="rejected",
        )
        self.assertEqual(row["sample_count"], 1)
        self.assertEqual(row["resolved_count"], 0)
        self.assertIsNone(row["hit_rate_pct"])
        self.assertIsNone(row["avg_return_after_friction_stressed_pct"])

    def test_existing_diagnostics_unchanged_with_candidate_filter_rows(self) -> None:
        preds = [
            {
                "asset_type": "stock",
                "sample_source": "historical",
                "status": "resolved",
                "as_of": datetime(2025, 1, 1, tzinfo=timezone.utc),
                "return_after_1w": 2.0,
                "upside_probability_pct": 65.0,
                "confidence": 60.0,
                "pattern_name": "uptrend_ma_stack",
            }
        ]
        rejection_rows = [
            {
                "asset_type": "stock",
                "track": "research",
                "reject_reason": "rsi_overbought",
                "attempted_count": 1,
                "accepted_count": 0,
                "rejected_count": 1,
                "total_rejected_count": 1,
                "rejection_rate_pct": 100.0,
                "total_rejection_rate_pct": 100.0,
            }
        ]
        baseline = self.service.compute_metrics(
            preds,
            rejection_diagnostics=rejection_rows,
        )
        with_filter_rows = self.service.compute_metrics(
            preds,
            rejection_diagnostics=rejection_rows,
            candidate_filter_diagnostics=[
                {
                    "asset_type": "stock",
                    "track": "research",
                    "pattern_name": "uptrend_ma_stack",
                    "reject_reason": "accepted",
                    "sample_count": 1,
                    "resolved_count": 1,
                    "hit_rate_pct": 100.0,
                    "avg_return_after_friction_pct": 1.0,
                    "avg_return_after_friction_stressed_pct": 0.9,
                    "edge_vs_benchmark_pct": 0.5,
                }
            ],
        )
        with_stage_rows = self.service.compute_metrics(
            preds,
            rejection_diagnostics=rejection_rows,
            candidate_filter_diagnostics=with_filter_rows["candidate_filter_diagnostics"],
            selection_stage_diagnostics=[
                {
                    "asset_type": "stock",
                    "track": "research",
                    "pattern_name": "uptrend_ma_stack",
                    "selection_stage": "selected_top_n",
                    "sample_count": 1,
                    "resolved_count": 1,
                    "hit_rate_pct": 100.0,
                    "avg_return_after_friction_stressed_pct": 0.9,
                    "edge_vs_benchmark_pct": 0.5,
                }
            ],
        )

        self.assertEqual(
            with_filter_rows["pattern_diagnostics"],
            baseline["pattern_diagnostics"],
        )
        self.assertEqual(
            with_filter_rows["rejection_diagnostics"],
            baseline["rejection_diagnostics"],
        )
        self.assertEqual(
            with_stage_rows["candidate_filter_diagnostics"],
            with_filter_rows["candidate_filter_diagnostics"],
        )
        self.assertEqual(
            with_stage_rows["pattern_diagnostics"],
            with_filter_rows["pattern_diagnostics"],
        )
        self.assertEqual(
            with_stage_rows["rejection_diagnostics"],
            with_filter_rows["rejection_diagnostics"],
        )


class MetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WalkForwardProofService(
            settings=proof_settings(), scan_repository=ScanRepository()
        )

    def _prediction(self, **kwargs) -> dict:
        base = {
            "asset_type": "stock",
            "sample_source": "out_of_sample",
            "status": "resolved",
            "as_of": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "return_after_1w": 2.0,
            "upside_probability_pct": 70.0,
            "confidence": 60.0,
            "pattern_name": "uptrend_ma_stack",
            "exit_window_helped": True,
            "protected_return_pct": 2.0,
            "hold_return_pct": 1.0,
            "prediction_count": 1,
        }
        base.update(kwargs)
        return base

    def test_metrics_upside_and_exit_window(self) -> None:
        preds = [
            self._prediction(return_after_1w=3.0, exit_window_helped=True),
            self._prediction(return_after_1w=-1.0, exit_window_helped=False),
            self._prediction(return_after_1w=2.0, exit_window_helped=True),
            self._prediction(return_after_1w=4.0, exit_window_helped=True),
        ]
        metrics = self.service.compute_metrics(preds)
        self.assertEqual(metrics["resolved_count"], 4)
        holdout = next(
            row for row in metrics["by_asset_track"] if row["asset_type"] == "stock" and row["track"] == "holdout"
        )
        self.assertAlmostEqual(holdout["upside_hit_rate_pct"], 75.0, places=1)
        self.assertAlmostEqual(holdout["exit_window_helped_rate_pct"], 75.0, places=1)
        # After friction return is strictly below gross average.
        self.assertLess(
            holdout["avg_return_after_friction_pct"], holdout["avg_return_pct"]
        )

    def test_accepted_out_of_sample_prediction_keeps_sample_source(self) -> None:
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        prediction = self.service.build_prediction_at(
            symbol="AAA",
            asset_type="stock",
            bars=make_uptrend_bars(count=400, last_day=last_day),
            as_of=datetime(2025, 7, 1, tzinfo=timezone.utc),
            sample_source="out_of_sample",
        )

        self.assertIsNotNone(prediction)
        self.assertEqual(prediction["sample_source"], "out_of_sample")

    def test_pattern_diagnostics_group_by_pattern_and_track(self) -> None:
        d1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        d2 = datetime(2025, 1, 8, tzinfo=timezone.utc)
        preds = [
            self._prediction(
                sample_source="historical",
                pattern_name="uptrend_ma_stack",
                as_of=d1,
                return_after_1w=2.0,
                upside_probability_pct=65.0,
                confidence=60.0,
            ),
            self._prediction(
                sample_source="historical",
                pattern_name="uptrend_ma_stack",
                as_of=d2,
                return_after_1w=-1.0,
                upside_probability_pct=55.0,
                confidence=40.0,
            ),
            self._prediction(
                sample_source="out_of_sample",
                pattern_name="uptrend_ma_stack",
                as_of=d1,
                return_after_1w=3.0,
                upside_probability_pct=75.0,
                confidence=70.0,
            ),
            self._prediction(
                sample_source="out_of_sample",
                pattern_name="breakout_20d_high",
                as_of=d2,
                return_after_1w=-2.0,
                upside_probability_pct=60.0,
                confidence=50.0,
            ),
        ]
        metrics = self.service.compute_metrics(preds)
        rows = metrics["pattern_diagnostics"]

        research_uptrend = next(
            row
            for row in rows
            if row["track"] == "research" and row["pattern_name"] == "uptrend_ma_stack"
        )
        holdout_uptrend = next(
            row
            for row in rows
            if row["track"] == "holdout" and row["pattern_name"] == "uptrend_ma_stack"
        )
        holdout_breakout = next(
            row
            for row in rows
            if row["track"] == "holdout" and row["pattern_name"] == "breakout_20d_high"
        )

        self.assertEqual(research_uptrend["prediction_count"], 2)
        self.assertEqual(research_uptrend["resolved_count"], 2)
        self.assertEqual(research_uptrend["upside_hit_rate_pct"], 50.0)
        self.assertEqual(research_uptrend["avg_upside_probability_pct"], 60.0)
        self.assertEqual(research_uptrend["avg_confidence"], 50.0)
        self.assertEqual(holdout_uptrend["prediction_count"], 1)
        self.assertEqual(holdout_uptrend["upside_hit_rate_pct"], 100.0)
        self.assertEqual(holdout_breakout["prediction_count"], 1)
        self.assertEqual(holdout_breakout["upside_hit_rate_pct"], 0.0)

    def test_rejection_diagnostics_count_build_path_reasons_and_totals(self) -> None:
        tracker: dict[tuple[str, str], dict] = {}
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        as_of = datetime(2025, 7, 1, tzinfo=timezone.utc)
        bars = make_uptrend_bars(count=400, last_day=last_day)

        accepted_service = WalkForwardProofService(
            settings=proof_settings(proof_rsi_overbought=101.0),
            scan_repository=ScanRepository(),
        )
        accepted = accepted_service.build_prediction_at(
            symbol="AAA",
            asset_type="stock",
            bars=bars,
            as_of=as_of,
            sample_source="historical",
            rejection_tracker=tracker,
        )
        self.assertIsNotNone(accepted)

        rsi_service = WalkForwardProofService(
            settings=proof_settings(proof_rsi_overbought=80.0),
            scan_repository=ScanRepository(),
        )
        rsi_rejected = rsi_service.build_prediction_at(
            symbol="AAA",
            asset_type="stock",
            bars=bars,
            as_of=as_of,
            sample_source="historical",
            rejection_tracker=tracker,
        )
        self.assertIsNone(rsi_rejected)

        ev_service = WalkForwardProofService(
            settings=proof_settings(proof_min_expected_value_pct=100.0),
            scan_repository=ScanRepository(),
        )
        ev_rejected = ev_service.build_prediction_at(
            symbol="AAA",
            asset_type="stock",
            bars=bars,
            as_of=as_of,
            sample_source="out_of_sample",
            rejection_tracker=tracker,
        )
        self.assertIsNone(ev_rejected)

        rows = _rejection_diagnostic_rows(tracker)
        research_rsi = next(
            row
            for row in rows
            if row["track"] == "research" and row["reject_reason"] == "rsi_overbought"
        )
        research_below_sma = next(
            row
            for row in rows
            if row["track"] == "research" and row["reject_reason"] == "below_sma50"
        )
        holdout_ev = next(
            row
            for row in rows
            if row["track"] == "holdout" and row["reject_reason"] == "expected_value_below_min"
        )

        self.assertEqual(research_rsi["attempted_count"], 2)
        self.assertEqual(research_rsi["accepted_count"], 1)
        self.assertEqual(research_rsi["rejected_count"], 1)
        self.assertEqual(research_rsi["total_rejected_count"], 1)
        self.assertEqual(research_rsi["rejection_rate_pct"], 50.0)
        self.assertEqual(research_rsi["total_rejection_rate_pct"], 50.0)
        self.assertEqual(research_below_sma["rejected_count"], 0)
        self.assertEqual(holdout_ev["attempted_count"], 1)
        self.assertEqual(holdout_ev["accepted_count"], 0)
        self.assertEqual(holdout_ev["rejected_count"], 1)
        self.assertEqual(holdout_ev["total_rejected_count"], 1)
        self.assertEqual(holdout_ev["rejection_rate_pct"], 100.0)

    def test_tail_helpers(self) -> None:
        returns = [-5.0, -3.0, 1.0, 2.0, 4.0, 6.0, -8.0, 3.0, 2.0, -1.0]
        self.assertIsNotNone(_worst_decile_mean(returns))
        self.assertEqual(_worst_decile_mean(returns), -8.0)
        dd = _max_drawdown_pct(returns)
        self.assertIsNotNone(dd)
        self.assertGreaterEqual(dd, 0.0)


class SolidityMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WalkForwardProofService(
            settings=proof_settings(), scan_repository=ScanRepository()
        )

    def _resolved(self, **kwargs) -> dict:
        base = {
            "asset_type": "stock",
            "sample_source": "out_of_sample",
            "status": "resolved",
            "as_of": datetime(2025, 6, 1, tzinfo=timezone.utc),
            "return_after_1w": 2.0,
            "upside_probability_pct": 70.0,
            "estimated_exit_price": 104.0,
            "invalidation_level": 97.0,
            "exit_conflict": False,
        }
        base.update(kwargs)
        return base

    def test_wilson_lower_bound_behaviour(self) -> None:
        self.assertIsNone(_wilson_lower_bound_pct(0, 0))
        thin = _wilson_lower_bound_pct(8, 10)
        self.assertIsNotNone(thin)
        # The lower bound is strictly below the 80% point estimate.
        self.assertLess(thin, 80.0)
        # A larger sample at the same rate tightens the bound upward.
        thick = _wilson_lower_bound_pct(80, 100)
        self.assertGreater(thick, thin)

    def test_spearman_ic_detects_and_flags_noise(self) -> None:
        monotone = [(float(i), float(i)) for i in range(10)]
        ic, t_stat = _spearman_ic(monotone)
        self.assertAlmostEqual(ic, 1.0, places=4)
        self.assertIsNone(t_stat)  # perfect correlation -> t undefined, reported safely
        noisy = [(1.0, 3.0), (2.0, 1.0), (3.0, 4.0), (4.0, 2.0), (5.0, 5.0), (6.0, 0.5)]
        ic2, t2 = _spearman_ic(noisy)
        self.assertIsNotNone(ic2)
        self.assertIsNotNone(t2)
        self.assertEqual(_spearman_ic([(1.0, 1.0)]), (None, None))

    def test_benchmark_regime_labels(self) -> None:
        last = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bull = make_uptrend_bars(count=260, last_day=last, daily_drift=0.4)
        self.assertEqual(_benchmark_regime(bull, last), "bull")
        bear = make_uptrend_bars(count=260, last_day=last, start_price=220.0, daily_drift=-0.4)
        self.assertEqual(_benchmark_regime(bear, last), "bear")
        self.assertEqual(_benchmark_regime([], last), "unknown")
        # Too little history cannot be classified.
        self.assertEqual(_benchmark_regime(bull[:50], last), "unknown")

    def test_exit_conflict_rate_and_solidity_in_metrics(self) -> None:
        preds = [
            self._resolved(return_after_1w=3.0, upside_probability_pct=80.0, exit_conflict=True),
            self._resolved(return_after_1w=-1.0, upside_probability_pct=55.0, exit_conflict=False),
            self._resolved(return_after_1w=2.0, upside_probability_pct=72.0, exit_conflict=False),
            self._resolved(return_after_1w=1.0, upside_probability_pct=60.0, exit_conflict=True),
        ]
        metrics = self.service.compute_metrics(preds)
        holdout = next(
            row for row in metrics["by_asset_track"] if row["track"] == "holdout"
        )
        self.assertAlmostEqual(holdout["exit_conflict_rate_pct"], 50.0, places=1)
        self.assertIsNotNone(holdout["upside_hit_rate_lb95_pct"])
        self.assertIn("edge_significant", holdout)
        self.assertIn("information_coefficient", holdout)
        self.assertIn("regime_sample_counts", holdout)
        self.assertIn("cross_regime_edge_ok", holdout)


class VerdictTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WalkForwardProofService(
            settings=proof_settings(
                proof_pilot_min_predictions_per_asset=2,
                proof_pilot_min_upside_hit_rate_pct=55.0,
                proof_pilot_max_calibration_gap_pct=15.0,
                proof_pilot_min_after_friction_return_pct=0.0,
                proof_pilot_max_drawdown_pct=50.0,
                proof_pilot_min_exit_window_helped_rate_pct=50.0,
            ),
            scan_repository=ScanRepository(),
        )

    def _strong_row(self, asset_type: str, track: str) -> dict:
        return {
            "asset_type": asset_type,
            "track": track,
            "prediction_count": 5,
            "resolved_count": 5,
            "upside_hit_rate_pct": 80.0,
            "avg_return_after_friction_stressed_pct": 1.0,
            "calibration_mean_abs_gap_pct": 5.0,
            "confidence_discrimination_pct": 10.0,
            "exit_window_helped_rate_pct": 70.0,
            "max_drawdown_pct": 10.0,
            "edge_after_friction_vs_buy_and_hold_pct": 0.5,
            # Statistical-solidity gates (all required by default settings).
            "upside_hit_rate_lb95_pct": 55.0,
            "edge_significant": True,
            "information_coefficient": 0.08,
            "ic_t_stat": 3.0,
            "cross_regime_edge_ok": True,
            "regime_sample_counts": {"bull": 10, "chop": 8},
            "regime_avg_return_pct": {"bull": 1.5, "chop": 0.5},
        }

    def test_verdict_ready_when_all_checks_pass(self) -> None:
        metrics = {
            "by_asset_track": [
                self._strong_row("stock", "research"),
                self._strong_row("stock", "holdout"),
                self._strong_row("crypto", "research"),
                self._strong_row("crypto", "holdout"),
            ]
        }
        verdict = self.service.compute_verdict(metrics)
        self.assertTrue(verdict["ready"])
        self.assertTrue(verdict["real_money_trust_blocked"])

    def test_verdict_blocked_when_no_data(self) -> None:
        verdict = self.service.compute_verdict({"by_asset_track": []})
        self.assertFalse(verdict["ready"])
        self.assertTrue(verdict["real_money_trust_blocked"])

    def test_verdict_blocked_when_holdout_weak(self) -> None:
        weak = self._strong_row("stock", "holdout")
        weak["upside_hit_rate_pct"] = 20.0
        metrics = {
            "by_asset_track": [
                self._strong_row("stock", "research"),
                weak,
                self._strong_row("crypto", "research"),
                self._strong_row("crypto", "holdout"),
            ]
        }
        verdict = self.service.compute_verdict(metrics)
        self.assertFalse(verdict["ready"])


class FilterTests(unittest.TestCase):
    def test_rsi_overbought_is_rejected(self) -> None:
        # Default overbought threshold (not relaxed); a pure monotonic ramp -> RSI 100.
        service = WalkForwardProofService(
            settings=proof_settings(proof_rsi_overbought=80.0), scan_repository=ScanRepository()
        )
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = make_uptrend_bars(count=400, last_day=last_day)
        result = service.build_prediction_at(
            symbol="AAA", asset_type="stock", bars=bars, as_of=datetime(2025, 7, 1, tzinfo=timezone.utc)
        )
        self.assertIsNone(result)

    def test_expected_value_gate_rejects_negative_reward_risk(self) -> None:
        # Very high friction so EV after friction is non-positive -> rejected.
        service = WalkForwardProofService(
            settings=proof_settings(proof_min_expected_value_pct=100.0), scan_repository=ScanRepository()
        )
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = make_uptrend_bars(count=400, last_day=last_day)
        result = service.build_prediction_at(
            symbol="AAA", asset_type="stock", bars=bars, as_of=datetime(2025, 7, 1, tzinfo=timezone.utc)
        )
        self.assertIsNone(result)

    def test_buy_hold_baseline_filter_rejects_no_edge(self) -> None:
        service = WalkForwardProofService(
            settings=proof_settings(proof_require_buy_hold_baseline=True),
            scan_repository=ScanRepository(),
        )
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = make_uptrend_bars(count=400, last_day=last_day)
        with patch(
            "app.services.walk_forward_proof._historical_buy_hold_avg_return",
            return_value=100.0,
        ):
            result = service.build_prediction_at(
                symbol="AAA",
                asset_type="stock",
                bars=bars,
                as_of=datetime(2025, 7, 1, tzinfo=timezone.utc),
            )
        self.assertIsNone(result)

    def test_volume_filter_rejects_drying_liquidity(self) -> None:
        service = WalkForwardProofService(
            settings=proof_settings(proof_min_volume_median_ratio=2.0),
            scan_repository=ScanRepository(),
        )
        last_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = make_uptrend_bars(count=400, last_day=last_day)
        for index, bar in enumerate(bars):
            bar["v"] = 1000 if index < len(bars) - 25 else 1
        result = service.build_prediction_at(
            symbol="AAA", asset_type="stock", bars=bars, as_of=datetime(2025, 7, 1, tzinfo=timezone.utc)
        )
        self.assertIsNone(result)


class CalibrationTests(unittest.TestCase):
    def test_reliability_map_and_gap(self) -> None:
        from app.core.calibration import build_reliability_map, calibrated_mean_abs_gap_pct

        research = [(70.0, True), (72.0, False), (30.0, False), (32.0, True), (30.0, False)]
        mapping = build_reliability_map(research, n_bins=5)
        self.assertTrue(mapping)
        gap = calibrated_mean_abs_gap_pct(mapping, [(71.0, True), (31.0, False)])
        self.assertIsNotNone(gap)
        self.assertGreaterEqual(gap, 0.0)


class PeriodDrawdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WalkForwardProofService(
            settings=proof_settings(), scan_repository=ScanRepository()
        )

    def test_period_returns_collapse_same_date(self) -> None:
        d1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        d2 = datetime(2025, 1, 8, tzinfo=timezone.utc)
        ordered = [
            {"as_of": d1, "return_after_1w": 2.0},
            {"as_of": d1, "return_after_1w": 4.0},
            {"as_of": d2, "return_after_1w": -1.0},
        ]
        self.assertEqual(self.service._period_returns(ordered), [3.0, -1.0])

    def test_max_drawdown_positive_on_decline(self) -> None:
        self.assertGreater(_max_drawdown_pct([2.0, -3.0, 1.0]) or 0.0, 0.0)


class BenchmarkRunTests(unittest.TestCase):
    def test_run_produces_benchmarks_and_edges(self) -> None:
        last_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        bars = {
            "AAA": make_uptrend_bars(count=760, last_day=last_day, daily_drift=0.5),
            "BBB": make_uptrend_bars(count=760, last_day=last_day, daily_drift=0.3),
            "CCC/USD": make_uptrend_bars(count=760, last_day=last_day, daily_drift=0.4),
            "SPY": make_uptrend_bars(count=760, last_day=last_day, daily_drift=0.2),
            "BTC/USD": make_uptrend_bars(count=760, last_day=last_day, daily_drift=0.35),
        }
        service = WalkForwardProofService(
            settings=proof_settings(),
            bar_store=FakeBarStore(bars),
            scan_repository=ScanRepository(),
        )
        run_id, summary = asyncio.run(
            service.run(symbols=["AAA", "BBB", "CCC/USD"], years=2, step_days=28, top_n_per_asset=3, persist=False)
        )
        self.assertTrue(summary["benchmarks"])
        strategies = {row["strategy"] for row in summary["benchmarks"]}
        self.assertIn("buy_and_hold", strategies)
        # At least one asset/track row carries an edge vs buy-and-hold.
        has_edge = any(
            row.get("edge_after_friction_vs_buy_and_hold_pct") is not None
            for row in summary["by_asset_track"]
        )
        self.assertTrue(has_edge)


class CryptoHistoryGateTests(unittest.TestCase):
    def test_verdict_blocks_crypto_when_history_insufficient(self) -> None:
        service = WalkForwardProofService(
            settings=proof_settings(
                proof_pilot_min_predictions_per_asset=1,
                proof_pilot_min_upside_hit_rate_pct=0.0,
                proof_pilot_max_calibration_gap_pct=100.0,
                proof_pilot_min_after_friction_return_pct=-100.0,
                proof_pilot_max_drawdown_pct=100.0,
                proof_pilot_min_exit_window_helped_rate_pct=0.0,
                proof_pilot_min_edge_vs_buy_hold_pct=-100.0,
            ),
            scan_repository=ScanRepository(),
        )

        def row(asset_type: str, track: str) -> dict:
            return {
                "asset_type": asset_type,
                "track": track,
                "prediction_count": 5,
                "resolved_count": 5,
                "upside_hit_rate_pct": 90.0,
                "avg_return_after_friction_stressed_pct": 5.0,
                "calibration_mean_abs_gap_pct": 1.0,
                "exit_window_helped_rate_pct": 90.0,
                "max_drawdown_pct": 1.0,
                "edge_after_friction_vs_buy_and_hold_pct": 5.0,
            }

        metrics = {
            "by_asset_track": [
                row("stock", "research"),
                row("stock", "holdout"),
                row("crypto", "research"),
                row("crypto", "holdout"),
            ]
        }
        verdict = service.compute_verdict(metrics, crypto_history_ok=False)
        self.assertFalse(verdict["ready"])
        self.assertTrue(
            any(c["name"] == "crypto_history_sufficient" and not c["passed"] for c in verdict["checks"])
        )


class WalkForwardRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "wf.db"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.session_local = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        self.session_patcher = patch("app.services.walk_forward_repository.SessionLocal", self.session_local)
        self.engine_patcher = patch("app.services.walk_forward_repository.engine", self.engine)
        self.session_patcher.start()
        self.engine_patcher.start()
        self.repo = WalkForwardRepository()

    def tearDown(self) -> None:
        self.session_patcher.stop()
        self.engine_patcher.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_persist_and_read_latest_summary(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        prediction = {
            "as_of": now,
            "asset_type": "stock",
            "ticker": "AAA",
            "selection_rank": 1,
            "sample_source": "historical",
            "pattern_name": "uptrend_ma_stack",
            "decision_signal": "BUY",
            "confidence": 70.0,
            "upside_probability_pct": 70.0,
            "historical_hit_rate_pct": 65.0,
            "sample_size": 20,
            "entry_price": 100.0,
            "projected_range_low": 98.0,
            "projected_range_high": 105.0,
            "estimated_exit_price": 104.0,
            "invalidation_level": 97.0,
            "stop_growing_signal": "Growth likely to slow near $104.",
            "horizon": "1w",
            "forward_days": 7,
            "generated_at": now,
            "resolve_due_at": now + timedelta(days=7),
            "status": "resolved",
            "price_after_1w": 103.0,
            "return_after_1w": 3.0,
            "in_range": True,
            "accuracy_outcome": "in_range",
            "exit_window_status": "resolved",
            "exit_hit": False,
            "invalidation_hit": False,
            "protected_return_pct": 3.0,
            "hold_return_pct": 3.0,
            "exit_window_helped": True,
            "evaluated_at": now,
        }
        self.repo.persist_run(
            run_id="wf-test-1",
            params={"target_years": 3, "step_days": 7, "top_n_per_asset": 5, "forward_days": 7},
            window_start=now - timedelta(days=730),
            window_end=now,
            holdout_start=now - timedelta(days=90),
            symbol_count=1,
            predictions=[prediction],
            metrics={
                "resolved_count": 1,
                "pending_count": 0,
                "by_asset_track": [
                    {
                        "asset_type": "stock",
                        "track": "research",
                        "prediction_count": 1,
                        "resolved_count": 1,
                        "pending_count": 0,
                        "upside_hit_rate_pct": 100.0,
                    }
                ],
                "calibration_buckets": [],
                "note": None,
            },
            verdict={"ready": False, "real_money_trust_blocked": True, "summary": "x", "checks": []},
            coverage=[{"symbol": "AAA", "asset_type": "stock", "bar_count": 400, "years_available": 2.0, "sufficient": True}],
        )

        summary = self.repo.get_latest_run_summary()
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary.run_id, "wf-test-1")
        self.assertEqual(summary.prediction_count, 1)
        self.assertEqual(summary.resolved_count, 1)
        self.assertEqual(len(summary.by_asset_track), 1)
        self.assertEqual(summary.by_asset_track[0].upside_hit_rate_pct, 100.0)
        self.assertTrue(summary.pilot_verdict.real_money_trust_blocked)
        self.assertEqual(len(self.repo.get_predictions("wf-test-1")), 1)

    def test_manifest_fields_round_trip(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.repo.persist_run(
            run_id="wf-manifest-1",
            params={"target_years": 3, "step_days": 7, "top_n_per_asset": 5, "forward_days": 7, "overlap_status": "non_overlapping"},
            window_start=now - timedelta(days=730),
            window_end=now,
            holdout_start=now - timedelta(days=90),
            symbol_count=2,
            predictions=[],
            metrics={"resolved_count": 0, "pending_count": 0, "by_asset_track": []},
            verdict={"ready": False, "real_money_trust_blocked": True, "summary": "x", "checks": [], "by_asset": []},
            coverage=[],
            manifest={
                "config_fingerprint": "abc123",
                "code_commit": "deadbeef",
                "engine_version": "wf-engine-v1",
                "validation_start": now - timedelta(days=180),
                "universe": ["AAA", "BBB/USD"],
                "data_quality": {"ok": False, "issues": ["AAA: stale tail"]},
            },
        )
        summary = self.repo.get_latest_run_summary()
        assert summary is not None
        self.assertEqual(summary.config_fingerprint, "abc123")
        self.assertEqual(summary.code_commit, "deadbeef")
        self.assertEqual(summary.engine_version, "wf-engine-v1")
        self.assertEqual(summary.universe, ["AAA", "BBB/USD"])
        self.assertIsNotNone(summary.validation_start)
        self.assertFalse(summary.data_quality_ok)
        self.assertEqual(summary.overlap_status, "non_overlapping")

    def test_validation_track_rows_round_trip(self) -> None:
        # The engine emits research/validation/holdout track labels; the summary
        # schema must accept the middle "validation" segment or build_summary_from_run
        # raises a Pydantic ValidationError and breaks /proof/summary + the run API.
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.repo.persist_run(
            run_id="wf-validation-1",
            params={"target_years": 3, "step_days": 14, "top_n_per_asset": 5, "forward_days": 7},
            window_start=now - timedelta(days=730),
            window_end=now,
            holdout_start=now - timedelta(days=90),
            symbol_count=1,
            predictions=[],
            metrics={
                "resolved_count": 0,
                "pending_count": 0,
                "by_asset_track": [
                    {
                        "asset_type": "stock",
                        "track": "validation",
                        "prediction_count": 3,
                        "resolved_count": 3,
                        "pending_count": 0,
                        "upside_hit_rate_pct": 66.7,
                    }
                ],
                "calibration_buckets": [
                    {
                        "probability_band": "60-70",
                        "asset_type": "stock",
                        "track": "validation",
                        "evaluated_count": 3,
                    }
                ],
                "benchmarks": [
                    {
                        "asset_type": "stock",
                        "track": "validation",
                        "strategy": "buy_and_hold",
                        "periods": 3,
                    }
                ],
            },
            verdict={"ready": False, "real_money_trust_blocked": True, "summary": "x", "checks": []},
            coverage=[],
        )

        summary = self.repo.get_latest_run_summary()
        assert summary is not None
        self.assertEqual(summary.run_id, "wf-validation-1")
        self.assertEqual(summary.by_asset_track[0].track, "validation")
        self.assertEqual(summary.calibration_buckets[0].track, "validation")
        self.assertEqual(summary.benchmarks[0].track, "validation")


class WalkForwardManifestTests(unittest.TestCase):
    def _service(self) -> WalkForwardProofService:
        last_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        bars = {
            "AAA": make_uptrend_bars(count=760, last_day=last_day, daily_drift=0.5),
            "BBB": make_uptrend_bars(count=760, last_day=last_day, daily_drift=0.3),
            "CCC/USD": make_uptrend_bars(count=760, last_day=last_day, daily_drift=0.4),
        }
        return WalkForwardProofService(
            settings=proof_settings(),
            bar_store=FakeBarStore(bars),
            scan_repository=ScanRepository(),
        )

    def test_window_has_ordered_validation_segment(self) -> None:
        service = WalkForwardProofService(
            settings=proof_settings(proof_holdout_months=3, proof_validation_months=2),
            scan_repository=ScanRepository(),
        )
        window_start, window_end, holdout_start, validation_start = service._window(
            years=2, forward_days=7
        )
        self.assertLess(window_start, validation_start)
        self.assertLess(validation_start, holdout_start)
        self.assertLessEqual(holdout_start, window_end + timedelta(days=400))

    def test_run_is_deterministic_over_stored_bars(self) -> None:
        service = self._service()

        async def run():
            return await service.run(
                symbols=["AAA", "BBB", "CCC/USD"],
                years=2,
                step_days=14,
                top_n_per_asset=3,
                persist=False,
            )

        run_id_a, summary_a = asyncio.run(run())
        run_id_b, summary_b = asyncio.run(run())
        # Deterministic id derived from config fingerprint + window + universe.
        self.assertEqual(run_id_a, run_id_b)
        self.assertEqual(summary_a["by_asset_track"], summary_b["by_asset_track"])
        self.assertEqual(summary_a["config_fingerprint"], summary_b["config_fingerprint"])
        self.assertEqual(summary_a["overlap_status"], "non_overlapping")

    def test_run_verdict_is_independent_per_asset(self) -> None:
        service = self._service()

        async def run():
            return await service.run(
                symbols=["AAA", "BBB", "CCC/USD"],
                years=2,
                step_days=14,
                top_n_per_asset=3,
                persist=False,
            )

        _, summary = asyncio.run(run())
        by_asset = {row["asset_type"]: row for row in summary["pilot_verdict"]["by_asset"]}
        self.assertIn("stock", by_asset)
        self.assertIn("crypto", by_asset)
        # Each per-asset verdict is self-contained (own checks, own summary).
        for asset, verdict in by_asset.items():
            self.assertTrue(verdict["real_money_trust_blocked"])
            self.assertIn(asset, verdict["summary"])


if __name__ == "__main__":
    unittest.main()
