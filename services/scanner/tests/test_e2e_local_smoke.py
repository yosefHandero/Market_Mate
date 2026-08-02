"""Local smoke path: persisted scan, operational readiness, and paper ledger (temp DB)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.automation_repository as automation_repository_module
import app.services.readiness as readiness_module
import app.services.repository as repository_module
from app.db import Base, SchemaStatus
from app.models.scan import ExecutionAuditORM, SignalOutcomeORM
from app.schemas import ScanResult, ScanRun
from app.services.automation_repository import AutomationRepository
from app.services.readiness import evaluate_operational_readiness
from app.services.repository import ScanRepository


class LocalE2ESmokeTests(unittest.TestCase):
    def test_scan_persist_readiness_and_partial_ledger_smoke(self) -> None:
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "smoke.db"
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
            repo = ScanRepository()
            automation = AutomationRepository()

            run = ScanRun(
                run_id="smoke-run-1",
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
                        explanation="Smoke fixture",
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

            try:
                with (
                    patch.object(repository_module, "SessionLocal", SessionLocal),
                    patch.object(automation_repository_module, "SessionLocal", SessionLocal),
                    patch.object(
                        readiness_module,
                        "get_schema_status",
                        return_value=SchemaStatus(ok=True, applied_changes=[], missing_items=[]),
                    ),
                ):
                    repo.save_run(run)
                    ready, reason = evaluate_operational_readiness(scan_repository=repo)
                    self.assertTrue(ready, reason)

                    latest = repo.get_latest_run()
                    self.assertIsNotNone(latest)
                    self.assertEqual(latest.run_id, "smoke-run-1")

                    ticker_history = repo.get_ticker_scan_history(ticker="AAPL", limit=10)
                    self.assertEqual(len(ticker_history), 1)
                    self.assertEqual(ticker_history[0].result.ticker, "AAPL")

                    with SessionLocal() as session:
                        outcome = SignalOutcomeORM(
                            run_id="smoke-run-1",
                            ticker="AAPL",
                            asset_type="stock",
                            strategy_variant="smoke-v1",
                            signal="BUY",
                            confidence=80.0,
                            calibrated_confidence=80.0,
                            calibration_source="raw",
                            raw_score=78.0,
                            score_band="80-100",
                            scoring_version="smoke",
                            market_status="bullish",
                            buy_score=80.0,
                            sell_score=20.0,
                            signal_label="smoke",
                            gate_passed=True,
                            gate_reason="Passed",
                            data_grade="decision",
                            entry_price=100.0,
                            generated_at=now.replace(tzinfo=None),
                            price_after_1h=101.25,
                            return_after_1h=1.25,
                            evaluated_at_1h=now.replace(tzinfo=None),
                            status_1h="evaluated",
                        )
                        session.add(outcome)
                        session.commit()

                    evidence = repo.get_ticker_signal_outcome_evidence(
                        ticker="AAPL",
                        horizon="1h",
                        recent_limit=3,
                    )
                    self.assertGreaterEqual(evidence.sample_size, 1)
                    self.assertGreaterEqual(evidence.evaluated_count, 1)
                    self.assertGreaterEqual(evidence.win_count, 1)
                    self.assertTrue(evidence.insufficient_sample)
                    self.assertGreaterEqual(len(evidence.recent_outcomes), 1)

                    with SessionLocal() as session:
                        buy_audit = ExecutionAuditORM(
                            created_at=now.replace(tzinfo=None),
                            updated_at=now.replace(tzinfo=None),
                            ticker="AAPL",
                            asset_type="stock",
                            side="buy",
                            order_type="market",
                            qty=2.0,
                            dry_run=True,
                            lifecycle_status="filled",
                            confidence=80.0,
                        )
                        session.add(buy_audit)
                        session.commit()
                        session.refresh(buy_audit)
                        buy_audit_id = buy_audit.id

                    buy_ledger = automation.record_paper_position_from_audit(
                        audit_id=buy_audit_id,
                        simulated_fill_price=100.0,
                        filled_at=now.replace(tzinfo=None),
                    )
                    self.assertIsNotNone(buy_ledger)

                    with SessionLocal() as session:
                        sell_audit = ExecutionAuditORM(
                            created_at=now.replace(tzinfo=None),
                            updated_at=now.replace(tzinfo=None),
                            ticker="AAPL",
                            asset_type="stock",
                            side="sell",
                            order_type="market",
                            qty=1.0,
                            dry_run=True,
                            lifecycle_status="filled",
                            confidence=80.0,
                        )
                        session.add(sell_audit)
                        session.commit()
                        session.refresh(sell_audit)
                        sell_audit_id = sell_audit.id

                    partial_ledger = automation.record_paper_position_from_audit(
                        audit_id=sell_audit_id,
                        simulated_fill_price=101.0,
                        filled_at=now.replace(tzinfo=None),
                    )
                    self.assertIsNotNone(partial_ledger)
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
