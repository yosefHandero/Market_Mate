from __future__ import annotations

from datetime import date, timedelta
import httpx

from app.config import get_settings
from app.http_client import request_json
from app.provider_resilience import AsyncProviderGuard


class FinnhubClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)
        self._guard = AsyncProviderGuard("finnhub", pace_seconds=0.5)

    async def get_news_sentiment_score(self, ticker: str) -> float:
        if not self.settings.finnhub_api_key:
            return 0.0

        to_date = date.today()
        from_date = to_date - timedelta(days=7)
        params = {
            "symbol": ticker,
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "token": self.settings.finnhub_api_key,
        }

        try:
            return await self._guard.cached_call(
                key=("news_sentiment", ticker.upper(), from_date.isoformat(), to_date.isoformat()),
                ttl_seconds=max(self.settings.news_cache_minutes * 60, 60),
                stale_ttl_seconds=max(self.settings.news_cache_minutes * 120, 300),
                fetcher=lambda: self._fetch_news_sentiment(ticker=ticker, params=params),
            )
        except Exception:
            return 0.0

    async def _fetch_news_sentiment(self, *, ticker: str, params: dict[str, str]) -> float:
        await self._guard.throttle()
        news = await request_json(
            self._client,
            method="GET",
            url="https://finnhub.io/api/v1/company-news",
            params=params,
            provider="finnhub",
            on_backoff=self._guard.register_backoff,
        )
        await self._guard.throttle()
        sentiment_payload = await request_json(
            self._client,
            method="GET",
            url="https://finnhub.io/api/v1/news-sentiment",
            params={"symbol": ticker, "token": self.settings.finnhub_api_key},
            provider="finnhub",
            on_backoff=self._guard.register_backoff,
        )

        company_news_score = float(sentiment_payload.get("companyNewsScore") or 0)
        article_sentiment = float(sentiment_payload.get("sentiment", {}).get("companyNewsScore") or 0)
        directional_company_score = (company_news_score * 2) - 1 if company_news_score else 0.0
        directional_article_score = (article_sentiment * 2) - 1 if article_sentiment else 0.0
        article_density = min(len(news), 15) / 15
        sentiment = (directional_company_score * 0.7) + (directional_article_score * 0.2) + (directional_company_score * article_density * 0.1)
        return round(max(min(sentiment, 1.0), -1.0), 4)