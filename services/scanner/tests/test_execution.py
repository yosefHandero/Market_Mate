import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.automation_repository as automation_repository_module
import app.services.execution as execution_module
import app.services.repository as repository_module
from app.db import Base
from app.errors import AppError
from app.models.scan import ExecutionAuditORM, PaperPositionORM
from app.schemas import OrderPlaceRequest, TradeEligibility
from app.services.execution import ExecutionService


class ExecutionServiceTests(unittest.TestCase):
    def test_preview_persists_trade_gate_linkage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                service = ExecutionService()
                service.alpaca.get_latest_price = AsyncMock(return_value=190.0)
                service.risk.evaluate_trade = lambda **_: TradeEligibility(
                    ticker="AAPL",
                    asset_type="stock",
                    requested_side="buy",
                    required_signal="BUY",
                    signal_outcome_id=99,
                    signal_run_id="run-123",
                    signal_generated_at=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
                    latest_signal="BUY",
                    confidence=72.0,
                    calibration_source="signal",
                    raw_score=68.0,
                    signal_age_minutes=5.0,
                    confidence_bucket="60-74",
                    raw_score_bucket="60-74",
                    score_band="60-69",
                    horizon="1h",
                    evidence_basis="recent_window:14d:generated_at",
                    trust_window_start=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
                    trust_window_end=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
                    allowed=False,
                    reason="blocked",
                    notional_estimate=190.0,
                    qty=1.0,
                )

                with patch.object(execution_module, "SessionLocal", SessionLocal):
                    preview = asyncio.run(
                        service.preview(
                            execution_module.OrderPreviewRequest(
                                ticker="AAPL",
                                side="buy",
                                qty=1,
                            )
                        )
                    )
                    with SessionLocal() as session:
                        audit = session.query(ExecutionAuditORM).one()

                self.assertIsNotNone(preview.execution_audit_id)
                self.assertTrue(audit.dry_run)
                self.assertEqual(audit.signal_outcome_id, 99)
                self.assertEqual(audit.signal_run_id, "run-123")
                self.assertEqual(audit.trade_gate_horizon, "1h")
                self.assertEqual(audit.evidence_basis, "recent_window:14d:generated_at")
                self.assertIsNotNone(audit.trust_window_start)
                self.assertIsNotNone(audit.trust_window_end)
            finally:
                engine.dispose()

    def test_place_rejects_non_dry_run_at_service_layer(self) -> None:
        service = ExecutionService()
        service.alpaca.get_latest_price = AsyncMock()
        service.alpaca.submit_order = AsyncMock()

        with self.assertRaises(AppError) as ctx:
            asyncio.run(
                service.place(
                    OrderPlaceRequest(
                        ticker="AAPL",
                        side="buy",
                        qty=1,
                    )
                )
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.code, "dry_run_required")
        service.alpaca.get_latest_price.assert_not_awaited()
        service.alpaca.submit_order.assert_not_awaited()

    def test_place_reuses_existing_idempotent_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                with SessionLocal() as session:
                    session.add(
                        ExecutionAuditORM(
                            created_at=datetime(2026, 3, 20, 12, 0),
                            updated_at=datetime(2026, 3, 20, 12, 1),
                            ticker="AAPL",
                            asset_type="stock",
                            side="buy",
                            order_type="market",
                            qty=1.0,
                            dry_run=True,
                            idempotency_key="reused-key-123",
                            lifecycle_status="dry_run",
                            latest_price=190.0,
                            notional_estimate=190.0,
                            submitted=False,
                            broker_status="dry_run",
                            preview_payload="{}",
                        )
                    )
                    session.commit()

                service = ExecutionService()
                service.alpaca.get_latest_price = AsyncMock(return_value=190.0)

                with patch.object(execution_module, "SessionLocal", SessionLocal):
                    response = asyncio.run(
                        service.place(
                            execution_module.OrderPlaceRequest(
                                ticker="AAPL",
                                side="buy",
                                qty=1,
                                dry_run=True,
                                idempotency_key="reused-key-123",
                            )
                        )
                    )

                self.assertTrue(response.ok)
                self.assertTrue(response.dry_run)
                self.assertEqual(response.idempotency_key, "reused-key-123")
                self.assertIn("Reused prior", response.message)
            finally:
                engine.dispose()

    def test_place_rejects_idempotency_key_reused_with_different_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                prior_req = OrderPlaceRequest(
                    ticker="AAPL",
                    side="buy",
                    qty=1,
                    dry_run=True,
                    idempotency_key="same-key-abc",
                )
                prior_payload = prior_req.model_dump(mode="json")
                payload_hash = ExecutionService._idempotency_payload_hash(prior_payload)
                with SessionLocal() as session:
                    session.add(
                        ExecutionAuditORM(
                            created_at=datetime(2026, 3, 20, 12, 0),
                            updated_at=datetime(2026, 3, 20, 12, 1),
                            ticker="AAPL",
                            asset_type="stock",
                            side="buy",
                            order_type="market",
                            qty=1.0,
                            dry_run=True,
                            idempotency_key="same-key-abc",
                            idempotency_payload_hash=payload_hash,
                            lifecycle_status="dry_run",
                            latest_price=190.0,
                            notional_estimate=190.0,
                            submitted=False,
                            broker_status="dry_run",
                            preview_payload="{}",
                            request_payload=json.dumps(prior_payload),
                        )
                    )
                    session.commit()

                service = ExecutionService()
                service.settings.require_readyz_for_execution = False

                with patch.object(execution_module, "SessionLocal", SessionLocal):
                    with self.assertRaises(AppError) as ctx:
                        asyncio.run(
                            service.place(
                                OrderPlaceRequest(
                                    ticker="NVDA",
                                    side="buy",
                                    qty=1,
                                    dry_run=True,
                                    idempotency_key="same-key-abc",
                                )
                            )
                        )
                self.assertEqual(ctx.exception.status_code, 409)
                self.assertEqual(ctx.exception.code, "idempotency_payload_mismatch")
            finally:
                engine.dispose()

    def test_dry_run_place_persists_paper_position(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                service = ExecutionService()
                service.settings.require_readyz_for_execution = False
                service.alpaca.get_latest_price = AsyncMock(return_value=190.0)
                service.risk.evaluate_trade = lambda **_: TradeEligibility(
                    ticker="AAPL",
                    asset_type="stock",
                    requested_side="buy",
                    required_signal="BUY",
                    signal_outcome_id=99,
                    signal_run_id="run-123",
                    signal_generated_at=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
                    latest_signal="BUY",
                    confidence=72.0,
                    calibration_source="signal",
                    raw_score=68.0,
                    signal_age_minutes=5.0,
                    confidence_bucket="60-74",
                    raw_score_bucket="60-74",
                    score_band="60-69",
                    horizon="1h",
                    evidence_basis="recent_window:14d:generated_at",
                    trust_window_start=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
                    trust_window_end=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
                    execution_eligibility="eligible",
                    strategy_version="v4.0-layered",
                    allowed=True,
                    reason="Eligible.",
                    notional_estimate=190.0,
                    qty=1.0,
                )

                with patch.object(execution_module, "SessionLocal", SessionLocal), patch.object(
                    automation_repository_module,
                    "SessionLocal",
                    SessionLocal,
                ):
                    response = asyncio.run(
                        service.place(
                            OrderPlaceRequest(
                                ticker="AAPL",
                                side="buy",
                                qty=1,
                                dry_run=True,
                                idempotency_key="manual-1",
                            )
                        )
                    )
                    with SessionLocal() as session:
                        position = session.query(PaperPositionORM).one()

                self.assertTrue(response.dry_run)
                self.assertIsNotNone(response.execution_audit_id)
                self.assertEqual(response.ledger_id, position.id)
                self.assertEqual(response.fill_price, 190.0)
                self.assertEqual(response.filled_qty, 1.0)
                self.assertEqual(position.status, "open")
                self.assertEqual(position.quantity, 1.0)
                self.assertEqual(position.simulated_fill_price, 190.0)
                self.assertEqual(position.intent_key, "manual-1")
                self.assertEqual(position.execution_audit_id, response.execution_audit_id)
                self.assertEqual(position.strategy_version, "v4.0-layered")
            finally:
                engine.dispose()

    def test_dry_run_sell_closes_existing_paper_position_without_double_counting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                opened_at = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)
                with SessionLocal() as session:
                    session.add(
                        PaperPositionORM(
                            created_at=opened_at,
                            updated_at=opened_at,
                            intent_key="manual-open-1",
                            execution_audit_id=None,
                            ticker="AAPL",
                            asset_type="stock",
                            side="buy",
                            quantity=1.0,
                            simulated_fill_price=100.0,
                            notional_usd=100.0,
                            cost_basis_usd=100.0,
                            close_price=None,
                            realized_pnl=None,
                            status="open",
                            opened_at=opened_at,
                            closed_at=None,
                            strategy_version="v4.0-layered",
                            confidence=72.0,
                        )
                    )
                    session.commit()

                service = ExecutionService()
                service.settings.require_readyz_for_execution = False
                service.alpaca.get_latest_price = AsyncMock(return_value=110.0)
                service.risk.evaluate_trade = lambda **_: TradeEligibility(
                    ticker="AAPL",
                    asset_type="stock",
                    requested_side="sell",
                    required_signal="SELL",
                    signal_outcome_id=100,
                    signal_run_id="run-sell-1",
                    signal_generated_at=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
                    latest_signal="SELL",
                    confidence=76.0,
                    calibration_source="signal",
                    raw_score=70.0,
                    signal_age_minutes=3.0,
                    confidence_bucket="75-84",
                    raw_score_bucket="70-79",
                    score_band="70-79",
                    horizon="1h",
                    evidence_basis="recent_window:14d:generated_at",
                    trust_window_start=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
                    trust_window_end=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
                    execution_eligibility="eligible",
                    strategy_version="v4.0-layered",
                    allowed=True,
                    reason="Eligible.",
                    notional_estimate=110.0,
                    qty=1.0,
                )

                with patch.object(execution_module, "SessionLocal", SessionLocal), patch.object(
                    automation_repository_module,
                    "SessionLocal",
                    SessionLocal,
                ), patch.object(repository_module, "SessionLocal", SessionLocal):
                    response = asyncio.run(
                        service.place(
                            OrderPlaceRequest(
                                ticker="AAPL",
                                side="sell",
                                qty=1,
                                dry_run=True,
                                idempotency_key="manual-close-1",
                            )
                        )
                    )
                    summary = repository_module.ScanRepository().get_paper_ledger_summary()
                    with SessionLocal() as session:
                        positions = session.query(PaperPositionORM).all()

                self.assertTrue(response.ok)
                self.assertTrue(response.dry_run)
                self.assertEqual(len(positions), 1)
                self.assertEqual(response.ledger_id, positions[0].id)
                self.assertEqual(positions[0].side, "buy")
                self.assertEqual(positions[0].status, "closed")
                self.assertEqual(positions[0].close_price, 110.0)
                self.assertEqual(positions[0].realized_pnl, 10.0)
                self.assertEqual(summary.open_positions, 0)
                self.assertEqual(summary.closed_positions, 1)
                self.assertEqual(summary.total_count, 1)
                self.assertEqual(summary.win_rate_pct, 100.0)
                self.assertEqual(summary.total_realized_pnl, 10.0)
                self.assertEqual(summary.gross_pnl_usd, 10.0)
            finally:
                engine.dispose()

    def test_sell_audit_without_open_position_does_not_create_closed_ledger_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                now = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
                with SessionLocal() as session:
                    audit = ExecutionAuditORM(
                        created_at=now,
                        updated_at=now,
                        ticker="AAPL",
                        asset_type="stock",
                        side="sell",
                        order_type="market",
                        qty=1.0,
                        dry_run=True,
                        idempotency_key="manual-close-empty",
                        lifecycle_status="dry_run",
                        latest_price=110.0,
                        notional_estimate=110.0,
                        submitted=False,
                        broker_status="dry_run",
                        preview_payload="{}",
                    )
                    session.add(audit)
                    session.commit()
                    audit_id = audit.id

                with patch.object(automation_repository_module, "SessionLocal", SessionLocal):
                    ledger_id = automation_repository_module.AutomationRepository().record_paper_position_from_audit(
                        audit_id=audit_id,
                        simulated_fill_price=110.0,
                    )
                    with SessionLocal() as session:
                        positions = session.query(PaperPositionORM).all()

                self.assertIsNone(ledger_id)
                self.assertEqual(positions, [])
            finally:
                engine.dispose()

    def test_preview_returns_setup_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                service = ExecutionService()
                service.settings.require_readyz_for_execution = False
                service.alpaca.get_latest_price = AsyncMock(return_value=100.0)
                service.risk.evaluate_trade = lambda **_: TradeEligibility(
                    ticker="AAPL",
                    asset_type="stock",
                    requested_side="buy",
                    required_signal="BUY",
                    horizon="1h",
                    execution_eligibility="eligible",
                    latest_scan_fresh=True,
                    allowed=True,
                    reason="Eligible.",
                    notional_estimate=100.0,
                    qty=1.0,
                )

                with patch.object(execution_module, "SessionLocal", SessionLocal):
                    preview = asyncio.run(
                        service.preview(
                            execution_module.OrderPreviewRequest(
                                ticker="AAPL",
                                side="buy",
                                qty=1,
                                mode="dry_run",
                                entry_price=100,
                                stop_price=99,
                                target_price=102,
                            )
                        )
                    )

                self.assertEqual(preview.entry_price, 100)
                self.assertEqual(preview.stop_price, 99)
                self.assertEqual(preview.target_price, 102)
                self.assertEqual(preview.position_size, 1)
                self.assertEqual(preview.estimated_pnl_usd, 2)
                self.assertEqual(preview.gate_result, "allowed")
                self.assertEqual(preview.freshness, "fresh")
                self.assertEqual(preview.reject_reasons, [])
            finally:
                engine.dispose()

    def test_dry_run_place_skips_when_gate_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "scanner.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                future=True,
                connect_args={"check_same_thread": False},
            )
            SessionLocal = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
            Base.metadata.create_all(engine)
            try:
                service = ExecutionService()
                service.settings.require_readyz_for_execution = False
                service.alpaca.get_latest_price = AsyncMock(return_value=190.0)
                service.risk.evaluate_trade = lambda **_: TradeEligibility(
                    ticker="AAPL",
                    asset_type="stock",
                    requested_side="buy",
                    required_signal="BUY",
                    horizon="1h",
                    execution_eligibility="blocked",
                    allowed=False,
                    reason="Signal evidence is stale.",
                    notional_estimate=190.0,
                    qty=1.0,
                )

                with patch.object(execution_module, "SessionLocal", SessionLocal), patch.object(
                    automation_repository_module,
                    "SessionLocal",
                    SessionLocal,
                ):
                    response = asyncio.run(
                        service.place(
                            OrderPlaceRequest(
                                ticker="AAPL",
                                side="buy",
                                qty=1,
                                dry_run=True,
                                idempotency_key="manual-blocked-1",
                            )
                        )
                    )
                    with SessionLocal() as session:
                        positions = session.query(PaperPositionORM).all()

                self.assertFalse(response.ok)
                self.assertTrue(response.dry_run)
                self.assertEqual(positions, [])
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
