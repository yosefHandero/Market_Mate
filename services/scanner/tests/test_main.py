import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

if "yahooquery" not in sys.modules:
    yahooquery_stub = types.ModuleType("yahooquery")
    yahooquery_stub.Ticker = object
    sys.modules["yahooquery"] = yahooquery_stub

import app.main as main_module


class MainRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main_module.app)

    def test_health_response_does_not_expose_database_path(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("database_path", body)
        self.assertIn("request_id", body)

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

    def test_trade_eligibility_returns_502_when_price_lookup_fails(self) -> None:
        with patch.object(
            main_module.execution_service.alpaca,
            "get_latest_price",
            AsyncMock(side_effect=RuntimeError("provider down")),
        ):
            response = self.client.get(
                "/risk/trade-eligibility",
                params={"ticker": "AAPL", "side": "buy", "qty": 1},
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("Unable to fetch latest price for AAPL", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
