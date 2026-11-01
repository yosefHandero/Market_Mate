from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.config import Settings
from app.services.runtime_identity import build_runtime_identity


class RuntimeIdentityTests(unittest.TestCase):
    def test_imported_policy_and_saved_identity_are_reported_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(_env_file=None, database_url=f"sqlite:///{Path(directory) / 'test.db'}", cache_dir=directory)
            policy = SimpleNamespace(policy_id="hybrid_legacy", policy_version="hybrid-new", fingerprint=lambda: "new")
            runtime = Mock()
            runtime.learned_inputs_service.load_active_campaign_pin.return_value = SimpleNamespace(fingerprint="pin")
            runtime.registry.get.return_value = policy
            runtime.effective_champion_id.return_value = "hybrid_legacy"
            runtime.requested_champion_id.return_value = "hybrid_legacy"
            saved = SimpleNamespace(campaign_id="camp-old", effective_policy_id="hybrid_legacy", effective_policy_version="hybrid-old", effective_decision_fingerprint="old", learned_artifacts_fingerprint="pin")
            identity = build_runtime_identity("api", settings=settings, runtime=runtime, campaign=saved)
            self.assertEqual(identity["runtime_policy_version"], "hybrid-new")
            self.assertEqual(identity["saved_policy_version"], "hybrid-old")
            self.assertFalse(identity["identity_matches_saved_campaign"])
            self.assertEqual(identity["learned_artifacts_fingerprint"], "pin")
            self.assertEqual(identity["database"], settings.database_path)
            self.assertNotIn("api_token", json.dumps(identity))

    def test_missing_pin_does_not_load_latest_or_claim_matching_identity(self):
        settings = Settings(_env_file=None, database_url="sqlite:///:memory:")
        runtime = Mock()
        runtime.learned_inputs_service.load_active_campaign_pin.return_value = None
        runtime.hybrid.policy_version = "hybrid-new"
        identity = build_runtime_identity("worker", settings=settings, runtime=runtime, campaign=None)
        self.assertEqual(identity["learned_artifact_status"], "no_saved_pin")
        self.assertIsNone(identity["runtime_decision_fingerprint"])
        runtime.refresh_weekly_inputs.assert_not_called()
        runtime.learned_inputs_service.load_current.assert_not_called()


class RuntimeVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_verification_only_heartbeats(self):
        import app.worker as worker

        settings = Settings(_env_file=None, runtime_verification_mode=True)
        heartbeat = asyncio.Event()

        async def beat():
            heartbeat.set()
            await asyncio.Event().wait()

        scheduler = Mock()
        scheduler.run_forever = AsyncMock()
        market_data = Mock(enabled=True)
        market_data.run_forever = AsyncMock()
        with (
            patch.object(worker, "get_settings", return_value=settings),
            patch.object(worker, "scheduler_service", scheduler),
            patch.object(worker, "coinbase_market_data_service", market_data),
            patch.object(worker, "_worker_heartbeat_loop", side_effect=beat),
            patch.object(worker, "log_runtime_identity"),
        ):
            task = asyncio.create_task(worker.main())
            try:
                await asyncio.wait_for(heartbeat.wait(), timeout=1)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            scheduler.stop.assert_called_once()
            scheduler.run_forever.assert_not_awaited()
            market_data.run_forever.assert_not_awaited()

    async def test_api_verification_skips_startup_mutations(self):
        import app.main as main

        settings = Settings(_env_file=None, runtime_verification_mode=True)
        with (
            patch.object(main, "settings", settings),
            patch.object(main, "log_runtime_identity"),
            patch.object(main, "get_schema_status", return_value=SimpleNamespace(ok=True, missing_items=[])),
            patch.object(main, "StartupMaintenanceService") as maintenance,
        ):
            async with main.lifespan(main.app):
                pass
        maintenance.assert_not_called()
