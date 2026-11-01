from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import math
import time
from uuid import uuid4

import httpx

from app.config import get_settings
from app.http_client import ProviderRequestError, _parse_retry_after, request_json
from app.provider_resilience import AsyncProviderGuard
from app.services.provider_coordination import CoordinationBlocked, ProviderCoordination, content_key

logger = logging.getLogger(__name__)
NEWS_URL = "https://api.marketaux.com/v1/news/all"


def marketaux_account(token: str) -> str:
    # Never persist or log the token itself.
    return content_key(["marketaux", token])


def _sentiment_score(payload: dict) -> float | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Marketaux news payload missing data")
    scores = []
    for article in payload["data"]:
        if not isinstance(article, dict):
            raise ValueError("Marketaux article is not an object")
        score = article.get("sentiment_score")
        if score is not None:
            numeric = float(score)
            if not math.isfinite(numeric):
                raise ValueError("Marketaux sentiment is not finite")
            scores.append(numeric)
    if not scores:
        return None
    avg = sum(scores) / len(scores)
    return round(max(min(avg, 1.0), -1.0), 4)


class MarketauxClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)
        self._guard = AsyncProviderGuard("marketaux", pace_seconds=0.5)
        self.coordination = ProviderCoordination(self.settings.cache_dir_path)
        self.account = marketaux_account(self.settings.marketaux_api_token)
        self.ownership_seconds = max(30.0, self.settings.provider_timeout_seconds * 4 + 5)
        self.wait_seconds = min(self.ownership_seconds, 30.0)

    async def get_news_sentiment_score(self, ticker: str) -> float | None:
        if not self.settings.marketaux_api_token:
            return None

        params = {
            "api_token": self.settings.marketaux_api_token,
            "symbols": ticker.upper(),
            "language": "en",
            "limit": 10,
        }

        try:
            payload = await self._shared_news(params)
            return _sentiment_score(payload)

        except Exception as exc:
            logger.info("Marketaux news unavailable", extra={"event": "marketaux_unavailable", "error_type": type(exc).__name__})
            return None

    async def _shared_news(self, params: dict[str, str | int]) -> dict:
        key = content_key(["marketaux-news-v2", "GET", NEWS_URL, params])
        owner = uuid4().hex
        deadline = asyncio.get_running_loop().time() + self.wait_seconds
        while True:
            state, payload = self.coordination.claim(key, owner, self.ownership_seconds)
            if state == "cached":
                return payload
            if state == "owned":
                break
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise CoordinationBlocked("equivalent_request_wait_timeout")
            await asyncio.sleep(min(0.1, remaining))

        ownership_lost = asyncio.Event()

        async def renew() -> None:
            while True:
                await asyncio.sleep(self.ownership_seconds / 3)
                try:
                    renewed = self.coordination.renew(key, owner, self.ownership_seconds)
                except Exception:
                    renewed = False
                if not renewed:
                    ownership_lost.set()
                    return

        heartbeat = asyncio.create_task(renew())
        failed = True
        try:
            # Bound the whole operation, including a transport trickling chunks.
            timeout = self.ownership_seconds * (self.settings.provider_retry_attempts + 2)
            payload = await asyncio.wait_for(self._fetch_news(params=params, key=key, owner=owner,
                                                             ownership_lost=ownership_lost), timeout=timeout)
            if ownership_lost.is_set():
                raise CoordinationBlocked("request_ownership_lost")
            if not self.coordination.complete(key, owner, payload, max(self.settings.news_cache_minutes * 60, 60)):
                raise CoordinationBlocked("request_ownership_lost")
            failed = False
            return payload
        finally:
            heartbeat.cancel()
            try:
                with suppress(asyncio.CancelledError):
                    await heartbeat
            finally:
                # A storage failure leaves only an expiring owner, never an
                # unfenced success write or a permanent in-flight lock.
                with suppress(Exception):
                    self.coordination.release(key, owner, failed=failed)

    async def _fetch_news(self, *, params: dict[str, str | int], key: str, owner: str,
                          ownership_lost: asyncio.Event) -> dict:
        async def before_attempt() -> None:
            await self._guard.throttle()
            if ownership_lost.is_set():
                raise CoordinationBlocked("request_ownership_lost")
            # Immediately before EVERY HTTP send, including retries.
            self.coordination.reserve_attempt(self.account, key, owner, self.settings.marketaux_daily_attempt_budget)

        def on_response(response: httpx.Response) -> None:
            if ownership_lost.is_set() or not self.coordination.renew(key, owner, self.ownership_seconds):
                raise CoordinationBlocked("request_ownership_lost")
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            error = payload.get("error") if isinstance(payload, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            # https://www.marketaux.com/documentation#errors documents these codes.
            if response.status_code == 402 and code == "usage_limit_reached":
                self.coordination.record_block(self.account, key, owner, reason="usage_limit_reached")
                raise ProviderRequestError("Marketaux plan quota exhausted; reset unknown", provider="marketaux",
                                           url=NEWS_URL, status_code=402)
            if response.status_code == 429:
                retry_after = _parse_retry_after(response.headers.get("retry-after"))
                # The rolling 60-second rate window is not a daily quota reset.
                cooldown = retry_after if retry_after is not None else 60.0
                self.coordination.record_block(self.account, key, owner, reason=str(code or "http_429"),
                                               rate_until=time.time() + cooldown)
                raise ProviderRequestError("Marketaux temporarily rate limited", provider="marketaux",
                                           url=NEWS_URL, status_code=429, retryable=True,
                                           retry_after_seconds=cooldown)
            if error and response.status_code < 400:
                raise ProviderRequestError("Marketaux returned an error payload", provider="marketaux", url=NEWS_URL)

        payload = await request_json(
            self._client,
            method="GET",
            url=NEWS_URL,
            params=params,
            provider="marketaux",
            on_backoff=self._guard.register_backoff,
            before_attempt=before_attempt,
            on_response=on_response,
        )
        # Validate before writing a success cache entry. The calculation itself
        # is unchanged and genuine zero remains a successful result.
        _sentiment_score(payload)
        return payload
