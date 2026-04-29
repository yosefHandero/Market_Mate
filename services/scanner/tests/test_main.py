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
import app.services.execution as execution_module
from app.db import apply_required_schema_patches
from app.dependencies import execution_service as global_execution_service


class MainRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        apply_required_schema_patches()
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
        slice_summary = {
            "key": "overall",
            "total_signals": 1,
            "metrics_15m": metrics_15m,
            "metrics_1h": metrics_1h,
            "metrics_1d": metrics_1d,
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

    def test_health_response_does_not_expose_database_path(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("database_path", body)
        self.assertIn("request_id", body)

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
        for path in ("/signals/outcomes", "/signals/outcomes/summary", "/metrics"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, path)

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

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "dry_run_required")
        place_mock.assert_not_awaited()

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

    def test_create_journal_entry_normalizes_payload_for_authorized_admin(self) -> None:
        original_admin_token = main_module.settings.admin_api_token
        main_module.settings.admin_api_token = "secret-token"
        self.addCleanup(setattr, main_module.settings, "admin_api_token", original_admin_token)

        created_entry = {
            "id": 7,
            "ticker": "AAPL",
            "run_id": "run-1",
            "decision": "watching",
            "entry_price": 180.0,
            "exit_price": None,
            "pnl_pct": None,
            "notes": "trimmed note",
            "created_at": datetime(2026, 3, 1, 12, 0),
            "signal_label": None,
            "score": None,
            "news_source": None,
        }

        with patch.object(
            main_module.journal_repository,
            "create_entry",
            Mock(return_value=created_entry),
        ) as create_mock:
            response = self.client.post(
                "/journal/entries",
                headers={"Authorization": "Bearer secret-token"},
                json={
                    "ticker": " aapl ",
                    "run_id": " run-1 ",
                    "decision": "watching",
                    "entry_price": 180.0,
                    "exit_price": None,
                    "pnl_pct": None,
                    "notes": "  trimmed note  ",
                    "signal_label": None,
                    "score": None,
                    "news_source": None,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = create_mock.call_args.args[0]
        self.assertEqual(payload.ticker, "AAPL")
        self.assertEqual(payload.run_id, "run-1")
        self.assertEqual(payload.notes, "trimmed note")
        self.assertEqual(response.json()["ticker"], "AAPL")

    def test_update_journal_entry_returns_404_when_missing(self) -> None:
        original_admin_token = main_module.settings.admin_api_token
        main_module.settings.admin_api_token = "secret-token"
        self.addCleanup(setattr, main_module.settings, "admin_api_token", original_admin_token)

        with patch.object(
            main_module.journal_repository,
            "update_entry",
            Mock(return_value=None),
        ) as update_mock:
            response = self.client.patch(
                "/journal/entries/99",
                headers={"Authorization": "Bearer secret-token"},
                json={"notes": "still missing"},
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Journal entry not found")
        update_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
