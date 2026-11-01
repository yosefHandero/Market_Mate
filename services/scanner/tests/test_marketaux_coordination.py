from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.clients.finnhub import FinnhubClient
from app.clients.marketaux import MarketauxClient, NEWS_URL
from app.marketaux_quota import main as quota_main
from app.services.news_cache import NewsCacheService
from app.services.provider_coordination import CoordinationBlocked, ProviderCoordination, content_key


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.store = ProviderCoordination(self.path)

    def claim(self, key="key", owner="owner", now=100):
        return self.store.claim(key, owner, 10, now=now)

    def test_expired_owner_cannot_overwrite_new_owner_or_quota(self):
        self.assertEqual(self.claim()[0], "owned")
        self.assertEqual(self.claim(owner="competing", now=105)[0], "waiting")
        self.assertEqual(self.claim(owner="new", now=111)[0], "owned")
        self.assertFalse(self.store.renew("key", "owner", 10, now=112))
        self.assertFalse(self.store.complete("key", "owner", {"stale": True}, 60, now=112))
        self.assertFalse(self.store.record_block("account", "key", "owner", reason="late", now=112))
        with self.assertRaisesRegex(CoordinationBlocked, "ownership_lost"):
            self.store.reserve_attempt("account", "key", "owner", None, now=112)
        self.assertTrue(self.store.complete("key", "new", {"fresh": True}, 60, now=112))
        self.assertEqual(self.claim(now=113), ("cached", {"fresh": True}))

    def test_unknown_reset_persists_until_audited_recovery(self):
        self.claim()
        self.store.record_block("account", "key", "owner", reason="usage_limit_reached", now=100)
        restarted = ProviderCoordination(self.path)
        restarted.claim("other", "new", 10, now=100000)
        with self.assertRaisesRegex(CoordinationBlocked, "reset_unknown"):
            restarted.reserve_attempt("account", "other", "new", None, now=100001)
        with self.assertRaises(ValueError):
            restarted.recover("account", " ")
        restarted.recover("account", "Verified available on account dashboard", now=100002)
        restarted.reserve_attempt("account", "other", "new", None, now=100003)
        status = restarted.status("account")
        self.assertEqual(status["total_attempts"], 1)
        self.assertEqual(status["audit"][0]["recorded_at"], 100002)
        self.assertEqual(status["audit"][0]["action"], "verified_available")

    def test_verified_reset_honored_at_exact_time(self):
        self.store.recover("account", "Verified reset time with provider", verified_reset_at=105, now=100)
        self.claim()
        with self.assertRaisesRegex(CoordinationBlocked, "waiting_verified_reset"):
            self.store.reserve_attempt("account", "key", "owner", None, now=104.99)
        self.store.reserve_attempt("account", "key", "owner", None, now=105)
        self.assertIsNone(self.store.status("account")["block_state"])

    def test_local_daily_cap_and_persistent_ceiling_are_independent(self):
        self.claim()
        self.store.reserve_attempt("account", "key", "owner", 1, now=101)
        with self.assertRaisesRegex(CoordinationBlocked, "daily_attempt_budget"):
            self.store.reserve_attempt("account", "key", "owner", 1, now=102)
        self.store.set_attempt_ceiling("account", 0, "Verification unavailable")
        self.claim(now=86401)
        with self.assertRaisesRegex(CoordinationBlocked, "operational_attempt_ceiling"):
            self.store.reserve_attempt("account", "key", "owner", 1, now=86402)
        self.store.set_attempt_ceiling("account", 1, "Verified one additional attempt")
        self.store.reserve_attempt("account", "key", "owner", 1, now=86402)
        self.assertEqual(self.store.status("account")["total_attempts"], 2)

    def test_independent_connections_atomically_reserve_shared_ceiling(self):
        self.store.set_attempt_ceiling("account", 3, "Test shared ceiling")
        def reserve(index):
            other = ProviderCoordination(self.path)
            key = str(index)
            other.claim(key, key, 30)
            try:
                other.reserve_attempt("account", key, key, None)
                return True
            except CoordinationBlocked:
                return False
        with ThreadPoolExecutor(max_workers=8) as executor:
            accepted = list(executor.map(reserve, range(20)))
        self.assertEqual(sum(accepted), 3)
        self.assertEqual(self.store.status("account")["total_attempts"], 3)

    def test_separate_process_observes_persisted_unknown_reset(self):
        self.claim()
        self.store.record_block("account", "key", "owner", reason="usage_limit_reached", now=100)
        # The child has its own audit hook before importing application modules.
        code = '''
import pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
def guard(event, args):
    if event in {"socket.connect", "socket.sendto", "socket.getaddrinfo"}:
        raise AssertionError("network forbidden")
    if event == "sqlite3.connect" and not pathlib.Path(args[0]).resolve().is_relative_to(root):
        raise AssertionError("nonisolated database forbidden")
sys.addaudithook(guard)
from app.services.provider_coordination import ProviderCoordination, CoordinationBlocked
store = ProviderCoordination(root)
store.claim("child", "child", 30)
try:
    store.reserve_attempt("account", "child", "child", None)
except CoordinationBlocked as exc:
    print(str(exc))
else:
    raise AssertionError("unknown quota block did not survive process restart")
'''
        result = subprocess.run([sys.executable, "-c", code, str(self.path)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("quota_exhausted_reset_unknown", result.stdout)

    def test_cache_concurrent_writes_survive_in_new_instance(self):
        settings = SimpleNamespace(cache_dir_path=self.path, marketaux_api_token="fake", finnhub_api_key="fake",
                                   news_cache_minutes=45)
        with patch("app.services.news_cache.get_settings", return_value=settings):
            def write(index):
                NewsCacheService().set(str(index), index / 100)
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(write, range(30)))
            restarted = NewsCacheService()
            for index in range(30):
                self.assertEqual(restarted.get(str(index))[0], index / 100)
            with self.assertRaises(ValueError):
                restarted.set("invalid", None)

    def test_keys_are_order_independent_but_cover_request_parameters(self):
        self.assertEqual(content_key({"a": 1, "b": 2}), content_key({"b": 2, "a": 1}))
        self.assertNotEqual(content_key({"symbols": "AAPL", "limit": 10}), content_key({"symbols": "AAPL", "limit": 5}))

    def test_cli_recovery_is_audited_and_does_not_remove_ceiling(self):
        settings = SimpleNamespace(cache_dir_path=self.path, marketaux_api_token="fake",
                                   marketaux_daily_attempt_budget=None)
        with patch("app.marketaux_quota.get_settings", return_value=settings), patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(quota_main(["ceiling", "0", "--reason", "Availability unknown"]), 0)
            output.seek(0)
            output.truncate()
            self.assertEqual(quota_main(["recover", "--reason", "Verified available on account dashboard"]), 0)
            status = json.loads(output.getvalue())
        self.assertEqual(status["attempt_ceiling"], 0)
        self.assertEqual(status["audit"][0]["action"], "verified_available")
        self.assertTrue(status["audit"][0]["recorded_at"])
        self.assertIn("unknown", status["account_daily_allowance"])


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = SimpleNamespace(cache_dir_path=Path(self.directory.name), marketaux_api_token="fake-token",
            finnhub_api_key="fake-finnhub", provider_timeout_seconds=1, provider_retry_attempts=3,
            provider_retry_backoff_seconds=0, news_cache_minutes=45, marketaux_daily_attempt_budget=None)
        self.patches = [patch("app.clients.marketaux.get_settings", return_value=self.settings),
                        patch("app.clients.finnhub.get_settings", return_value=self.settings),
                        patch("app.http_client.get_settings", return_value=self.settings)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client._client.aclose()

    def client(self, responses):
        client = MarketauxClient()
        self.clients.append(client)
        client._guard.pace_seconds = 0
        client._client.request = AsyncMock(side_effect=responses)
        return client

    async def test_exhaustion_no_retry_and_new_client_no_send(self):
        first = self.client([httpx.Response(402, json={"error": {"code": "usage_limit_reached"}})])
        self.assertIsNone(await first.get_news_sentiment_score("AAPL"))
        second = self.client([AssertionError("Must not send")])
        self.assertIsNone(await second.get_news_sentiment_score("MSFT"))
        self.assertEqual(first._client.request.await_count, 1)
        self.assertEqual(second._client.request.await_count, 0)
        self.assertEqual(second.coordination.status(second.account)["block_state"], "reset_unknown")
        self.assertEqual(second.coordination.status(second.account)["total_attempts"], 1)

    async def test_ambiguous_402_does_not_claim_confirmed_exhaustion(self):
        client = self.client([httpx.Response(402, json={"error": {"code": "other_error"}})])
        self.assertIsNone(await client.get_news_sentiment_score("AAPL"))
        self.assertIsNone(client.coordination.status(client.account)["block_state"])

    async def test_429_is_shared_temporary_rate_block_not_quota_exhaustion(self):
        client = self.client([httpx.Response(429, headers={"Retry-After": "120"},
                                            json={"error": {"code": "rate_limit_reached"}})])
        self.assertIsNone(await client.get_news_sentiment_score("AAPL"))
        state = client.coordination.status(client.account)
        self.assertIsNone(state["block_state"])
        self.assertGreater(state["rate_until"], time.time() + 110)
        second = self.client([AssertionError("Cooldown must block")])
        self.assertIsNone(await second.get_news_sentiment_score("MSFT"))
        self.assertEqual(second._client.request.await_count, 0)

    async def test_retry_http_attempts_share_three_attempt_ceiling(self):
        client = self.client([httpx.Response(503, json={"error": "temporary"})] * 5)
        client.coordination.set_attempt_ceiling(client.account, 3, "At most three verification attempts")
        self.assertIsNone(await client.get_news_sentiment_score("AAPL"))
        self.assertEqual(client._client.request.await_count, 3)
        self.assertEqual(client.coordination.status(client.account)["total_attempts"], 3)
        second = self.client([AssertionError("No fourth attempt across tickers")])
        self.assertIsNone(await second.get_news_sentiment_score("MSFT"))
        self.assertEqual(second._client.request.await_count, 0)

    async def test_transport_retries_also_respect_ceiling(self):
        client = self.client([httpx.ReadTimeout("fake timeout")] * 5)
        client.coordination.set_attempt_ceiling(client.account, 2, "Transport retry ceiling")
        self.assertIsNone(await client.get_news_sentiment_score("AAPL"))
        self.assertEqual(client._client.request.await_count, 2)
        self.assertEqual(client.coordination.status(client.account)["total_attempts"], 2)

    async def test_independent_clients_coalesce_and_reuse_genuine_neutral(self):
        first = self.client([])
        async def delayed(*args, **kwargs):
            await asyncio.sleep(0.05)
            return httpx.Response(200, json={"data": [{"sentiment_score": 0.0}]})
        first._client.request.side_effect = delayed
        second = self.client([AssertionError("Equivalent request must coalesce")])
        self.assertEqual(await asyncio.gather(first.get_news_sentiment_score("AAPL"), second.get_news_sentiment_score("aapl")), [0.0, 0.0])
        restarted = self.client([AssertionError("Must reuse persisted success")])
        self.assertEqual(await restarted.get_news_sentiment_score("AAPL"), 0.0)
        self.assertEqual(first._client.request.await_count, 1)
        self.assertEqual(second._client.request.await_count, 0)
        self.assertEqual(restarted._client.request.await_count, 0)

    async def test_wait_is_bounded_and_abandoned_request_recovers(self):
        client = self.client([httpx.Response(200, json={"data": [{"sentiment_score": 0.4}]})])
        params = {"api_token": "fake-token", "symbols": "AAPL", "language": "en", "limit": 10}
        key = content_key(["marketaux-news-v2", "GET", NEWS_URL, params])
        client.coordination.claim(key, "crashed", 0.1)
        client.wait_seconds = 0.02
        with self.assertRaisesRegex(CoordinationBlocked, "wait_timeout"):
            await client._shared_news(params)
        self.assertEqual(client._client.request.await_count, 0)
        await asyncio.sleep(0.1)
        self.assertEqual(await client.get_news_sentiment_score("AAPL"), 0.4)
        self.assertEqual(client._client.request.await_count, 1)

    async def test_failed_payload_does_not_become_successful_neutral(self):
        client = self.client([httpx.Response(200, json={"error": {"code": "failure"}})])
        self.assertIsNone(await client.get_news_sentiment_score("AAPL"))
        second = self.client([AssertionError("Failure cooldown")])
        self.assertIsNone(await second.get_news_sentiment_score("AAPL"))
        self.assertEqual(second._client.request.await_count, 0)

    async def test_malformed_sentiment_is_not_cached_as_success(self):
        client = self.client([httpx.Response(200, json={"data": [{"sentiment_score": "bad-number"}]})])
        self.assertIsNone(await client.get_news_sentiment_score("AAPL"))
        params = {"api_token": "fake-token", "symbols": "AAPL", "language": "en", "limit": 10}
        key = content_key(["marketaux-news-v2", "GET", NEWS_URL, params])
        self.assertIsNone(client.coordination.read_cache(key))

    async def test_request_parameter_change_does_not_reuse_cache(self):
        client = self.client([httpx.Response(200, json={"data": [{"sentiment_score": 0.2}]})] * 2)
        params = {"api_token": "fake-token", "symbols": "AAPL", "language": "en", "limit": 10}
        await client._shared_news(params)
        await client._shared_news({**params, "limit": 5})
        self.assertEqual(client._client.request.await_count, 2)

    async def test_heartbeat_storage_failure_does_not_cache_or_retry_unowned_response(self):
        client = self.client([])
        client.ownership_seconds = 0.09
        async def delayed(*args, **kwargs):
            await asyncio.sleep(0.04)
            return httpx.Response(200, json={"data": [{"sentiment_score": 0.2}]})
        client._client.request.side_effect = delayed
        with patch.object(client.coordination, "renew", side_effect=RuntimeError("fake store failure")), patch.object(
            client.coordination, "complete", wraps=client.coordination.complete
        ) as complete, patch.object(client.coordination, "release", wraps=client.coordination.release) as release:
            self.assertIsNone(await client.get_news_sentiment_score("AAPL"))
            complete.assert_not_called()
            release.assert_called_once()
        self.assertEqual(client._client.request.await_count, 1)

    async def test_finnhub_failure_is_unavailable_but_neutral_is_valid(self):
        client = FinnhubClient()
        self.clients.append(client)
        with patch.object(client, "_fetch_news_sentiment", AsyncMock(side_effect=RuntimeError("fake provider failure"))):
            self.assertIsNone(await client.get_news_sentiment_score("AAPL"))
        with patch.object(client, "_fetch_news_sentiment", AsyncMock(return_value=0.0)):
            self.assertEqual(await client.get_news_sentiment_score("AAPL"), 0.0)

    async def test_scanner_keeps_finnhub_independent_and_neutral_honest(self):
        from app.services.scanner import ScannerService
        scanner = ScannerService.__new__(ScannerService)
        scanner.settings = self.settings
        scanner.news_cache = MagicMock()
        scanner.news_cache.get.return_value = (None, None)
        scanner.marketaux = SimpleNamespace(get_news_sentiment_score=AsyncMock(return_value=None))
        scanner.finnhub = SimpleNamespace(get_news_sentiment_score=AsyncMock(return_value=0.6))
        value = await scanner._get_directional_sentiment("AAPL")
        self.assertEqual(value[:3], (0.6, True, "finnhub"))
        scanner.news_cache.set.assert_not_called()
        scanner.finnhub.get_news_sentiment_score.return_value = None
        value = await scanner._get_directional_sentiment("AAPL")
        self.assertEqual(value[:3], (0.0, False, "unavailable"))
        scanner.news_cache.set.assert_not_called()
        scanner.marketaux.get_news_sentiment_score.return_value = 0.0
        scanner.finnhub.get_news_sentiment_score.return_value = 0.0
        value = await scanner._get_directional_sentiment("AAPL")
        self.assertEqual(value[:3], (0.0, True, "marketaux+finnhub"))
        self.assertNotIn("directional_news_unavailable", value[4])
        scanner.news_cache.set.assert_called_once_with("AAPL", 0.0)

    async def test_scanner_preserves_successful_nonzero_formula(self):
        from app.services.scanner import ScannerService
        scanner = ScannerService.__new__(ScannerService)
        scanner.settings = self.settings
        scanner.news_cache = MagicMock()
        scanner.news_cache.get.return_value = (None, None)
        scanner.marketaux = SimpleNamespace(get_news_sentiment_score=AsyncMock(return_value=0.8))
        scanner.finnhub = SimpleNamespace(get_news_sentiment_score=AsyncMock(return_value=-0.4))
        self.assertEqual((await scanner._get_directional_sentiment("AAPL"))[0], 0.2)
        scanner.finnhub.get_news_sentiment_score.return_value = 0.0
        self.assertEqual((await scanner._get_directional_sentiment("AAPL"))[0], 0.8)


if __name__ == "__main__":
    unittest.main()
