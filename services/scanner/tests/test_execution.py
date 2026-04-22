import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.execution as execution_module
from app.db import Base
from app.errors import AppError
from app.models.scan import ExecutionAuditORM
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
                self.assertEqual(audit.signal_outcome_id, 99)
                self.assertEqual(audit.signal_run_id, "run-123")
                self.assertEqual(audit.trade_gate_horizon, "1h")
                self.assertEqual(audit.evidence_basis, "recent_window:14d:generated_at")
                self.assertIsNotNone(audit.trust_window_start)
                self.assertIsNotNone(audit.trust_window_end)
            finally:
                engine.dispose()

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


if __name__ == "__main__":
    unittest.main()
