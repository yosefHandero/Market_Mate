"""Paper position horizon close uses market prices when provided."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.repository as repository_module
from app.db import Base
from app.models.scan import PaperPositionORM


class PaperHorizonCloseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = repository_module.ScanRepository()
        original_horizon = self.repo.settings.trade_gate_horizon
        self.addCleanup(setattr, self.repo.settings, "trade_gate_horizon", original_horizon)
        self.repo.settings.trade_gate_horizon = "1h"

    def test_horizon_close_uses_market_price_not_entry_fill(self) -> None:
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
                opened_at = datetime.now(timezone.utc) - timedelta(hours=2)
                with SessionLocal() as session:
                    session.add(
                        PaperPositionORM(
                            created_at=opened_at,
                            updated_at=opened_at,
                            intent_key="horizon-test-1",
                            execution_audit_id=None,
                            ticker="AAPL",
                            asset_type="stock",
                            side="buy",
                            quantity=2.0,
                            simulated_fill_price=100.0,
                            notional_usd=200.0,
                            cost_basis_usd=200.0,
                            status="open",
                            opened_at=opened_at,
                            strategy_version="test",
                            confidence=70.0,
                        )
                    )
                    session.commit()

                with patch.object(repository_module, "SessionLocal", SessionLocal):
                    closed = self.repo.close_open_positions_past_horizon(
                        observed_at=datetime.now(timezone.utc),
                        market_prices={"AAPL": 110.0},
                    )

                self.assertEqual(closed, 1)
                with SessionLocal() as session:
                    position = session.query(PaperPositionORM).one()
                self.assertEqual(position.status, "closed")
                self.assertEqual(position.close_price, 110.0)
                self.assertEqual(position.realized_pnl, 20.0)

                with patch.object(repository_module, "SessionLocal", SessionLocal):
                    legacy = self.repo.close_open_positions_past_horizon(
                        observed_at=datetime.now(timezone.utc),
                        market_prices=None,
                    )
                self.assertEqual(legacy, 0)
            finally:
                engine.dispose()

    def test_horizon_close_skips_when_market_price_missing(self) -> None:
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
                opened_at = datetime.now(timezone.utc) - timedelta(hours=2)
                with SessionLocal() as session:
                    session.add(
                        PaperPositionORM(
                            created_at=opened_at,
                            updated_at=opened_at,
                            intent_key="horizon-test-2",
                            execution_audit_id=None,
                            ticker="MSFT",
                            asset_type="stock",
                            side="buy",
                            quantity=1.0,
                            simulated_fill_price=100.0,
                            notional_usd=100.0,
                            cost_basis_usd=100.0,
                            status="open",
                            opened_at=opened_at,
                            strategy_version="test",
                            confidence=70.0,
                        )
                    )
                    session.commit()

                with patch.object(repository_module, "SessionLocal", SessionLocal):
                    closed = self.repo.close_open_positions_past_horizon(
                        observed_at=datetime.now(timezone.utc),
                        market_prices={},
                    )

                self.assertEqual(closed, 0)
                with SessionLocal() as session:
                    position = session.query(PaperPositionORM).one()
                self.assertEqual(position.status, "open")
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
