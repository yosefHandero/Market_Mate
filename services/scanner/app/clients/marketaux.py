from __future__ import annotations

import httpx

from app.config import get_settings
from app.http_client import request_json
from app.provider_resilience import AsyncProviderGuard


class MarketauxClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)
        self._guard = AsyncProviderGuard("marketaux", pace_seconds=0.5)

    async def get_news_sentiment_score(self, ticker: str) -> float:
        if not self.settings.marketaux_api_token:
            return 0.0

        params = {
            "api_token": self.settings.marketaux_api_token,
            "symbols": ticker,
            "language": "en",
            "limit": 10,
        }

        try:
            payload = await self._guard.cached_call(
                key=("news", ticker.upper()),
                ttl_seconds=max(self.settings.news_cache_minutes * 60, 60),
                stale_ttl_seconds=max(self.settings.news_cache_minutes * 120, 300),
                fetcher=lambda: self._fetch_news(params=params),
            )

            articles = payload.get("data", [])
            if not articles:
                return 0.0

            scores = []
            for article in articles:
                score = article.get("sentiment_score")
                if score is not None:
                    scores.append(float(score))

            if scores:
                avg = sum(scores) / len(scores)
                return round(max(min(avg, 1.0), -1.0), 4)

            return 0.0

        except Exception:
            return 0.0

    async def _fetch_news(self, *, params: dict[str, str | int]) -> dict:
        await self._guard.throttle()
        payload = await request_json(
            self._client,
            method="GET",
            url="https://api.marketaux.com/v1/news/all",
            params=params,
            provider="marketaux",
            on_backoff=self._guard.register_backoff,
        )
        return payload if isinstance(payload, dict) else {}