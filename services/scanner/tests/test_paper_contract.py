"""Isolated acceptance checks for the real hybrid recommendation/paper contract.

Only historical evidence and provider quotes are fixtures. Scoring, calibration,
gate/selection, persistence, risk, placement, due selection, closure and ledger
aggregation use application code. Run via scripts/run_isolated_tests.py so a
personal database or network request fails the verification.
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.services.automation_repository as automation_repository_module
import app.services.execution as execution_module
import app.services.repository as repository_module
import app.services.scanner as scanner_module
from app.config import get_settings
from app.core.paper_action import paper_action_checks
from app.core.selection import apply_top_pick_selection, select_top_picks
from app.core.signals import compute_signal_and_explanation
from app.core.strategy_contract import build_strategy_evaluation_metadata
from app.db import Base
from app.errors import AppError
from app.models.scan import ExecutionAuditORM, PaperPositionORM, PredictionSnapshotORM, SignalOutcomeORM
from app.schemas import OptionsFlowSnapshot, OrderPlaceRequest, OrderPreviewRequest, ScanResult, ScanRun, WeeklyPatternPrediction
from app.services.execution import ExecutionService
from app.services.repository import ScanRepository
from app.services.scanner import ScannerService


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _clock_at(value: datetime):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    return FrozenDatetime


class PaperContractAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.engine = create_engine(
            f"sqlite:///{(Path(directory) / 'contract.db').as_posix()}",
            future=True, connect_args={"check_same_thread": False},
        )
        self.addCleanup(self.engine.dispose)
        self.SessionLocal = sessionmaker(
            bind=self.engine, expire_on_commit=False, autoflush=False, future=True,
        )
        Base.metadata.create_all(self.engine)
        for module in (repository_module, execution_module, automation_repository_module):
            self.stack.enter_context(patch.object(module, "SessionLocal", self.SessionLocal))
        # Preserve the operator's cached settings object; the local one-hour
        # product choice and readiness bypass apply only to this isolated fixture.
        self.settings = get_settings().model_copy(update={
            "trade_gate_horizon": "1h",
            "require_readyz_for_execution": False,
            "paper_loop_kill_switch": False,
            "execution_enabled": False,
            "allow_live_trading": False,
        })
        self.repo = ScanRepository()
        self.repo.settings = self.settings
        self.scanner = ScannerService()
        self.scanner.settings = self.settings
        self.scanner.repo = self.repo
        self.scanner.brain.settings = self.settings
        self.scanner.brain.repository = self.repo
        self.execution = ExecutionService(scan_repository=self.repo)
        self.execution.settings = self.settings
        self.execution.risk.settings = self.settings
        self.execution.alpaca.get_latest_price = AsyncMock(return_value=100.0)
        self.execution.alpaca.get_latest_crypto_price = AsyncMock(return_value=100.0)
        self.scanner.alpaca.get_latest_price = AsyncMock(return_value=104.0)
        self.scanner.alpaca.get_latest_crypto_price = AsyncMock(return_value=104.0)
        self.scan_at = datetime.now(timezone.utc) - timedelta(seconds=60)
        self.fill_at = self.scan_at + timedelta(seconds=30)

    def _store_hybrid_buy(self, *, ticker="AAPL", asset_type="stock", evidence=True, provider_status="ok") -> ScanResult:
        signal = compute_signal_and_explanation(
            ticker=ticker, asset_type=asset_type, price=100.0,
            price_change_pct=3.0, relative_volume=2.0, breakout_flag=True,
            breakdown_flag=False, above_vwap=True, close_to_high_pct=0.95,
            close_to_low_pct=0.05, sentiment_score=0.8, catalyst_score=0.5,
            market_status="bullish", relative_strength_pct=2.0,
            options_snapshot=OptionsFlowSnapshot(bullish_score=2.0),
            context_bias=0.15, trend_above_sma=True, trend_strength_pct=2.0,
            buy_threshold=self.settings.signal_buy_threshold,
            sell_threshold=self.settings.signal_sell_threshold,
            signal_margin=self.settings.signal_margin,
        )
        self.assertEqual(signal.decision_signal, "BUY")
        if evidence:
            # Thirty independent earlier price-bearing rows; no threshold,
            # calibration formula, learned input or production gate is mocked.
            band = self.repo._score_band(signal.score)
            with self.SessionLocal.begin() as session:
                for index in range(30):
                    future_price = 100.4 if index < 24 else 99.9
                    session.add(SignalOutcomeORM(
                        run_id=f"evidence-{asset_type}-{index}", ticker=ticker,
                        asset_type=asset_type, signal="BUY", confidence=signal.score,
                        raw_score=signal.score, score_band=band, calibrated_confidence=signal.score,
                        calibration_source="raw", entry_price=100.0,
                        generated_at=self.scan_at - timedelta(hours=2, minutes=index),
                        price_after_1h=future_price,
                        return_after_1h=self.repo._signal_return(signal="BUY", entry_price=100.0, future_price=future_price),
                        status_1h="resolved", evaluated_at_1h=self.scan_at-timedelta(hours=1),
                        sample_source="live_paper_forward", gate_passed=True,
                    ))
        confidence, source, passed, reason, checks, blend = self.scanner._gate_signal(
            asset_type=asset_type, signal=signal, observed_at=self.scan_at,
        )
        self.assertEqual(passed, evidence)
        metadata = build_strategy_evaluation_metadata(
            signal="BUY", gate_passed=passed, calibration_source=source,
            data_quality="ok", provider_status=provider_status,
        )
        # Weekly context deliberately has a bearish range: it must not replace
        # the intraday BUY or become the paper holding duration.
        weekly = WeeklyPatternPrediction(
            pattern_name="momentum_rsi_bear", directional_bias="bearish",
            range_low=90.0, range_high=110.0, sample_size=40,
            historical_hit_rate_pct=67.5, avg_forward_1w_return_pct=-0.2,
            evidence_basis="historical_only", data_quality="ok",
        )
        row = ScanResult(
            ticker=ticker, asset_type=asset_type, score=signal.score,
            raw_score=signal.score, calibrated_confidence=confidence,
            confidence_score=confidence, calibration_source=source,
            buy_score=signal.buy_score, sell_score=signal.sell_score,
            decision_signal=signal.decision_signal, scoring_version=signal.scoring_version,
            explanation=signal.explanation, price=100.0, price_change_pct=3.0,
            relative_volume=2.0, sentiment_score=0.8, filing_flag=False,
            breakout_flag=True, market_status="bullish", sector_strength_score=0.5,
            relative_strength_pct=2.0, gate_passed=passed, gate_reason=reason,
            gate_checks=checks, evidence_quality=metadata.evidence_quality,
            evidence_quality_score=metadata.evidence_quality_score,
            execution_eligibility=metadata.execution_eligibility, data_grade=metadata.data_grade,
            strategy_id=metadata.strategy_id, strategy_version=metadata.strategy_version,
            strategy_primary_horizon=self.settings.trade_gate_horizon,
            provider_status=provider_status, bar_age_minutes=1.0,
            bar_as_of=self.scan_at, freshness_flags={"alpaca_market_bars": "ok"},
            weekly_prediction=weekly, created_at=self.scan_at,
            layer_details={"calibration": blend, "weekly_prediction": weekly.model_dump(mode="json")},
        )
        row = apply_top_pick_selection([row], settings=self.settings)[0]
        snapshot = self.scanner.brain.build_snapshot(
            as_of=self.scan_at, results=[row], daily_bars_by_symbol={},
        )
        decisions = self.scanner.brain.hybrid.decide_all(snapshot)
        self.assertEqual(decisions[0].action, "BUY")
        self.assertIsNone(decisions[0].p_up_calibrated)
        self.repo.save_run(
            ScanRun(run_id="contract-run", created_at=self.scan_at, market_status="bullish",
                    scan_count=1, watchlist_size=1, results=[row]),
            champion_decisions=decisions,
            champion_policy_id=self.scanner.brain.hybrid.policy_id,
            champion_policy_version=self.scanner.brain.hybrid.policy_version,
            champion_fingerprint=self.scanner.brain.hybrid.fingerprint(),
        )
        return row

    def _preview_and_place(self, *, ticker="AAPL", qty=1.0):
        preview = asyncio.run(self.execution.preview(OrderPreviewRequest(
            ticker=ticker, side="buy", qty=qty, stop_price=99.0, target_price=102.0,
        )))
        self.assertTrue(preview.trade_gate.allowed, preview.trade_gate.reason)
        self.execution.alpaca.get_latest_price.return_value = 101.0
        self.execution.alpaca.get_latest_crypto_price.return_value = 101.0
        request = OrderPlaceRequest(
            ticker=ticker, side="buy", qty=preview.qty,
            preview_audit_id=preview.execution_audit_id, idempotency_key="contract-placement-1",
            paper_contract=getattr(preview, "paper_contract", None),
            stop_price=99.0, target_price=102.0,
        )
        with patch.object(execution_module, "datetime", _clock_at(self.fill_at)):
            place = asyncio.run(self.execution.place(request))
        self.assertTrue(place.ok, place.message)
        self.assertIsNotNone(place.ledger_id)
        return preview, request, place

    def _close_at(self, observed_at: datetime) -> int:
        # The maintenance path timestamps its actual quote retrieval, separately
        # from due selection. Freeze that clock as well as the eligibility time.
        with patch.object(scanner_module, "datetime", _clock_at(observed_at)):
            return asyncio.run(self.scanner.close_open_positions_past_horizon(observed_at=observed_at))

    def test_real_buy_preview_fill_frozen_deadline_late_close_and_gross_ledger(self):
        row = self._store_hybrid_buy()
        self.assertTrue(all(check.passed for check in paper_action_checks(row)))
        self.assertEqual(select_top_picks([row], settings=self.settings).stocks[0].ticker, "AAPL")
        preview, request, place = self._preview_and_place(qty=2.0)
        self.assertEqual(preview.paper_contract.source_run_id, "contract-run")
        self.assertEqual(preview.paper_contract.policy_id, "hybrid_legacy")
        self.assertEqual(preview.paper_contract.policy_version, self.scanner.brain.hybrid.policy_version)
        self.assertEqual(preview.paper_contract.decision_fingerprint, self.scanner.brain.hybrid.fingerprint())
        self.assertEqual(preview.paper_contract.holding_duration_seconds, 3600)
        self.assertEqual(preview.paper_contract.exit_method, "time_based")
        self.assertEqual(place.paper_contract, preview.paper_contract)
        position = self.repo.list_paper_positions()[0]
        due_at = self.fill_at + timedelta(hours=1)
        self.assertEqual(_utc(position.opened_at), self.fill_at)
        self.assertEqual(_utc(position.exit_due_at), due_at)
        self.assertEqual(position.simulated_fill_price, 101.0)
        self.assertEqual(position.source_run_id, "contract-run")
        self.assertEqual(position.policy_id, preview.paper_contract.policy_id)
        # Crossing an advisory stop before the saved deadline does not trigger a
        # protective order or a fabricated protective result.
        self.scanner.alpaca.get_latest_price.return_value = 98.0
        self.assertEqual(self._close_at(self.fill_at+timedelta(minutes=30)), 0)
        self.scanner.alpaca.get_latest_price.assert_not_awaited()
        self.scanner.alpaca.get_latest_price.return_value = 104.0
        self.settings.trade_gate_horizon = "1d"
        self.assertEqual(self.repo.list_paper_positions_due_for_horizon_close(observed_at=due_at-timedelta(seconds=1)), [])
        self.assertEqual(self._close_at(due_at+timedelta(minutes=10)), 1)
        closed = self.repo.list_paper_positions(status="closed")[0]
        self.assertEqual(_utc(closed.exit_due_at), due_at)
        self.assertEqual(_utc(closed.closed_at), due_at+timedelta(minutes=10))
        self.assertEqual(closed.close_price, 104.0)
        self.assertEqual(closed.realized_pnl, 6.0)
        self.assertEqual(closed.closure_status, "closed_late")
        self.assertEqual(closed.close_delay_seconds, 600.0)
        summary = self.repo.get_paper_ledger_summary()
        self.assertEqual(summary.gross_pnl_usd, 6.0)
        self.assertEqual(summary.total_realized_pnl, 6.0)
        self.assertEqual(summary.closed_positions, 1)
        self.assertEqual(summary.open_positions, 0)
        signal_summary = self.repo.get_signal_outcome_summary(asset_type="stock")
        self.assertEqual(signal_summary.overall.evaluated_1h_count, 30)
        self.assertAlmostEqual(signal_summary.overall.avg_return_1h, 0.3)
        with self.SessionLocal() as session:
            signal_row = session.scalar(select(SignalOutcomeORM).where(SignalOutcomeORM.run_id == "contract-run"))
            prediction = session.scalar(select(PredictionSnapshotORM).where(PredictionSnapshotORM.run_id == "contract-run"))
        self.assertIsNone(signal_row.price_after_1h)
        self.assertIsNone(signal_row.return_after_1h)
        self.assertEqual(prediction.horizon, "1w")
        self.assertEqual(prediction.status, "pending")
        self.assertIsNone(json.loads(prediction.pattern_metadata_json)["upside_probability_pct"])

    def test_repeated_placement_and_closure_do_not_duplicate_records(self):
        self._store_hybrid_buy()
        _, request, place = self._preview_and_place()
        repeated = asyncio.run(self.execution.place(request))
        self.assertEqual(repeated.ledger_id, place.ledger_id)
        self.assertEqual(repeated.execution_audit_id, place.execution_audit_id)
        due_at = self.fill_at+timedelta(hours=1)
        self.assertEqual(self._close_at(due_at), 1)
        self.assertEqual(self._close_at(due_at+timedelta(minutes=5)), 0)
        with self.SessionLocal() as session:
            self.assertEqual(len(session.scalars(select(PaperPositionORM)).all()), 1)
            self.assertEqual(len(session.scalars(select(ExecutionAuditORM)).all()), 1)

    def test_buy_without_evidence_remains_blocked_through_preview_and_place(self):
        row = self._store_hybrid_buy(evidence=False)
        self.assertFalse(row.is_top_pick)
        self.assertFalse(all(check.passed for check in paper_action_checks(row)))
        preview = asyncio.run(self.execution.preview(OrderPreviewRequest(ticker="AAPL", side="buy", qty=1)))
        self.assertFalse(preview.trade_gate.allowed)
        place = asyncio.run(self.execution.place(OrderPlaceRequest(
            ticker="AAPL", side="buy", qty=1, preview_audit_id=preview.execution_audit_id,
            paper_contract=getattr(preview, "paper_contract", None), idempotency_key="blocked-contract-1",
        )))
        self.assertFalse(place.ok)
        self.assertIsNone(place.ledger_id)
        self.assertEqual(self.repo.list_paper_positions(), [])

    def test_critical_provider_buy_remains_blocked_even_with_passing_evidence(self):
        row = self._store_hybrid_buy(provider_status="critical")
        self.assertTrue(row.gate_passed)
        self.assertFalse(row.is_top_pick)
        preview = asyncio.run(self.execution.preview(OrderPreviewRequest(ticker="AAPL", side="buy", qty=1)))
        self.assertFalse(preview.trade_gate.allowed)
        self.assertTrue(any(not check.passed for check in preview.trade_gate.gate_checks if check.name.startswith("paper_")))

    def test_missing_or_invalid_exit_quote_keeps_due_position_pending(self):
        self._store_hybrid_buy()
        self._preview_and_place()
        observed_at = self.fill_at+timedelta(hours=1, minutes=5)
        for quote in (None, 0.0, -1.0, float("nan"), float("inf"), RuntimeError("mock unavailable")):
            with self.subTest(quote=quote):
                self.scanner.alpaca.get_latest_price.side_effect = quote if isinstance(quote, Exception) else None
                self.scanner.alpaca.get_latest_price.return_value = quote
                self.assertEqual(self._close_at(observed_at), 0)
                position = self.repo.list_paper_positions(observed_at=observed_at)[0]
                self.assertEqual(position.status, "open")
                self.assertEqual(position.closure_status, "overdue_pending_quote")
                self.assertIsNone(position.close_price)
                self.assertIsNone(position.closed_at)
                self.assertIsNone(position.realized_pnl)
                summary = self.repo.get_paper_ledger_summary(observed_at=observed_at)
                self.assertEqual(summary.closed_positions, 0)
                self.assertEqual(summary.open_positions, 1)
                self.assertEqual(summary.overdue_positions, 1)
                self.assertEqual(summary.gross_pnl_usd, 0.0)

    def test_generated_preview_obeys_current_quantity_and_notional_limits(self):
        self._store_hybrid_buy()
        for quote, budget in ((10.0, 100.0), (300.0, 100.0), (300.0, 10000.0), (33.333333, 100.0)):
            with self.subTest(quote=quote, budget=budget):
                self.execution.alpaca.get_latest_price.return_value = quote
                preview = asyncio.run(self.execution.preview(OrderPreviewRequest(
                    ticker="AAPL", side="buy", requested_notional_usd=budget,
                )))
                self.assertTrue(preview.trade_gate.allowed, preview.trade_gate.reason)
                self.assertGreater(preview.qty, 0)
                self.assertLessEqual(preview.qty, self.settings.trade_gate_max_qty)
                self.assertLessEqual(preview.notional_estimate, self.settings.trade_gate_max_notional)
                if quote == 300.0 and budget == 100.0:
                    self.assertLess(preview.qty, 1.0)
        # Explicit oversize quantities still go through the same real risk gate.
        explicit = asyncio.run(self.execution.preview(OrderPreviewRequest(
            ticker="AAPL", side="buy", qty=self.settings.trade_gate_max_qty+1,
        )))
        self.assertFalse(explicit.trade_gate.allowed)
        self.execution.alpaca.get_latest_price.return_value = 60000.0
        explicit_notional = asyncio.run(self.execution.preview(OrderPreviewRequest(
            ticker="AAPL", side="buy", qty=1.0,
        )))
        self.assertFalse(explicit_notional.trade_gate.allowed)

    def test_generated_crypto_preview_keeps_fractional_quantity(self):
        self._store_hybrid_buy(ticker="BTC/USD", asset_type="crypto")
        self.execution.alpaca.get_latest_crypto_price.return_value = 60000.0
        preview = asyncio.run(self.execution.preview(OrderPreviewRequest(
            ticker="BTC/USD", side="buy", requested_notional_usd=100.0,
        )))
        self.assertTrue(preview.trade_gate.allowed, preview.trade_gate.reason)
        self.assertGreater(preview.qty, 0)
        self.assertLess(preview.qty, 1)
        self.assertLessEqual(preview.notional_estimate, 100.0)

    def test_horizon_changed_before_placement_rejects_unagreed_contract(self):
        self._store_hybrid_buy()
        preview = asyncio.run(self.execution.preview(OrderPreviewRequest(ticker="AAPL", side="buy", qty=1)))
        self.settings.trade_gate_horizon = "1d"
        with self.assertRaises(AppError) as error:
            asyncio.run(self.execution.place(OrderPlaceRequest(
                ticker="AAPL", side="buy", qty=preview.qty,
                preview_audit_id=preview.execution_audit_id,
                paper_contract=preview.paper_contract, idempotency_key="changed-horizon-1",
            )))
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.repo.list_paper_positions(), [])
        with self.SessionLocal() as session:
            audit = session.scalar(select(ExecutionAuditORM))
        self.assertEqual(audit.lifecycle_status, "previewed")

    def test_position_persistence_failure_cannot_claim_success_and_can_retry(self):
        self._store_hybrid_buy()
        preview = asyncio.run(self.execution.preview(OrderPreviewRequest(ticker="AAPL", side="buy", qty=1)))
        request = OrderPlaceRequest(
            ticker="AAPL", side="buy", qty=preview.qty,
            preview_audit_id=preview.execution_audit_id, paper_contract=preview.paper_contract,
            idempotency_key="retry-persistence-1",
        )
        with patch.object(self.repo, "record_paper_position_from_audit", side_effect=RuntimeError("mock storage failure")):
            with self.assertLogs("app.services.execution", level="ERROR"):
                with self.assertRaises(AppError) as error:
                    asyncio.run(self.execution.place(request))
        self.assertEqual(error.exception.code, "paper_position_persistence_failed")
        self.assertEqual(self.repo.list_paper_positions(), [])
        with self.SessionLocal() as session:
            audit = session.scalar(select(ExecutionAuditORM))
        self.assertNotEqual(audit.lifecycle_status, "dry_run")
        place = asyncio.run(self.execution.place(request))
        self.assertTrue(place.ok)
        self.assertEqual(len(self.repo.list_paper_positions()), 1)

    def test_subprecision_generated_budget_has_no_fabricated_quantity(self):
        self._store_hybrid_buy(ticker="BTC/USD", asset_type="crypto")
        self.execution.alpaca.get_latest_crypto_price.return_value = 60000.0
        with self.assertRaises(AppError) as error:
            asyncio.run(self.execution.preview(OrderPreviewRequest(
                ticker="BTC/USD", side="buy", requested_notional_usd=0.001,
            )))
        self.assertEqual(error.exception.code, "unable_to_size")
        self.assertEqual(self.repo.list_paper_positions(), [])


if __name__ == "__main__":
    unittest.main()
