import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

if "yahooquery" not in sys.modules:
    yahooquery_stub = types.ModuleType("yahooquery")
    yahooquery_stub.Ticker = object
    sys.modules["yahooquery"] = yahooquery_stub

import app.main as main_module
import app.api.public as public_module
import app.db as db_module
import app.services.execution as execution_module
import app.services.readiness as readiness_module
from app.db import SchemaStatus
from app.dependencies import (
    coinbase_market_data_service,
    execution_service as global_execution_service,
    scheduler_service as global_scheduler_service,
)
from app.schemas import (
    OrderPlaceResponse,
    ScanResult,
    ScanRun,
)


class MainRouteTests(unittest.TestCase):
    def _sample_trust_snapshot(self):
        return types.SimpleNamespace(
            window=types.SimpleNamespace(
                start=datetime(2026, 3, 1, tzinfo=timezone.utc),
                end=datetime(2026, 3, 31, tzinfo=timezone.utc),
                days=30,
            ),
            summary=types.SimpleNamespace(
                total_signals=2,
                evaluated_count=2,
                pending_count=0,
                by_signal_and_gate=[
                    types.SimpleNamespace(key="BUY:passed", evaluated_count=1),
                    types.SimpleNamespace(key="SELL:passed", evaluated_count=1),
                ],
            ),
            threshold=types.SimpleNamespace(
                recommendation=types.SimpleNamespace(
                    evidence_status="ready",
                    source="test",
                    warnings=[],
                ),
            ),
            pending_due_15m_count=0,
            pending_due_1h_count=0,
            pending_due_1d_count=0,
            pending_due_1w_count=0,
        )

    def setUp(self) -> None:
        schema_status = SchemaStatus(ok=True, applied_changes=[], missing_items=[])
        self.public_schema_status_mock = Mock(return_value=schema_status)
        self.readiness_schema_status_mock = Mock(return_value=schema_status)
        self.startup_schema_status_mock = Mock(return_value=schema_status)
        self.startup_maintenance_mock = AsyncMock(
            return_value=types.SimpleNamespace(
                repaired_signal_outcome_returns=None,
                relinked_execution_audits=None,
                recovered_automation_intents=None,
                ran_tasks=(),
                skipped_tasks=(),
            )
        )
        self.scheduler_state_mock = Mock(
            return_value=types.SimpleNamespace(
                enabled=False,
                running=False,
                worker_alive=False,
                interval_seconds=300,
                lease_owner=None,
                lease_expires_at=None,
                worker_heartbeat_at=None,
                next_run_at=None,
                last_run_started_at=None,
                last_run_finished_at=None,
                last_error=None,
            )
        )
        fresh_scan = datetime.now(timezone.utc) - timedelta(minutes=5)
        coinbase_settings = coinbase_market_data_service.settings
        original_coinbase_ws_enabled = coinbase_settings.coinbase_ws_enabled
        coinbase_settings.coinbase_ws_enabled = False
        self.addCleanup(
            setattr,
            coinbase_settings,
            "coinbase_ws_enabled",
            original_coinbase_ws_enabled,
        )
        patchers = [
            patch.object(public_module, "get_schema_status", self.public_schema_status_mock),
            patch.object(readiness_module, "get_schema_status", self.readiness_schema_status_mock),
            patch.object(readiness_module, "check_database_connection", Mock(return_value=True)),
            patch.object(main_module, "get_schema_status", self.startup_schema_status_mock),
            patch.object(
                main_module.StartupMaintenanceService,
                "run_if_due",
                self.startup_maintenance_mock,
            ),
            patch.object(global_scheduler_service, "state", self.scheduler_state_mock),
            patch.object(
                main_module.scan_repository,
                "get_latest_run_timestamp",
                Mock(return_value=fresh_scan),
            ),
            patch.object(
                main_module.scan_repository,
                "get_trust_readiness_snapshot",
                Mock(return_value=self._sample_trust_snapshot()),
            ),
            patch.object(
                main_module.scan_repository,
                "sync_signal_outcome_returns",
                Mock(return_value=0),
            ),
            patch.object(
                main_module.scan_repository,
                "backfill_execution_audit_signal_links",
                Mock(return_value=0),
            ),
            patch.object(
                main_module.automation_service,
                "recover_due_intents",
                AsyncMock(return_value=0),
            ),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(main_module.app)
        # Default config uses fail-closed read access; most route tests expect open reads.
        main_module.settings.public_read_access_enabled = True

    def tearDown(self) -> None:
        main_module.settings.public_read_access_enabled = False

    def _sample_performance_report(self) -> dict:
        metrics = {
            "horizon": "1h",
            "total_signals": 1,
            "evaluated_count": 1,
            "pending_count": 0,
            "win_count": 1,
            "loss_count": 0,
            "false_positive_count": 0,
            "win_rate": 100.0,
            "mean_return": 1.25,
            "median_return": 1.25,
            "avg_win_return": 1.25,
            "avg_loss_return": None,
            "expectancy": 1.25,
            "false_positive_rate": 0.0,
            "meets_min_sample": True,
            "insufficient_sample": False,
        }
        metrics_15m = {**metrics, "horizon": "15m"}
        metrics_1h = dict(metrics)
        metrics_1d = {**metrics, "horizon": "1d"}
        metrics_1w = {**metrics, "horizon": "1w"}
        slice_summary = {
            "key": "overall",
            "total_signals": 1,
            "metrics_15m": metrics_15m,
            "metrics_1h": metrics_1h,
            "metrics_1d": metrics_1d,
            "metrics_1w": metrics_1w,
        }
        return {
            "generated_at_field": "generated_at",
            "start": datetime(2026, 3, 1, 0, 0),
            "end": datetime(2026, 3, 2, 0, 0),
            "asset_type": None,
            "total_signals": 1,
            "min_evaluated_per_horizon": 1,
            "overall": slice_summary,
            "by_signal": [{**slice_summary, "key": "BUY"}],
            "by_signal_and_gate": [{**slice_summary, "key": "BUY:passed"}],
            "by_asset_type": [{**slice_summary, "key": "stock"}],
            "baseline": {
                "primary_horizon": "1h",
                "min_evaluated_per_horizon": 1,
                "min_mean_return_pct": 0.0,
                "passes_baseline": True,
                "details": ["BUY:passed meets the baseline."],
                "checks": [
                    {
                        "key": "BUY:passed",
                        "horizon": "1h",
                        "evaluated_count": 1,
                        "mean_return": 1.25,
                        "meets_min_sample": True,
                        "passes_mean_return": True,
                        "passed": True,
                        "reason": "BUY:passed meets the baseline.",
                    }
                ],
            },
        }

    def _sample_scan_result(self, *, ticker: str = "AAPL") -> ScanResult:
        return ScanResult(
            ticker=ticker,
            score=72.0,
            raw_score=72.0,
            calibrated_confidence=72.0,
            decision_signal="BUY",
            explanation="Momentum is expanding.",
            price=100.0,
            price_change_pct=1.2,
            relative_volume=1.5,
            sentiment_score=0.2,
            filing_flag=False,
            breakout_flag=True,
            market_status="bullish",
            sector_strength_score=0.4,
            gate_passed=True,
            gate_reason="Passed",
            provider_status="ok",
            bar_age_minutes=5,
            created_at=datetime(2026, 3, 1, 12, 0),
        )

    def _sample_scan_run(self, results: list[ScanResult] | None = None) -> ScanRun:
        rows = results if results is not None else [self._sample_scan_result()]
        return ScanRun(
            run_id="run-1",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            market_status="bullish",
            scan_count=len(rows),
            watchlist_size=len(rows),
            alerts_sent=0,
            fear_greed_value=None,
            fear_greed_label=None,
            results=rows,
        )

    def _sample_automation_status(self, **overrides):
        status = types.SimpleNamespace(
            enabled=False,
            phase="disabled",
            dry_run_only=True,
            kill_switch_enabled=False,
            breaker=types.SimpleNamespace(state="closed"),
        )
        for key, value in overrides.items():
            setattr(status, key, value)
        return status

    def test_health_response_does_not_expose_database_path(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("database_path", body)
        self.assertIn("request_id", body)

    def test_lifespan_does_not_apply_schema_patches(self) -> None:
        forbidden_patch = Mock(side_effect=AssertionError("startup must not auto-repair schema"))

        with patch.object(
            main_module,
            "apply_required_schema_patches",
            forbidden_patch,
            create=True,
        ), patch.object(
            db_module,
            "apply_required_schema_patches",
            forbidden_patch,
        ):
            with TestClient(main_module.create_app()):
                pass

        forbidden_patch.assert_not_called()
        self.startup_schema_status_mock.assert_called()

    def test_lifespan_runs_startup_maintenance_service(self) -> None:
        with patch.object(
            main_module.scan_repository,
            "sync_signal_outcome_returns",
            Mock(side_effect=AssertionError("startup must use StartupMaintenanceService")),
        ), patch.object(
            main_module.scan_repository,
            "backfill_execution_audit_signal_links",
            Mock(side_effect=AssertionError("startup must use StartupMaintenanceService")),
        ), patch.object(
            main_module.automation_service,
            "recover_due_intents",
            AsyncMock(side_effect=AssertionError("startup must use StartupMaintenanceService")),
        ):
            with TestClient(main_module.create_app()):
                pass

        self.startup_maintenance_mock.assert_awaited_once()

    def _assert_settings_reject_live_flags(
        self,
        *,
        execution_enabled: bool,
        allow_live_trading: bool,
    ) -> None:
        # Paper-only enforcement now lives in Settings.forbid_live_execution, so
        # any process that loads settings with a live flag set fails fast at
        # construction rather than relying on a single API startup assertion.
        from pydantic import ValidationError

        from app.config import Settings

        with self.assertRaisesRegex(ValidationError, "Paper-only build enforcement"):
            Settings(
                execution_enabled=execution_enabled,
                allow_live_trading=allow_live_trading,
            )

    def test_settings_reject_execution_enabled_true(self) -> None:
        self._assert_settings_reject_live_flags(
            execution_enabled=True,
            allow_live_trading=False,
        )

    def test_settings_reject_allow_live_trading_true(self) -> None:
        self._assert_settings_reject_live_flags(
            execution_enabled=False,
            allow_live_trading=True,
        )

    def test_settings_reject_both_live_flags_true(self) -> None:
        self._assert_settings_reject_live_flags(
            execution_enabled=True,
            allow_live_trading=True,
        )

    def test_readyz_reports_stale_scan_as_not_ready(self) -> None:
        with patch.object(
            main_module.scan_repository,
            "get_latest_run_timestamp",
            Mock(return_value=datetime(2026, 3, 1, 0, 0)),
        ):
            response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ready"])
        self.assertFalse(body["scan_fresh"])

    def test_readyz_not_ready_when_no_scan_has_ever_run(self) -> None:
        with patch.object(
            main_module.scan_repository,
            "get_latest_run_timestamp",
            Mock(return_value=None),
        ):
            response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ready"])
        self.assertFalse(body["scan_fresh"])
        self.assertIsNone(body["last_scan_at"])

    def test_scan_latest_returns_503_when_schema_missing_items(self) -> None:
        missing_status = SchemaStatus(
            ok=False,
            applied_changes=[],
            missing_items=["scan_results.bar_as_of"],
        )
        self.public_schema_status_mock.return_value = missing_status

        with patch.object(
            main_module.scanner_service,
            "latest",
            Mock(side_effect=AssertionError("schema-missing scan/latest should short-circuit")),
        ):
            response = self.client.get("/scan/latest")

        self.assertEqual(response.status_code, 503)
        body = response.json()
        details = body.get("error", {}).get("details", {})
        self.assertIn("missing_schema_items", details)
        self.assertEqual(["scan_results.bar_as_of"], details["missing_schema_items"])

    def test_livez_short_circuits_when_schema_missing_items(self) -> None:
        missing_status = SchemaStatus(
            ok=False,
            applied_changes=[],
            missing_items=["scan_results.bar_as_of"],
        )
        self.public_schema_status_mock.return_value = missing_status

        with patch.object(
            main_module.scan_repository,
            "get_latest_run_timestamp",
            Mock(side_effect=AssertionError("schema-missing livez should short-circuit")),
        ), patch.object(
            main_module.scan_repository,
            "get_trust_readiness_snapshot",
            Mock(side_effect=AssertionError("schema-missing livez should short-circuit")),
        ):
            response = self.client.get("/livez")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["schema_ok"])
        self.assertEqual(["scan_results.bar_as_of"], body["missing_schema_items"])

    def test_readyz_returns_503_when_schema_missing_items(self) -> None:
        missing_status = SchemaStatus(
            ok=False,
            applied_changes=[],
            missing_items=["scan_runs.strategy_variant"],
        )
        self.public_schema_status_mock.return_value = missing_status
        self.readiness_schema_status_mock.return_value = missing_status

        with patch.object(
            main_module.scan_repository,
            "get_latest_run_timestamp",
            Mock(side_effect=AssertionError("schema-missing readyz should short-circuit")),
        ), patch.object(
            main_module.scan_repository,
            "get_trust_readiness_snapshot",
            Mock(side_effect=AssertionError("schema-missing readyz should short-circuit")),
        ):
            response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertFalse(body["ready"])
        self.assertFalse(body["schema_ok"])
        self.assertEqual(["scan_runs.strategy_variant"], body["missing_schema_items"])

    def test_readyz_reports_trust_window_metadata_when_scan_is_fresh(self) -> None:
        fresh_scan = datetime.now(timezone.utc) - timedelta(minutes=5)
        with patch.object(
            main_module.scan_repository,
            "get_latest_run_timestamp",
            Mock(return_value=fresh_scan),
        ):
            response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ready"])
        self.assertTrue(body["scan_fresh"])
        self.assertIn("trust_window_start", body)
        self.assertIn("trust_threshold_evidence_status", body)
        self.assertIn("pending_due_1h_count", body)

    def test_admin_route_requires_token_when_configured(self) -> None:
        original_admin_token = main_module.settings.admin_api_token
        original_env = main_module.settings.app_env
        main_module.settings.admin_api_token = "secret-token"
        main_module.settings.app_env = "production"
        self.addCleanup(setattr, main_module.settings, "admin_api_token", original_admin_token)
        self.addCleanup(setattr, main_module.settings, "app_env", original_env)

        response = self.client.post("/scan/run")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthorized")

    def test_scan_latest_requires_auth_when_public_read_disabled_and_no_tokens(self) -> None:
        saved_public = main_module.settings.public_read_access_enabled
        saved_read = main_module.settings.read_api_token
        saved_admin = main_module.settings.admin_api_token
        main_module.settings.public_read_access_enabled = False
        main_module.settings.read_api_token = ""
        main_module.settings.admin_api_token = ""
        self.addCleanup(setattr, main_module.settings, "public_read_access_enabled", saved_public)
        self.addCleanup(setattr, main_module.settings, "read_api_token", saved_read)
        self.addCleanup(setattr, main_module.settings, "admin_api_token", saved_admin)

        response = self.client.get("/scan/latest")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthorized")

    def test_read_route_requires_token_when_public_access_is_disabled(self) -> None:
        original_public = main_module.settings.public_read_access_enabled
        original_read_token = main_module.settings.read_api_token
        main_module.settings.public_read_access_enabled = False
        main_module.settings.read_api_token = "read-secret"
        self.addCleanup(
            setattr,
            main_module.settings,
            "public_read_access_enabled",
            original_public,
        )
        self.addCleanup(setattr, main_module.settings, "read_api_token", original_read_token)

        response = self.client.get("/scan/latest")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthorized")

    def test_read_route_accepts_valid_read_token(self) -> None:
        original_public = main_module.settings.public_read_access_enabled
        original_read_token = main_module.settings.read_api_token
        main_module.settings.public_read_access_enabled = False
        main_module.settings.read_api_token = "read-secret"
        self.addCleanup(
            setattr,
            main_module.settings,
            "public_read_access_enabled",
            original_public,
        )
        self.addCleanup(setattr, main_module.settings, "read_api_token", original_read_token)

        with patch.object(main_module.scanner_service, "latest", Mock(return_value=None)) as latest_mock:
            response = self.client.get(
                "/scan/latest",
                headers={"Authorization": "Bearer read-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())
        latest_mock.assert_called_once()

    def test_removed_non_core_read_routes_return_404(self) -> None:
        for path in (
            "/scan/history",
            "/scan/history/AAPL",
            "/signals/validation/summary",
            "/signals/validation/threshold-sweep",
            "/signals/validation/execution-alignment",
            "/signals/outcomes",
            "/signals/outcomes/summary",
            "/signals/outcomes/AAPL",
            "/scan/projection/AAPL",
            "/journal/entries",
            "/journal/analytics",
            "/metrics",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, path)

    def test_removed_non_core_admin_journal_routes_return_404(self) -> None:
        original_admin_token = main_module.settings.admin_api_token
        main_module.settings.admin_api_token = "secret-token"
        self.addCleanup(setattr, main_module.settings, "admin_api_token", original_admin_token)

        create_response = self.client.post(
            "/journal/entries",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "ticker": "AAPL",
                "run_id": "run-1",
                "decision": "watching",
                "entry_price": 180.0,
                "notes": "removed product route",
            },
        )
        update_response = self.client.patch(
            "/journal/entries/99",
            headers={"Authorization": "Bearer secret-token"},
            json={"notes": "removed product route"},
        )

        self.assertEqual(create_response.status_code, 404)
        self.assertEqual(update_response.status_code, 404)

    def test_orders_preview_returns_503_when_scanner_not_ready(self) -> None:
        original_admin = main_module.settings.admin_api_token
        main_module.settings.admin_api_token = "preview-admin"
        self.addCleanup(setattr, main_module.settings, "admin_api_token", original_admin)
        original_require = global_execution_service.settings.require_readyz_for_execution
        global_execution_service.settings.require_readyz_for_execution = True
        self.addCleanup(
            setattr,
            global_execution_service.settings,
            "require_readyz_for_execution",
            original_require,
        )

        with patch.object(
            execution_module,
            "evaluate_operational_readiness",
            return_value=(False, "No full scan has completed yet."),
        ):
            response = self.client.post(
                "/orders/preview",
                headers={"Authorization": "Bearer preview-admin"},
                json={
                    "ticker": "AAPL",
                    "side": "buy",
                    "qty": 1,
                    "order_type": "market",
                },
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "not_ready")

    def test_orders_place_rejects_non_dry_run_at_boundary(self) -> None:
        original_admin = main_module.settings.admin_api_token
        main_module.settings.admin_api_token = "preview-admin"
        self.addCleanup(setattr, main_module.settings, "admin_api_token", original_admin)

        with patch.object(main_module.execution_service, "place", AsyncMock()) as place_mock:
            response = self.client.post(
                "/orders/place",
                headers={"Authorization": "Bearer preview-admin"},
                json={
                    "ticker": "AAPL",
                    "side": "buy",
                    "qty": 1,
                    "order_type": "market",
                    "dry_run": False,
                },
            )

        # Paper-only build: dry_run=false is rejected at the schema boundary (422)
        # before the handler runs.
        self.assertEqual(response.status_code, 422)
        place_mock.assert_not_awaited()

    def test_orders_place_rejects_live_and_unknown_modes_at_boundary(self) -> None:
        original_admin = main_module.settings.admin_api_token
        main_module.settings.admin_api_token = "preview-admin"
        self.addCleanup(setattr, main_module.settings, "admin_api_token", original_admin)

        for mode in ("live", "real", "production", "paperish"):
            with self.subTest(mode=mode):
                with patch.object(main_module.execution_service, "place", AsyncMock()) as place_mock:
                    response = self.client.post(
                        "/orders/place",
                        headers={"Authorization": "Bearer preview-admin"},
                        json={
                            "ticker": "AAPL",
                            "side": "buy",
                            "qty": 1,
                            "order_type": "market",
                            "mode": mode,
                            "dry_run": True,
                        },
                    )

                # Only mode omitted or "dry_run" is accepted; anything else is a
                # 422 schema rejection.
                self.assertEqual(response.status_code, 422)
                place_mock.assert_not_awaited()

    def test_orders_place_defaults_omitted_dry_run_to_paper(self) -> None:
        original_admin = main_module.settings.admin_api_token
        main_module.settings.admin_api_token = "preview-admin"
        self.addCleanup(setattr, main_module.settings, "admin_api_token", original_admin)
        place_response = OrderPlaceResponse(
            ok=True,
            submitted=False,
            dry_run=True,
            message="Dry-run paper order recorded. No broker order request was made.",
        )

        with patch.object(
            main_module.execution_service,
            "place",
            AsyncMock(return_value=place_response),
        ) as place_mock:
            response = self.client.post(
                "/orders/place",
                headers={"Authorization": "Bearer preview-admin"},
                json={
                    "ticker": "AAPL",
                    "side": "buy",
                    "qty": 1,
                    "order_type": "market",
                },
            )

        self.assertEqual(response.status_code, 200)
        request = place_mock.await_args.args[0]
        self.assertTrue(request.dry_run)
        self.assertIsNone(request.mode)

    def test_read_route_accepts_admin_token_when_read_token_is_configured(self) -> None:
        original_public = main_module.settings.public_read_access_enabled
        original_read_token = main_module.settings.read_api_token
        original_admin_token = main_module.settings.admin_api_token
        main_module.settings.public_read_access_enabled = False
        main_module.settings.read_api_token = "read-secret"
        main_module.settings.admin_api_token = "admin-secret"
        self.addCleanup(setattr, main_module.settings, "public_read_access_enabled", original_public)
        self.addCleanup(setattr, main_module.settings, "read_api_token", original_read_token)
        self.addCleanup(setattr, main_module.settings, "admin_api_token", original_admin_token)

        with patch.object(main_module.scanner_service, "latest", Mock(return_value=None)) as latest_mock:
            response = self.client.get(
                "/scan/latest",
                headers={"Authorization": "Bearer admin-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())
        latest_mock.assert_called_once()

    def test_trade_eligibility_returns_502_when_price_lookup_fails(self) -> None:
        original_admin = main_module.settings.admin_api_token
        main_module.settings.admin_api_token = "risk-admin"
        self.addCleanup(setattr, main_module.settings, "admin_api_token", original_admin)
        with patch.object(
            main_module.execution_service.alpaca,
            "get_latest_price",
            AsyncMock(side_effect=RuntimeError("provider down")),
        ):
            response = self.client.get(
                "/risk/trade-eligibility",
                params={"ticker": "AAPL", "side": "buy", "qty": 1},
                headers={"Authorization": "Bearer risk-admin"},
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("Unable to fetch latest price for AAPL", response.json()["detail"])

    def test_signal_outcome_performance_report_returns_data_for_authorized_admin(self) -> None:
        original_admin_token = main_module.settings.admin_api_token
        original_env = main_module.settings.app_env
        main_module.settings.admin_api_token = "secret-token"
        main_module.settings.app_env = "production"
        self.addCleanup(setattr, main_module.settings, "admin_api_token", original_admin_token)
        self.addCleanup(setattr, main_module.settings, "app_env", original_env)

        with patch.object(
            main_module.scan_repository,
            "get_signal_outcome_performance_report",
            Mock(return_value=self._sample_performance_report()),
        ) as report_mock:
            response = self.client.get(
                "/signals/outcomes/performance-report",
                params={"start": "2026-03-01T00:00:00Z", "end": "2026-03-02T00:00:00Z"},
                headers={"Authorization": "Bearer secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["baseline"]["passes_baseline"])
        report_mock.assert_called_once()

    def test_orders_audits_route_returns_recent_audits(self) -> None:
        with patch.object(
            main_module.scan_repository,
            "list_execution_audits",
            Mock(
                return_value=[
                    {
                        "id": 1,
                        "created_at": datetime(2026, 3, 1, 12, 0),
                        "updated_at": datetime(2026, 3, 1, 12, 1),
                        "ticker": "AAPL",
                        "asset_type": "stock",
                        "side": "buy",
                        "order_type": "market",
                        "qty": 1.0,
                        "dry_run": True,
                        "lifecycle_status": "dry_run",
                        "latest_price": 190.0,
                        "notional_estimate": 190.0,
                        "signal_run_id": "run-123",
                        "signal_generated_at": datetime(2026, 3, 1, 11, 59),
                        "latest_signal": "BUY",
                        "confidence": 72.0,
                        "trade_gate_allowed": True,
                        "trade_gate_reason": "passed",
                        "submitted": False,
                        "broker_order_id": None,
                        "broker_status": "dry_run",
                        "error_message": None,
                    }
                ]
            ),
        ) as audits_mock:
            response = self.client.get("/orders/audits")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body[0]["ticker"], "AAPL")
        self.assertEqual(body[0]["lifecycle_status"], "dry_run")
        audits_mock.assert_called_once()

    def test_automation_status_route_returns_aggregated_loop_health(self) -> None:
        with patch.object(
            main_module.automation_service,
            "status",
            Mock(
                return_value={
                    "enabled": True,
                    "phase": "limited",
                    "dry_run_only": True,
                    "kill_switch_enabled": False,
                    "scheduler_triggered": True,
                    "last_processed_run_id": "run-123",
                    "last_processed_run_at": datetime(2026, 3, 30, 12, 0),
                    "last_recovery_at": datetime(2026, 3, 30, 12, 5),
                    "requests_made": 2,
                    "requests_avoided": 7,
                    "dedupe_hits": 3,
                    "retries": 1,
                    "blocked_by_budget": 1,
                    "blocked_by_gate": 0,
                    "blocked_by_cooldown": 2,
                    "blocked_by_circuit": 0,
                    "recent_status_counts": {"dry_run_complete": 1, "shadowed": 2},
                    "budget": {
                        "hourly_limit": 6,
                        "hourly_used": 2,
                        "daily_limit": 20,
                        "daily_used": 2,
                        "per_symbol_window_limit": 1,
                        "per_symbol_window_seconds": 21600,
                        "per_cycle_limit": 2,
                    },
                    "breaker": {
                        "state": "closed",
                        "opened_at": None,
                        "open_until": None,
                        "consecutive_failures": 0,
                        "last_error": None,
                        "probe_owner": None,
                        "probe_expires_at": None,
                    },
                    "recent_intents": [],
                    "candidates_considered": 0,
                    "candidates_reached_execution_call": 0,
                    "filter_rate_pct": None,
                }
            ),
        ) as status_mock:
            response = self.client.get("/automation/status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["enabled"])
        self.assertEqual(body["requests_avoided"], 7)
        self.assertEqual(body["budget"]["hourly_limit"], 6)
        status_mock.assert_called_once()

    def test_system_readiness_route_returns_pass_with_automation_separate(self) -> None:
        with patch.object(
            public_module,
            "check_database_connection",
            Mock(return_value=True),
        ), patch.object(
            main_module.scan_repository,
            "get_latest_run",
            Mock(return_value=self._sample_scan_run()),
        ), patch.object(
            main_module.automation_service,
            "status",
            Mock(return_value=self._sample_automation_status()),
        ):
            response = self.client.get("/system/readiness")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "PASS")
        self.assertIn("Core safety and data checks pass", body["reasons"])
        self.assertFalse(body["automation"]["automation_ready"])
        self.assertFalse(body["automation"]["scheduler_enabled"])
        self.assertEqual(body["provider"]["worst_status"], "ok")
        self.assertEqual(body["freshness"]["total_count"], 1)
        self.assertTrue(body["freshness"]["scan_fresh"])

    def test_system_readiness_route_fails_for_safety_and_global_data_blockers(self) -> None:
        breaker = types.SimpleNamespace(state="open")
        critical_row = self._sample_scan_result(ticker="AAPL")
        critical_row.provider_status = "critical"
        critical_row.bar_age_minutes = 400
        stale_row = self._sample_scan_result(ticker="TSLA")
        stale_row.provider_status = "critical"
        stale_row.bar_age_minutes = 500

        with patch.object(
            public_module,
            "check_database_connection",
            Mock(return_value=True),
        ), patch.object(
            main_module.scan_repository,
            "get_latest_run",
            Mock(return_value=self._sample_scan_run([critical_row, stale_row])),
        ), patch.object(
            main_module.automation_service,
            "status",
            Mock(
                return_value=self._sample_automation_status(
                    kill_switch_enabled=True,
                    breaker=breaker,
                )
            ),
        ):
            response = self.client.get("/system/readiness")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "FAIL")
        self.assertIn("Kill switch on", body["safety_blockers"])
        self.assertIn("Circuit breaker open", body["safety_blockers"])
        self.assertIn("Severe global freshness failure", body["reasons"])
        self.assertIn("Provider critical with unusable/stale data", body["reasons"])
        self.assertTrue(body["automation"]["kill_switch_enabled"])
        self.assertEqual(body["automation"]["breaker_state"], "open")

    def test_paper_ledger_summary_route_returns_backend_summary(self) -> None:
        with patch.object(
            main_module.scan_repository,
            "get_paper_ledger_summary",
            Mock(
                return_value={
                    "open_positions": 1,
                    "closed_positions": 2,
                    "total_notional_usd": 120.0,
                    "total_realized_pnl": 14.5,
                    "total_closed_notional_usd": 210.0,
                    "long_positions": 1,
                    "short_positions": 0,
                    "last_opened_at": datetime(2026, 4, 1, 12, 0),
                    "last_closed_at": datetime(2026, 4, 1, 13, 0),
                }
            ),
        ) as summary_mock:
            response = self.client.get("/paper/ledger/summary")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["open_positions"], 1)
        summary_mock.assert_called_once()

    def test_proof_summary_route_returns_ledger_and_loop_metrics(self) -> None:
        ledger = {
            "open_positions": 1,
            "closed_positions": 2,
            "total_notional_usd": 120.0,
            "total_realized_pnl": 14.5,
            "total_closed_notional_usd": 210.0,
            "long_positions": 1,
            "short_positions": 0,
            "last_opened_at": datetime(2026, 4, 1, 12, 0),
            "last_closed_at": datetime(2026, 4, 1, 13, 0),
            "total_count": 3,
            "win_rate_pct": 50.0,
            "gross_pnl_usd": 14.5,
            "max_drawdown_usd": 3.0,
            "total_unrealized_pnl": 8.25,
        }
        audits = [
            Mock(lifecycle_status="dry_run", trade_gate_allowed=True),
            Mock(lifecycle_status="previewed", trade_gate_allowed=True),
            Mock(lifecycle_status="blocked", trade_gate_allowed=False),
        ]
        with patch.object(
            main_module.scan_repository,
            "get_latest_run",
            Mock(return_value=None),
        ), patch.object(
            main_module.scan_repository,
            "get_paper_ledger_summary",
            Mock(return_value=ledger),
        ) as summary_mock, patch.object(
            main_module.scan_repository,
            "list_execution_audits",
            Mock(return_value=audits),
        ), patch.object(
            main_module.scan_repository,
            "get_latest_run_timestamp",
            Mock(return_value=datetime(2026, 4, 1, 12, 0)),
        ), patch.object(
            main_module.scan_repository,
            "get_prediction_accuracy_summary",
            Mock(
                return_value={
                    "evaluated_count": 5,
                    "pending_count": 2,
                    "in_range_count": 3,
                    "in_range_rate_pct": 60.0,
                    "below_range_count": 1,
                    "above_range_count": 1,
                    "missed_count": 0,
                    "note": "Low sample",
                }
            ),
        ), patch.object(
            main_module.scan_repository,
            "get_confidence_performance",
            Mock(return_value={"ranking": {"buckets": [], "monotonic_by_group": None, "note": None}, "calibration": {"buckets": [], "mean_abs_reliability_gap_pct": None, "note": None}}),
        ), patch.object(
            main_module.scan_repository,
            "get_exit_window_accuracy_summary",
            Mock(return_value={"evaluated_count": 0, "pending_count": 0, "helped_count": 0, "helped_rate_pct": None, "by_asset_type": [], "note": None}),
        ), patch.object(
            main_module.scan_repository,
            "get_weekly_evidence_progress",
            Mock(return_value={"live_forward_samples": 0, "out_of_sample_samples": 0, "historical_samples": 0, "backfilled_replay_samples": 0, "min_live_forward_samples": 20, "min_out_of_sample_samples": 10, "min_historical_samples": 30, "min_backfilled_replay_samples": 20, "trust_sample_gate_met": False, "calibration_sample_gate_met": False}),
        ):
            response = self.client.get("/proof/summary")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["ledger"]["total_unrealized_pnl"], 8.25)
        self.assertEqual(body["loop_metrics"]["recent_dry_runs"], 1)
        self.assertEqual(body["loop_metrics"]["recent_previewed"], 1)
        self.assertEqual(body["loop_metrics"]["recent_blocked"], 1)
        self.assertEqual(body["loop_metrics"]["total_audits"], 3)
        self.assertEqual(body["mark_prices_source"], "latest_scan")
        self.assertEqual(body["prediction_accuracy"]["in_range_rate_pct"], 60.0)
        summary_mock.assert_called_once()

    def test_admin_paper_routes_return_promotion_and_reconciliation_reports(self) -> None:
        original_admin_token = main_module.settings.admin_api_token
        main_module.settings.admin_api_token = "secret-token"
        self.addCleanup(setattr, main_module.settings, "admin_api_token", original_admin_token)

        with patch.object(
            main_module.promotion_service,
            "evaluate_promotion_readiness",
            Mock(
                return_value={
                    "current_phase": "shadow",
                    "target_phase": "limited",
                    "passed": True,
                    "generated_at": datetime(2026, 4, 4, 12, 0),
                    "details": ["clean"],
                    "checks": [{"key": "reconciliation_clean", "passed": True, "detail": "clean"}],
                }
            ),
        ) as promotion_mock, patch.object(
            main_module.scan_repository,
            "reconcile_paper_loop",
            Mock(
                return_value={
                    "generated_at": datetime(2026, 4, 4, 12, 0),
                    "ok": True,
                    "total_issues": 0,
                    "issues": [],
                }
            ),
        ) as reconcile_mock:
            promotion_response = self.client.get(
                "/paper/promotion-check",
                headers={"Authorization": "Bearer secret-token"},
            )
            reconcile_response = self.client.get(
                "/paper/reconcile",
                headers={"Authorization": "Bearer secret-token"},
            )

        self.assertEqual(promotion_response.status_code, 200)
        self.assertTrue(promotion_response.json()["passed"])
        self.assertEqual(reconcile_response.status_code, 200)
        self.assertTrue(reconcile_response.json()["ok"])
        promotion_mock.assert_called_once()
        reconcile_mock.assert_called_once()

if __name__ == "__main__":
    unittest.main()
