"""Saved paper contracts close at actual usable quotes, without historical guesses."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.automation_repository as automation_repository_module
import app.services.repository as repository_module
import app.services.scanner as scanner_module
from app.db import Base
from app.models.scan import AutomationIntentORM, ExecutionAuditORM
from app.services.automation_repository import AutomationRepository
from app.services.scanner import ScannerService


class PaperHorizonCloseTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_engine(f"sqlite:///{(Path(directory.name) / 'paper.db').as_posix()}")
        self.addCleanup(self.engine.dispose)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        for module in (repository_module, automation_repository_module):
            patcher = patch.object(module, "SessionLocal", self.sessions)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.repo = repository_module.ScanRepository()
        self.writer = AutomationRepository()
        original_horizon = self.repo.settings.trade_gate_horizon
        self.addCleanup(setattr, self.repo.settings, "trade_gate_horizon", original_horizon)
        self.repo.settings.trade_gate_horizon = "1h"
        self.fill_time = datetime(2026, 10, 11, 12, 8, 30, tzinfo=timezone.utc)

    def _audit(self, *, contract: bool = True) -> int:
        paper_contract = {
            "source_run_id": "qualifying-run",
            "policy_id": "hybrid_legacy",
            "policy_version": "hybrid-v4.3",
            "decision_fingerprint": "saved-decision-fingerprint",
            "holding_horizon": "1h",
            "holding_duration_seconds": 3600,
            "exit_method": "time_based",
        }
        preview = {"trade_gate": {"strategy_version": "hybrid-v4.3"}}
        if contract:
            preview["paper_contract"] = paper_contract
        with self.sessions() as session:
            audit = ExecutionAuditORM(
                created_at=self.fill_time - timedelta(minutes=8),
                updated_at=self.fill_time,
                ticker="AAPL", asset_type="stock", side="buy", order_type="market",
                qty=2.0, dry_run=True, idempotency_key="contract-buy",
                lifecycle_status="dry_run", latest_price=100.0,
                notional_estimate=200.0, signal_run_id="qualifying-run",
                trade_gate_horizon="1h", trade_gate_allowed=True,
                preview_payload=json.dumps(preview),
            )
            session.add(audit)
            session.commit()
            return audit.id

    def _position(self, *, contract: bool = True) -> tuple[int, int]:
        audit_id = self._audit(contract=contract)
        position_id = self.writer.record_paper_position_from_audit(
            audit_id=audit_id, simulated_fill_price=100.0, filled_at=self.fill_time,
        )
        self.assertIsNotNone(position_id)
        return audit_id, position_id

    def test_agreed_terms_identity_and_deadline_use_actual_fill(self) -> None:
        audit_id, position_id = self._position()
        rows = self.repo.list_paper_positions(observed_at=self.fill_time)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.source_run_id, "qualifying-run")
        self.assertEqual(row.policy_id, "hybrid_legacy")
        self.assertEqual(row.policy_version, "hybrid-v4.3")
        self.assertEqual(row.decision_fingerprint, "saved-decision-fingerprint")
        self.assertEqual(row.holding_horizon, "1h")
        self.assertEqual(row.holding_duration_seconds, 3600)
        self.assertEqual(row.exit_method, "time_based")
        self.assertEqual(row.exit_due_at.replace(tzinfo=timezone.utc), self.fill_time + timedelta(hours=1))
        self.assertEqual(row.contract_status, "recorded")
        self.assertEqual(row.closure_status, "scheduled")
        repeated = self.writer.record_paper_position_from_audit(
            audit_id=audit_id, simulated_fill_price=999.0,
            filled_at=self.fill_time + timedelta(hours=4),
        )
        self.assertEqual(repeated, position_id)
        self.assertEqual(self.repo.list_paper_positions()[0].simulated_fill_price, 100.0)
        self.assertEqual(len(self.repo.list_paper_positions()), 1)

    def test_saved_deadline_ignores_later_config_and_opened_time_changes(self) -> None:
        _, position_id = self._position()
        self.repo.settings.trade_gate_horizon = "1w"
        before = self.fill_time + timedelta(minutes=59)
        self.assertEqual(self.repo.list_paper_positions_due_for_horizon_close(observed_at=before), [])
        due_at = self.fill_time + timedelta(hours=1)
        due = self.repo.list_paper_positions_due_for_horizon_close(observed_at=due_at)
        self.assertEqual([item.id for item in due], [position_id])
        self.assertEqual(self.repo.close_open_positions_past_horizon(
            observed_at=due_at, market_prices={"AAPL": 110.0},
        ), 1)
        row = self.repo.list_paper_positions()[0]
        self.assertEqual(row.holding_horizon, "1h")
        self.assertEqual(row.realized_pnl, 20.0)
        self.assertEqual(row.close_delay_seconds, 0.0)

    def test_automation_and_manual_writers_share_one_audit_contract_without_duplicate(self) -> None:
        audit_id = self._audit()
        with self.sessions() as session:
            intent = AutomationIntentORM(
                created_at=self.fill_time, updated_at=self.fill_time, run_id="qualifying-run",
                symbol="AAPL", asset_type="stock", side="buy", qty=2.0,
                intent_key="automation-intent", intent_hash="hash", status="dry_run_complete",
                execution_audit_id=audit_id,
            )
            session.add(intent)
            session.commit()
            intent_id = intent.id
        position_id = self.writer.record_paper_position(
            intent_id=intent_id, simulated_fill_price=100.0, filled_at=self.fill_time,
        )
        repeated = self.writer.record_paper_position_from_audit(
            audit_id=audit_id, simulated_fill_price=110.0,
            filled_at=self.fill_time + timedelta(hours=2),
        )
        self.assertEqual(repeated, position_id)
        rows = self.repo.list_paper_positions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source_run_id, "qualifying-run")
        self.assertEqual(rows[0].policy_id, "hybrid_legacy")
        self.assertEqual(rows[0].holding_duration_seconds, 3600)
        self.assertEqual(rows[0].simulated_fill_price, 100.0)
        self.assertEqual(rows[0].exit_due_at.replace(tzinfo=timezone.utc), self.fill_time + timedelta(hours=1))

    def test_malformed_saved_contract_is_not_reinterpreted_as_current_configuration(self) -> None:
        audit_id = self._audit()
        with self.sessions() as session:
            audit = session.get(ExecutionAuditORM, audit_id)
            payload = json.loads(audit.preview_payload)
            payload["paper_contract"]["holding_duration_seconds"] = 7200
            audit.preview_payload = json.dumps(payload)
            session.commit()
        self.writer.record_paper_position_from_audit(
            audit_id=audit_id, simulated_fill_price=100.0, filled_at=self.fill_time,
        )
        row = self.repo.list_paper_positions()[0]
        self.assertEqual(row.contract_status, "legacy_unknown")
        self.assertIsNone(row.exit_due_at)
        self.assertIsNone(row.holding_duration_seconds)

    def test_late_quote_actual_close_time_and_gross_result_are_visible_and_idempotent(self) -> None:
        _, position_id = self._position()
        due_at = self.fill_time + timedelta(hours=1)
        actual_close = due_at + timedelta(minutes=9, seconds=3)
        self.assertEqual(self.repo.close_open_positions_past_horizon(
            observed_at=due_at, market_prices={"AAPL": 110.0},
            market_observed_at={"AAPL": actual_close},
        ), 1)
        self.assertEqual(self.repo.close_open_positions_past_horizon(
            observed_at=actual_close + timedelta(minutes=3), market_prices={"AAPL": 50.0},
        ), 0)
        row = self.repo.list_paper_positions()[0]
        self.assertEqual(row.id, position_id)
        self.assertEqual(row.closed_at.replace(tzinfo=timezone.utc), actual_close)
        self.assertEqual(row.close_price, 110.0)
        self.assertEqual(row.realized_pnl, 20.0)
        self.assertEqual(row.closure_status, "closed_late")
        self.assertEqual(row.close_delay_seconds, 543.0)
        summary = self.repo.get_paper_ledger_summary(observed_at=actual_close)
        self.assertEqual(summary.gross_pnl_usd, 20.0)
        self.assertEqual(summary.total_realized_pnl, 20.0)
        self.assertEqual(summary.closed_positions, 1)
        self.assertEqual(summary.late_closed_positions, 1)

    def test_missing_or_invalid_quote_keeps_honest_overdue_position(self) -> None:
        self._position()
        observed = self.fill_time + timedelta(hours=2)
        for prices in (None, {}, {"AAPL": 0.0}, {"AAPL": -1.0}, {"AAPL": float("nan")}, {"AAPL": float("inf")}):
            with self.subTest(prices=prices):
                self.assertEqual(self.repo.close_open_positions_past_horizon(
                    observed_at=observed, market_prices=prices,
                ), 0)
        row = self.repo.list_paper_positions(observed_at=observed)[0]
        self.assertEqual(row.status, "open")
        self.assertEqual(row.closure_status, "overdue_pending_quote")
        self.assertIsNone(row.close_price)
        self.assertIsNone(row.closed_at)
        self.assertIsNone(row.realized_pnl)
        summary = self.repo.get_paper_ledger_summary(observed_at=observed)
        self.assertEqual(summary.overdue_positions, 1)
        self.assertEqual(summary.closed_positions, 0)
        self.assertEqual(summary.gross_pnl_usd, 0.0)

    def test_legacy_position_has_unknown_contract_and_requires_manual_review(self) -> None:
        self._position(contract=False)
        observed = self.fill_time + timedelta(days=30)
        self.assertEqual(self.repo.list_paper_positions_due_for_horizon_close(observed_at=observed), [])
        self.assertEqual(self.repo.close_open_positions_past_horizon(
            observed_at=observed, market_prices={"AAPL": 110.0},
        ), 0)
        row = self.repo.list_paper_positions(observed_at=observed)[0]
        self.assertEqual(row.contract_status, "legacy_unknown")
        self.assertEqual(row.closure_status, "legacy_unknown")
        self.assertIsNone(row.holding_horizon)
        self.assertIsNone(row.exit_due_at)
        self.assertIsNone(row.policy_id)
        self.assertIsNone(row.realized_pnl)
        self.assertEqual(self.repo.get_paper_ledger_summary().legacy_unknown_positions, 1)

    def test_actual_scanner_close_path_with_mocked_provider_exception_stays_pending(self) -> None:
        self._position()
        service = ScannerService()
        service.repo = self.repo
        service.alpaca.get_latest_price = AsyncMock(side_effect=RuntimeError("no usable quote"))
        closed = asyncio.run(service.close_open_positions_past_horizon(
            observed_at=self.fill_time + timedelta(hours=2),
        ))
        self.assertEqual(closed, 0)
        service.alpaca.get_latest_price.assert_awaited_once_with("AAPL")
        self.assertEqual(self.repo.list_paper_positions()[0].status, "open")

    def test_actual_scanner_close_path_records_quote_observation_time(self) -> None:
        self._position()
        due_at = self.fill_time + timedelta(hours=1)
        quote_observed_at = due_at + timedelta(seconds=17)
        service = ScannerService()
        service.repo = self.repo
        service.alpaca.get_latest_price = AsyncMock(return_value=110.0)
        with patch.object(scanner_module, "datetime", wraps=datetime) as clock:
            clock.now.return_value = quote_observed_at
            closed = asyncio.run(service.close_open_positions_past_horizon(observed_at=due_at))
        self.assertEqual(closed, 1)
        row = self.repo.list_paper_positions()[0]
        self.assertEqual(row.closed_at.replace(tzinfo=timezone.utc), quote_observed_at)
        self.assertEqual(row.close_delay_seconds, 17.0)
        self.assertEqual(row.realized_pnl, 20.0)

    def test_safe_repair_requires_actual_fill_receipt_and_never_invents_legacy_fill(self) -> None:
        self._audit(contract=False)
        report = self.repo.repair_paper_reconcile_safe()
        self.assertEqual(self.repo.list_paper_positions(), [])
        self.assertIn("dry_run_audit_without_ledger", report.issues_by_kind)

    def test_safe_repair_uses_receipt_price_time_and_saved_contract(self) -> None:
        audit_id = self._audit()
        with self.sessions() as session:
            audit = session.get(ExecutionAuditORM, audit_id)
            audit.broker_payload = json.dumps({
                "fill_price": 103.0, "filled_at": self.fill_time.isoformat(),
            })
            session.commit()
        report = self.repo.repair_paper_reconcile_safe()
        self.assertTrue(report.ok)
        row = self.repo.list_paper_positions()[0]
        self.assertEqual(row.simulated_fill_price, 103.0)
        self.assertEqual(row.opened_at.replace(tzinfo=timezone.utc), self.fill_time)
        self.assertEqual(row.exit_due_at.replace(tzinfo=timezone.utc), self.fill_time + timedelta(hours=1))
        self.repo.repair_paper_reconcile_safe()
        self.assertEqual(len(self.repo.list_paper_positions()), 1)


if __name__ == "__main__":
    unittest.main()
