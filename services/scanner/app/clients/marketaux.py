from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
import logging
import math
import time
from uuid import uuid4

import httpx

from app.config import Settings, get_settings
from app.clients.news_result import NEWS_LOOKBACK_DAYS, NewsResult, news_request_failure
from app.http_client import ProviderRequestError, _parse_retry_after, request_json
from app.provider_resilience import AsyncProviderGuard
from app.services.provider_coordination import CoordinationBlocked, CoordinationPaced, ProviderCoordination, content_key

logger = logging.getLogger(__name__)
NEWS_URL = "https://api.marketaux.com/v1/news/all"
# Keep shared reservations below the observed 30-attempt rolling minute.
MIN_ATTEMPT_INTERVAL_SECONDS = 2.1


def marketaux_account(token: str) -> str:
    # Never persist or log the token itself.
    return content_key(["marketaux", token])


def marketaux_quota_status(settings: Settings) -> dict[str, str | int | None] | None:
    if not settings.marketaux_api_token:
        return None
    now = time.time()
    utc_day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    state = ProviderCoordination(settings.cache_dir_path).status(marketaux_account(settings.marketaux_api_token))
    ceiling = state["attempt_ceiling"]
    reset_at = state["reset_at"]
    rate_until = state["rate_until"]
    return {
        "configured_daily_attempt_budget": settings.marketaux_daily_attempt_budget,
        "utc_day_attempts": state["day_attempts"] if state["day"] == utc_day else 0,
        "operational_attempts_remaining": None if ceiling is None else max(0, ceiling - state["total_attempts"]),
        "block_state": None if reset_at and reset_at <= now else state["block_state"],
        "verified_reset_at": datetime.fromtimestamp(reset_at, timezone.utc).isoformat() if reset_at else None,
        "rate_retry_at": datetime.fromtimestamp(rate_until, timezone.utc).isoformat() if rate_until > now else None,
    }


def _news_result(payload: dict, ticker: str, lookback_start: str) -> NewsResult:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Marketaux news payload missing data")
    if not payload["data"]:
        return NewsResult(0.0, "no_relevant_articles", NEWS_URL, 200, lookback_start)

    scores = []
    latest = None
    matched_entity = False
    now = datetime.now(timezone.utc)
    earliest = datetime.fromisoformat(lookback_start).replace(tzinfo=timezone.utc)
    for article in payload["data"]:
        if not isinstance(article, dict):
            raise ValueError("Marketaux article is not an object")
        entities = article.get("entities")
        if not isinstance(entities, list):
            raise ValueError("Marketaux entities are not an array")
        for entity in entities:
            if not isinstance(entity, dict):
                raise ValueError("Marketaux entity is not an object")
            if not isinstance(entity.get("symbol"), str):
                raise ValueError("Marketaux entity is missing a symbol")
            if entity["symbol"].upper() != ticker:
                continue
            matched_entity = True
            try:
                published_at = datetime.fromisoformat(article.get("published_at", ""))
            except (TypeError, ValueError):
                break
            if published_at.tzinfo is None or published_at > now:
                break
            latest = published_at if latest is None else max(latest, published_at)
            if entity.get("sentiment_score") is None:
                continue
            numeric = float(entity["sentiment_score"])
            if not math.isfinite(numeric):
                raise ValueError("Marketaux sentiment is not finite")
            if published_at >= earliest:
                scores.append(numeric)
            break
    latest_article_at = latest.isoformat() if latest else None
    if not scores:
        if latest is None:
            status = "invalid_publication_time" if matched_entity else "coverage_unavailable"
        else:
            status = "stale_news" if latest < earliest else "missing_sentiment"
        return NewsResult(None, status, NEWS_URL, 200, lookback_start, latest_article_at)
    avg = sum(scores) / len(scores)
    return NewsResult(round(max(min(avg, 1.0), -1.0), 4), "ok", NEWS_URL, 200, lookback_start, latest_article_at)


class MarketauxClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)
        self._guard = AsyncProviderGuard("marketaux", pace_seconds=0.5)
        self.coordination = ProviderCoordination(self.settings.cache_dir_path)
        self.account = marketaux_account(self.settings.marketaux_api_token)
        self.min_attempt_interval_seconds = MIN_ATTEMPT_INTERVAL_SECONDS
        self.ownership_seconds = max(30.0, self.settings.provider_timeout_seconds * 4 + 5)
        self.wait_seconds = min(self.ownership_seconds, 30.0)

    async def get_news_sentiment_score(self, ticker: str) -> float | None:
        return (await self.check_news(ticker)).score

    async def check_news(self, ticker: str) -> NewsResult:
        if not self.settings.marketaux_api_token:
            return NewsResult(None, "disabled_missing_credentials")

        symbol = ticker.upper()
        lookback_start = (datetime.now(timezone.utc).date() - timedelta(days=NEWS_LOOKBACK_DAYS)).isoformat()
        params = {
            "api_token": self.settings.marketaux_api_token,
            "symbols": symbol,
            "language": "en",
            "limit": 10,
            "published_after": lookback_start,
        }

        try:
            payload = await self._shared_news(params)
            return _news_result(payload, symbol, lookback_start)

        except Exception as exc:
            result = news_request_failure(exc, endpoint=NEWS_URL)
            logger.info("Marketaux news unavailable (%s)", result.status,
                        extra={"event": "marketaux_unavailable", "error_type": type(exc).__name__})
            return result

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
        except CoordinationBlocked:
            # Recheck shared quota or ownership on the next caller. No generic
            # cooldown should hide a specific quota block.
            failed = False
            raise
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
            while not ownership_lost.is_set():
                try:
                    # Immediately before EVERY HTTP send, including retries.
                    self.coordination.reserve_attempt(
                        self.account, key, owner, self.settings.marketaux_daily_attempt_budget,
                        min_interval_seconds=self.min_attempt_interval_seconds,
                    )
                except CoordinationPaced as exc:
                    await asyncio.sleep(exc.retry_after_seconds)
                else:
                    return
            raise CoordinationBlocked("request_ownership_lost")

        def on_response(response: httpx.Response) -> None:
            if ownership_lost.is_set() or not self.coordination.renew(key, owner, self.ownership_seconds):
                raise CoordinationBlocked("request_ownership_lost")
            if response.status_code < 400 and response.status_code != 200:
                raise ProviderRequestError("Marketaux returned an unexpected HTTP status", provider="marketaux",
                                           url=NEWS_URL, status_code=response.status_code)
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            error = payload.get("error") if isinstance(payload, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            # https://www.marketaux.com/documentation#errors documents these codes.
            if response.status_code == 402 and code == "usage_limit_reached":
                self.coordination.record_block(self.account, key, owner, reason="usage_limit_reached")
                raise CoordinationBlocked("quota_exhausted_reset_unknown")
            if response.status_code in {401, 403}:
                raise ProviderRequestError("Marketaux endpoint access blocked", provider="marketaux",
                                           url=NEWS_URL, status_code=response.status_code)
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
                raise ProviderRequestError("Marketaux returned an error payload", provider="marketaux", url=NEWS_URL,
                                           status_code=response.status_code)

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
        # Cache only well-formed responses. Reuse empty or uncovered responses
        # within the TTL to avoid spending more requests for the same window.
        try:
            _news_result(payload, str(params["symbols"]), str(params["published_after"]))
        except (ValueError, TypeError, OverflowError) as exc:
            raise ProviderRequestError("Marketaux news payload is invalid", provider="marketaux",
                                       url=NEWS_URL, status_code=200) from exc
        return payload
