import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.automation_repository as automation_repository_module
from app.db import Base
from app.models.scan import AutomationIntentORM, ExecutionAuditORM, PaperPositionORM
from app.schemas import OrderPlaceResponse, ScanResult, ScanRun
from app.services.automation import AutomationService
from app.services.automation_repository import AutomationRepository


def _build_scan_run(*, run_id: str = "run-1", signal: str = "BUY") -> ScanRun:
    created_at = datetime.now(timezone.utc)
    return ScanRun(
        run_id=run_id,
        created_at=created_at,
        market_status="bullish",
        strategy_variant="layered-v4",
        shadow_enabled=False,
        scan_count=1,
        watchlist_size=1,
        alerts_sent=0,
        fear_greed_value=60,
        fear_greed_label="Greed",
        results=[
            ScanResult(
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
                decision_signal=signal,
                scoring_version="v4.0-layered",
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
                comparison=None,
                created_at=created_at,
            )
        ],
    )


class AutomationServiceTests(unittest.TestCase):
    def _build_session_local(self):
        temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(temp_dir.name) / "scanner.db"
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
        return temp_dir, engine, SessionLocal

    def _build_service(self, place_mock: AsyncMock | None = None) -> AutomationService:
        execution_service = Mock()
        execution_service.place = place_mock or AsyncMock()
        service = AutomationService(
            repository=AutomationRepository(),
            execution_service=execution_service,
        )
        service.settings.paper_loop_enabled = True
        service.settings.paper_loop_phase = "limited"
        service.settings.paper_loop_kill_switch = False
        service.settings.paper_loop_symbol_allowlist = ""
        service.settings.paper_loop_target_notional_usd = 100.0
        service.settings.paper_loop_max_actions_per_cycle = 2
        service.settings.paper_loop_max_requests_per_hour = 6
        service.settings.paper_loop_max_requests_per_day = 20
        service.settings.paper_loop_max_requests_per_symbol_window = 1
        service.settings.paper_loop_symbol_window_seconds = 21600
        service.settings.paper_loop_symbol_cooldown_minutes = 360
        service.settings.paper_loop_signal_stale_after_minutes = 10
        service.settings.paper_loop_same_side_repeat_requires_delta = True
        service.settings.paper_loop_opposite_side_requires_unwound = True
        service.settings.paper_loop_min_confidence_delta = 5.0
        service.settings.paper_loop_claim_ttl_seconds = 90
        service.settings.paper_loop_retry_max_attempts = 3
        service.settings.paper_loop_retry_base_seconds = 300
        service.settings.paper_loop_retry_jitter_ratio = 0.2
        service.settings.paper_loop_breaker_failures_to_open = 3
        service.settings.paper_loop_breaker_failure_window_minutes = 15
        service.settings.paper_loop_breaker_open_minutes = 30
        service.settings.trade_gate_max_qty = 5.0
        service.settings.app_instance_id = "scanner-test"
        return service

    def _add_execution_audit(self, session, *, now: datetime, **overrides) -> ExecutionAuditORM:
        values = {
            "created_at": now,
            "updated_at": now,
            "ticker": "AAPL",
            "asset_type": "stock",
            "side": "sell",
            "order_type": "market",
            "qty": 1.0,
            "dry_run": True,
            "idempotency_key": "paperloop:sell-without-open",
            "lifecycle_status": "dry_run",
            "latest_price": 200.0,
            "notional_estimate": 200.0,
            "trade_gate_allowed": True,
            "submitted": False,
            "broker_status": "dry_run",
            "preview_payload": json.dumps({"trade_gate": {"strategy_version": "v4.0-layered"}}),
        }
        values.update(overrides)
        audit = ExecutionAuditORM(**values)
        session.add(audit)
        session.flush()
        return audit

    def _add_intent_for_audit(self, session, *, now: datetime, audit: ExecutionAuditORM) -> AutomationIntentORM:
        intent = AutomationIntentORM(
            created_at=now,
            updated_at=now,
            run_id="run-sell-without-open",
            symbol=audit.ticker,
            asset_type=audit.asset_type,
            side=audit.side,
            qty=audit.qty,
            strategy_version="v4.0-layered",
            confidence=80.0,
            horizon="1h",
            intent_key=audit.idempotency_key or f"manual-audit-{audit.id}",
            intent_hash="hash",
            status="pending",
            idempotency_key=audit.idempotency_key,
            execution_audit_id=audit.id,
            request_payload_json=json.dumps(
                {
                    "ticker": audit.ticker,
                    "side": audit.side,
                    "qty": audit.qty,
                    "order_type": "market",
                    "dry_run": True,
                    "idempotency_key": audit.idempotency_key,
                }
            ),
        )
        session.add(intent)
        session.flush()
        return intent

    def test_shadow_mode_records_intent_without_execution_call(self) -> None:
        temp_dir, engine, SessionLocal = self._build_session_local()
        try:
            place_mock = AsyncMock()
            service = self._build_service(place_mock=place_mock)
            service.settings.paper_loop_phase = "shadow"
            run = _build_scan_run()

            with patch.object(automation_repository_module, "SessionLocal", SessionLocal):
                asyncio.run(service.process_completed_run(run))
                with SessionLocal() as session:
                    intent = session.query(AutomationIntentORM).one()

            self.assertEqual(intent.status, "shadowed")
            self.assertEqual(intent.request_count_avoided, 1)
            place_mock.assert_not_awaited()
        finally:
            engine.dispose()
            temp_dir.cleanup()

    def test_duplicate_run_reuses_same_intent_without_second_execution(self) -> None:
        temp_dir, engine, SessionLocal = self._build_session_local()
        try:
            place_mock = AsyncMock(
                return_value=OrderPlaceResponse(
                    ok=True,
                    submitted=False,
                    dry_run=True,
                    message="Dry run only. Order was not sent to Alpaca.",
                    idempotency_key="paperloop:test",
                    execution_audit_id=11,
                )
            )
            service = self._build_service(place_mock=place_mock)
            run = _build_scan_run(run_id="run-dedupe")

            with patch.object(automation_repository_module, "SessionLocal", SessionLocal):
                asyncio.run(service.process_completed_run(run))
                asyncio.run(service.process_completed_run(run))
                with SessionLocal() as session:
                    intents = session.query(AutomationIntentORM).all()

            self.assertEqual(len(intents), 1)
            self.assertEqual(intents[0].status, "dry_run_complete")
            place_mock.assert_awaited_once()
        finally:
            engine.dispose()
            temp_dir.cleanup()

    def test_hourly_budget_blocks_new_request(self) -> None:
        temp_dir, engine, SessionLocal = self._build_session_local()
        try:
            place_mock = AsyncMock()
            service = self._build_service(place_mock=place_mock)
            run = _build_scan_run(run_id="run-budget")
            now = datetime.now(timezone.utc)

            with patch.object(automation_repository_module, "SessionLocal", SessionLocal):
                with SessionLocal() as session:
                    session.add(
                        AutomationIntentORM(
                            created_at=now,
                            updated_at=now,
                            run_id="previous-run",
                            symbol="MSFT",
                            asset_type="stock",
                            side="buy",
                            qty=1.0,
                            strategy_version="v4.0-layered",
                            confidence=80.0,
                            horizon="1h",
                            intent_key="previous-key",
                            intent_hash="hash",
                            status="dry_run_complete",
                            status_reason="done",
                            idempotency_key="previous-key",
                            request_count_used=service.settings.paper_loop_max_requests_per_hour,
                            last_attempt_at=now,
                        )
                    )
                    session.commit()

                asyncio.run(service.process_completed_run(run))

                with SessionLocal() as session:
                    intents = (
                        session.query(AutomationIntentORM)
                        .filter(AutomationIntentORM.run_id == "run-budget")
                        .all()
                    )

            self.assertEqual(len(intents), 1)
            self.assertEqual(intents[0].status, "blocked_by_budget")
            self.assertEqual(intents[0].request_count_avoided, 1)
            place_mock.assert_not_awaited()
        finally:
            engine.dispose()
            temp_dir.cleanup()

    def test_stale_signal_blocks_new_request(self) -> None:
        temp_dir, engine, SessionLocal = self._build_session_local()
        try:
            place_mock = AsyncMock()
            service = self._build_service(place_mock=place_mock)
            run = _build_scan_run(run_id="run-stale")
            run.results[0].created_at = datetime.now(timezone.utc) - timedelta(minutes=30)
            service.settings.stale_signal_max_age_minutes = 10

            with patch.object(automation_repository_module, "SessionLocal", SessionLocal):
                asyncio.run(service.process_completed_run(run))
                with SessionLocal() as session:
                    intent = session.query(AutomationIntentORM).filter_by(run_id="run-stale").one()

            self.assertEqual(intent.status, "stale_signal")
            self.assertEqual(intent.incident_class, "stale_signal")
            place_mock.assert_not_awaited()
        finally:
            engine.dispose()
            temp_dir.cleanup()

    def test_degraded_provider_row_never_reaches_execution(self) -> None:
        temp_dir, engine, SessionLocal = self._build_session_local()
        try:
            place_mock = AsyncMock()
            service = self._build_service(place_mock=place_mock)
            run = _build_scan_run(run_id="run-degraded")
            run.results[0].provider_status = "degraded"

            with patch.object(automation_repository_module, "SessionLocal", SessionLocal):
                asyncio.run(service.process_completed_run(run))
                with SessionLocal() as session:
                    intents = session.query(AutomationIntentORM).filter_by(run_id="run-degraded").all()

            self.assertEqual(intents, [])
            place_mock.assert_not_awaited()
        finally:
            engine.dispose()
            temp_dir.cleanup()

    def test_recovery_reuses_existing_execution_audit_without_new_request(self) -> None:
        temp_dir, engine, SessionLocal = self._build_session_local()
        try:
            place_mock = AsyncMock()
            service = self._build_service(place_mock=place_mock)
            now = datetime.now(timezone.utc)
            idempotency_key = "paperloop:recover:aapl:buy:0.500000:v4.0-layered:1h"

            with patch.object(automation_repository_module, "SessionLocal", SessionLocal):
                with SessionLocal() as session:
                    session.add(
                        AutomationIntentORM(
                            created_at=now - timedelta(minutes=5),
                            updated_at=now - timedelta(minutes=5),
                            run_id="run-recover",
                            symbol="AAPL",
                            asset_type="stock",
                            side="buy",
                            qty=0.5,
                            strategy_version="v4.0-layered",
                            confidence=82.0,
                            horizon="1h",
                            intent_key=idempotency_key,
                            intent_hash="hash",
                            status="failed_retryable",
                            status_reason="network",
                            idempotency_key=idempotency_key,
                            request_payload_json=json.dumps(
                                {
                                    "ticker": "AAPL",
                                    "side": "buy",
                                    "qty": 0.5,
                                    "order_type": "market",
                                    "dry_run": True,
                                    "idempotency_key": idempotency_key,
                                }
                            ),
                            next_retry_at=now - timedelta(minutes=1),
                        )
                    )
                    session.add(
                        ExecutionAuditORM(
                            created_at=now - timedelta(minutes=4),
                            updated_at=now - timedelta(minutes=4),
                            ticker="AAPL",
                            asset_type="stock",
                            side="buy",
                            order_type="market",
                            qty=0.5,
                            dry_run=True,
                            idempotency_key=idempotency_key,
                            lifecycle_status="dry_run",
                            latest_price=200.0,
                            notional_estimate=100.0,
                            submitted=False,
                            broker_status="dry_run",
                            preview_payload="{}",
                        )
                    )
                    session.commit()

                recovered = asyncio.run(service.recover_due_intents())
                with SessionLocal() as session:
                    intent = (
                        session.query(AutomationIntentORM)
                        .filter(AutomationIntentORM.run_id == "run-recover")
                        .one()
                    )

            self.assertEqual(recovered, 1)
            self.assertEqual(intent.status, "dry_run_complete")
            self.assertEqual(intent.request_count_avoided, 1)
            place_mock.assert_not_awaited()
        finally:
            engine.dispose()
            temp_dir.cleanup()

    def test_dry_run_completion_records_paper_ledger_row(self) -> None:
        temp_dir, engine, SessionLocal = self._build_session_local()
        try:
            place_mock = AsyncMock(
                return_value=OrderPlaceResponse(
                    ok=True,
                    submitted=False,
                    dry_run=True,
                    message="Dry run only. Order was not sent to Alpaca.",
                    idempotency_key="paperloop:test",
                    execution_audit_id=11,
                    raw={"latest_price": 200.0},
                )
            )
            service = self._build_service(place_mock=place_mock)
            run = _build_scan_run(run_id="run-ledger")

            with patch.object(automation_repository_module, "SessionLocal", SessionLocal):
                asyncio.run(service.process_completed_run(run))
                with SessionLocal() as session:
                    ledger_rows = session.query(PaperPositionORM).all()

            self.assertEqual(len(ledger_rows), 1)
            self.assertEqual(ledger_rows[0].ticker, "AAPL")
            self.assertEqual(ledger_rows[0].status, "open")
        finally:
            engine.dispose()
            temp_dir.cleanup()

    def test_record_paper_position_sell_without_open_marks_audit_failed(self) -> None:
        temp_dir, engine, SessionLocal = self._build_session_local()
        try:
            now = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
            with patch.object(automation_repository_module, "SessionLocal", SessionLocal):
                with SessionLocal() as session:
                    audit = self._add_execution_audit(session, now=now)
                    untouched = self._add_execution_audit(
                        session,
                        now=now,
                        idempotency_key="paperloop:untouched",
                    )
                    intent = self._add_intent_for_audit(session, now=now, audit=audit)
                    audit_id = audit.id
                    untouched_id = untouched.id
                    intent_id = intent.id
                    session.commit()

                position_id = AutomationRepository().record_paper_position(
                    intent_id=intent_id,
                    simulated_fill_price=201.0,
                    filled_at=now + timedelta(minutes=1),
                )

                with SessionLocal() as session:
                    audit = session.get(ExecutionAuditORM, audit_id)
                    untouched = session.get(ExecutionAuditORM, untouched_id)
                    ledger_rows = session.query(PaperPositionORM).all()

            self.assertIsNone(position_id)
            self.assertEqual(ledger_rows, [])
            self.assertEqual(audit.lifecycle_status, "failed")
            self.assertEqual(audit.error_message, "sell_without_open_position")
            self.assertEqual(untouched.lifecycle_status, "dry_run")
            self.assertIsNone(untouched.error_message)
        finally:
            engine.dispose()
            temp_dir.cleanup()

    def test_record_paper_position_from_audit_sell_without_open_marks_audit_failed(self) -> None:
        temp_dir, engine, SessionLocal = self._build_session_local()
        try:
            now = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
            with patch.object(automation_repository_module, "SessionLocal", SessionLocal):
                with SessionLocal() as session:
                    audit = self._add_execution_audit(session, now=now)
                    untouched = self._add_execution_audit(
                        session,
                        now=now,
                        idempotency_key="paperloop:untouched-audit",
                    )
                    audit_id = audit.id
                    untouched_id = untouched.id
                    session.commit()

                position_id = AutomationRepository().record_paper_position_from_audit(
                    audit_id=audit_id,
                    simulated_fill_price=201.0,
                    filled_at=now + timedelta(minutes=1),
                )

                with SessionLocal() as session:
                    audit = session.get(ExecutionAuditORM, audit_id)
                    untouched = session.get(ExecutionAuditORM, untouched_id)
                    ledger_rows = session.query(PaperPositionORM).all()

            self.assertIsNone(position_id)
            self.assertEqual(ledger_rows, [])
            self.assertEqual(audit.lifecycle_status, "failed")
            self.assertEqual(audit.error_message, "sell_without_open_position")
            self.assertEqual(untouched.lifecycle_status, "dry_run")
            self.assertIsNone(untouched.error_message)
        finally:
            engine.dispose()
            temp_dir.cleanup()

    def test_recovery_terminalizes_when_attempt_count_at_cap(self) -> None:
        temp_dir, engine, SessionLocal = self._build_session_local()
        try:
            place_mock = AsyncMock()
            service = self._build_service(place_mock=place_mock)
            now = datetime.now(timezone.utc)
            with patch.object(automation_repository_module, "SessionLocal", SessionLocal):
                with SessionLocal() as session:
                    session.add(
                        AutomationIntentORM(
                            created_at=now,
                            updated_at=now,
                            run_id="run-cap",
                            symbol="AAPL",
                            asset_type="stock",
                            side="buy",
                            qty=0.5,
                            strategy_version="v4.0-layered",
                            confidence=80.0,
                            horizon="1h",
                            intent_key="cap-key",
                            intent_hash="h",
                            status="failed_retryable",
                            attempt_count=3,
                            idempotency_key="cap-key",
                            request_payload_json=json.dumps(
                                {
                                    "ticker": "AAPL",
                                    "side": "buy",
                                    "qty": 0.5,
                                    "order_type": "market",
                                    "dry_run": True,
                                    "idempotency_key": "cap-key",
                                }
                            ),
                            next_retry_at=now - timedelta(minutes=1),
                        )
                    )
                    session.commit()

                asyncio.run(service.recover_due_intents())
                with SessionLocal() as session:
                    intent = session.query(AutomationIntentORM).filter_by(run_id="run-cap").one()

            self.assertEqual(intent.status, "failed_terminal")
            place_mock.assert_not_awaited()
        finally:
            engine.dispose()
            temp_dir.cleanup()

    def test_concurrent_claim_intent_single_winner(self) -> None:
        temp_dir, engine, SessionLocal = self._build_session_local()
        try:
            now = datetime.now(timezone.utc)
            with patch.object(automation_repository_module, "SessionLocal", SessionLocal):
                with SessionLocal() as session:
                    session.add(
                        AutomationIntentORM(
                            created_at=now,
                            updated_at=now,
                            run_id="run",
                            symbol="AAPL",
                            asset_type="stock",
                            side="buy",
                            qty=0.5,
                            strategy_version="v4.0-layered",
                            confidence=80.0,
                            horizon="1h",
                            intent_key="concurrent-key",
                            intent_hash="h",
                            status="pending",
                            idempotency_key="concurrent-key",
                            request_payload_json=json.dumps({"idempotency_key": "concurrent-key"}),
                        )
                    )
                    session.commit()
                    intent_id = session.query(AutomationIntentORM).one().id

                repo = AutomationRepository()
                results: list[bool] = []

                def attempt() -> None:
                    results.append(
                        repo.claim_intent(
                            intent_id=intent_id,
                            claimed_by="w",
                            claim_expires_at=now + timedelta(seconds=90),
                            max_place_attempts=3,
                        )
                    )

                t1 = threading.Thread(target=attempt)
                t2 = threading.Thread(target=attempt)
                t1.start()
                t2.start()
                t1.join()
                t2.join()

                self.assertEqual(sum(1 for r in results if r), 1)
        finally:
            engine.dispose()
            temp_dir.cleanup()

    def test_breaker_closed_failures_open_and_half_open_serializes_probes(self) -> None:
        temp_dir, engine, SessionLocal = self._build_session_local()
        try:
            now = datetime.now(timezone.utc)
            with patch.object(automation_repository_module, "SessionLocal", SessionLocal):
                repo = AutomationRepository()
                for _ in range(3):
                    repo.breaker_on_place_failure(
                        now=now,
                        message="err",
                        half_open_probe=False,
                        failures_to_open=3,
                        failure_window_minutes=15,
                        open_minutes=30,
                    )
                blocked, next_retry, _ = repo.breaker_pre_execution_should_block(now=now, owner="a")
                self.assertTrue(blocked)
                self.assertIsNotNone(next_retry)

                later = now + timedelta(hours=1)
                a1, _, _, h1 = repo.breaker_prepare_for_place(
                    owner="a", now=later, probe_ttl_seconds=90
                )
                self.assertTrue(a1)
                self.assertTrue(h1)
                a2, nr2, _, _ = repo.breaker_prepare_for_place(owner="b", now=later, probe_ttl_seconds=90)
                self.assertFalse(a2)
                self.assertIsNotNone(nr2)
        finally:
            engine.dispose()
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
