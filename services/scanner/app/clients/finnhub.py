from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import math

import httpx

from app.clients.news_result import NEWS_LOOKBACK_DAYS, NewsResult, news_request_failure
from app.config import get_settings
from app.http_client import ProviderRequestError, request_json
from app.provider_resilience import AsyncProviderGuard
from app.services.provider_coordination import ProviderCoordination, content_key

logger = logging.getLogger(__name__)
SENTIMENT_URL = "https://finnhub.io/api/v1/news-sentiment"
COMPANY_NEWS_URL = "https://finnhub.io/api/v1/company-news"
ACCESS_COOLDOWN_SECONDS = 24 * 60 * 60
RESOURCE_DENIED = "You don't have access to this resource."


class FinnhubClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)
        self._guard = AsyncProviderGuard("finnhub", pace_seconds=0.5)
        self._coordination = ProviderCoordination(self.settings.cache_dir_path)

    async def get_news_sentiment_score(self, ticker: str) -> float | None:
        return (await self.check_news(ticker)).score

    async def check_news(self, ticker: str) -> NewsResult:
        if not self.settings.finnhub_api_key:
            return NewsResult(None, "disabled_missing_credentials")

        ticker = ticker.upper()
        to_date = datetime.now(timezone.utc).date()
        from_date = to_date - timedelta(days=NEWS_LOOKBACK_DAYS)
        params = {
            "symbol": ticker,
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        }

        try:
            return await self._guard.cached_call(
                key=("news_sentiment", ticker.upper(), from_date.isoformat(), to_date.isoformat()),
                ttl_seconds=max(self.settings.news_cache_minutes * 60, 60),
                stale_ttl_seconds=0,
                fetcher=lambda: self._fetch_news_sentiment(ticker=ticker, params=params),
            )
        except Exception as exc:
            result = news_request_failure(exc, endpoint=SENTIMENT_URL)
            logger.info("Finnhub news unavailable (%s)", result.status,
                        extra={"event": "finnhub_unavailable", "error_type": type(exc).__name__})
            return result

    async def _request_news(self, url: str, params: dict[str, str]):
        token = self.settings.finnhub_api_key
        key = content_key(["finnhub-access-v1", token, url])

        def check_access() -> None:
            blocked = self._coordination.read_cache(key)
            if blocked is not None:
                raise ProviderRequestError("Finnhub endpoint access blocked", provider="finnhub", url=url,
                                           status_code=blocked["status_code"])

        async def before_attempt() -> None:
            check_access()
            await self._guard.throttle()
            check_access()

        def on_response(response: httpx.Response) -> None:
            status = response.status_code
            if status < 400 and status != 200:
                raise ProviderRequestError("Finnhub returned an unexpected HTTP status", provider="finnhub",
                                           url=url, status_code=status)
            if status not in {401, 403}:
                return
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if status == 401 or (isinstance(payload, dict) and payload.get("error") == RESOURCE_DENIED):
                self._coordination.write_cache(key, {"status_code": status}, ACCESS_COOLDOWN_SECONDS)
            raise ProviderRequestError("Finnhub endpoint access blocked", provider="finnhub", url=url,
                                       status_code=status)

        try:
            return await request_json(
                self._client,
                method="GET",
                url=url,
                params=params,
                headers={"X-Finnhub-Token": token},
                provider="finnhub",
                on_backoff=self._guard.register_backoff,
                before_attempt=before_attempt,
                on_response=on_response,
            )
        except (httpx.TransportError, TimeoutError) as exc:
            raise ProviderRequestError("Finnhub transport failed", provider="finnhub", url=url) from exc

    async def _fetch_news_sentiment(self, *, ticker: str, params: dict[str, str]) -> NewsResult:
        # Entitlement is required before the article-density request can contribute.
        sentiment_payload = await self._request_news(SENTIMENT_URL, {"symbol": ticker})
        if not isinstance(sentiment_payload, dict) or sentiment_payload.get("error"):
            raise ProviderRequestError("Finnhub sentiment payload is invalid", provider="finnhub",
                                       url=SENTIMENT_URL, status_code=200)
        symbol = sentiment_payload.get("symbol")
        if symbol is not None and symbol != ticker:
            return NewsResult(None, "coverage_unavailable", SENTIMENT_URL, 200, params["from"])

        article_stats = sentiment_payload.get("sentiment")
        if article_stats is not None and not isinstance(article_stats, dict):
            raise ProviderRequestError("Finnhub sentiment statistics are invalid", provider="finnhub",
                                       url=SENTIMENT_URL, status_code=200)
        company_score = sentiment_payload.get("companyNewsScore")
        article_score = (article_stats or {}).get("bullishPercent", (article_stats or {}).get("companyNewsScore"))
        try:
            company_news_score = float(company_score or 0)
            article_sentiment = float(article_score or 0)
            if not math.isfinite(company_news_score) or not math.isfinite(article_sentiment):
                raise ValueError("Finnhub sentiment is not finite")
        except (ValueError, TypeError, OverflowError) as exc:
            raise ProviderRequestError("Finnhub sentiment values are invalid", provider="finnhub",
                                       url=SENTIMENT_URL, status_code=200) from exc
        news = await self._request_news(COMPANY_NEWS_URL, params)
        if not isinstance(news, list) or any(not isinstance(article, dict) for article in news):
            raise ProviderRequestError("Finnhub company news payload is invalid", provider="finnhub",
                                       url=COMPANY_NEWS_URL, status_code=200)
        timestamps = [article.get("datetime") for article in news if isinstance(article.get("datetime"), int)]
        latest = max(timestamps, default=0)
        latest_article_at = None
        if 0 < latest <= datetime.now(timezone.utc).timestamp():
            latest_article_at = datetime.fromtimestamp(latest, timezone.utc).isoformat()

        if company_score is None and article_score is None:
            return NewsResult(None if news else 0.0, "coverage_unavailable" if news else "no_relevant_articles",
                              SENTIMENT_URL, 200, params["from"], latest_article_at)
        directional_company_score = (company_news_score * 2) - 1 if company_news_score else 0.0
        directional_article_score = (article_sentiment * 2) - 1 if article_sentiment else 0.0
        article_density = min(len(news), 15) / 15
        sentiment = (directional_company_score * 0.7) + (directional_article_score * 0.2) + (directional_company_score * article_density * 0.1)
        return NewsResult(round(max(min(sentiment, 1.0), -1.0), 4), "ok" if news else "company_sentiment_only",
                          SENTIMENT_URL, 200, params["from"], latest_article_at)
