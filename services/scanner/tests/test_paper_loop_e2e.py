"""End-to-end paper loop: preview -> dry-run place -> ledger -> horizon close -> proof summary."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.automation_repository as automation_repository_module
import app.services.execution as execution_module
import app.services.repository as repository_module
from app.db import Base
from app.models.scan import ExecutionAuditORM, PaperPositionORM, ScanResultORM, ScanRunORM
from app.schemas import OrderPlaceRequest, OrderPreviewRequest, ScanResult, ScanRun, TradeEligibility
from app.services.execution import ExecutionService
from app.services.repository import ScanRepository


class PaperLoopE2ETests(unittest.TestCase):
    def test_preview_place_ledger_horizon_close_and_proof_summary(self) -> None:
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "loop.db"
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
                repo = ScanRepository()
                original_horizon = repo.settings.trade_gate_horizon
                self.addCleanup(setattr, repo.settings, "trade_gate_horizon", original_horizon)
                repo.settings.trade_gate_horizon = "1h"
                run = ScanRun(
                    run_id="loop-run-1",
                    created_at=now,
                    market_status="bullish",
                    scan_count=1,
                    watchlist_size=1,
                    alerts_sent=0,
                    fear_greed_value=55,
                    fear_greed_label="Neutral",
                    results=[
                        ScanResult(
                            ticker="AAPL",
                            asset_type="stock",
                            score=80.0,
                            raw_score=78.0,
                            calibrated_confidence=80.0,
                            decision_signal="BUY",
                            explanation="Loop fixture",
                            price=100.0,
                            price_change_pct=1.0,
                            relative_volume=1.0,
                            relative_strength_pct=0.5,
                            sentiment_score=0.1,
                            filing_flag=False,
                            breakout_flag=True,
                            market_status="bullish",
                            sector_strength_score=0.5,
                            recommended_action="preview",
                            gate_passed=True,
                            created_at=now,
                        )
                    ],
                )

                service = ExecutionService()
                service.settings.require_readyz_for_execution = False
                service.settings.paper_loop_kill_switch = False
                service.alpaca.get_latest_price = AsyncMock(return_value=100.0)
                service.risk.evaluate_trade = lambda **_: TradeEligibility(
                    ticker="AAPL",
                    asset_type="stock",
                    requested_side="buy",
                    required_signal="BUY",
                    signal_outcome_id=1,
                    signal_run_id="loop-run-1",
                    signal_generated_at=now,
                    latest_signal="BUY",
                    confidence=80.0,
                    calibration_source="signal",
                    raw_score=78.0,
                    signal_age_minutes=1.0,
                    confidence_bucket="75-84",
                    raw_score_bucket="70-79",
                    score_band="70-79",
                    horizon="1h",
                    evidence_basis="recent_window:14d:generated_at",
                    trust_window_start=now - timedelta(days=14),
                    trust_window_end=now,
                    allowed=True,
                    reason="Eligible.",
                    notional_estimate=100.0,
                    qty=1.0,
                    strategy_version="test-v1",
                    strategy_id="scanner-directional",
                    strategy_primary_horizon="1h",
                    confidence_label="moderate_evidence",
                    execution_eligibility="eligible",
                )

                with (
                    patch.object(repository_module, "SessionLocal", SessionLocal),
                    patch.object(execution_module, "SessionLocal", SessionLocal),
                    patch.object(automation_repository_module, "SessionLocal", SessionLocal),
                ):
                    repo.save_run(run)
                    preview = asyncio.run(
                        service.preview(
                            OrderPreviewRequest(ticker="AAPL", side="buy", qty=1, dry_run=True)
                        )
                    )
                    place = asyncio.run(
                        service.place(
                            OrderPlaceRequest(
                                ticker="AAPL",
                                side="buy",
                                qty=1,
                                dry_run=True,
                                idempotency_key="loop-e2e-1",
                                preview_audit_id=preview.execution_audit_id,
                            )
                        )
                    )

                    self.assertTrue(place.ok)
                    self.assertTrue(place.dry_run)
                    self.assertIsNotNone(place.ledger_id)

                    positions = repo.list_paper_positions(status="open")
                    self.assertEqual(len(positions), 1)
                    self.assertEqual(positions[0].ticker, "AAPL")

                    audits = repo.list_execution_audits(limit=10)
                    self.assertGreaterEqual(len(audits), 1)

                    with SessionLocal() as session:
                        position = session.get(PaperPositionORM, place.ledger_id)
                        assert position is not None
                        position.opened_at = (now - timedelta(hours=2)).replace(tzinfo=None)
                        session.commit()

                    closed = repo.close_open_positions_past_horizon(
                        observed_at=now,
                        market_prices={"AAPL": 105.0},
                    )
                    self.assertEqual(closed, 1)

                    summary = repo.get_paper_ledger_summary(mark_prices={"AAPL": 105.0})
                    self.assertEqual(summary.closed_positions, 1)
                    self.assertEqual(summary.total_realized_pnl, 5.0)
                    self.assertEqual(summary.open_positions, 0)

                    with SessionLocal() as session:
                        closed_position = session.query(PaperPositionORM).one()
                    self.assertEqual(closed_position.close_price, 105.0)
                    self.assertEqual(closed_position.realized_pnl, 5.0)
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
