from __future__ import annotations

import httpx

from app.config import get_settings
from app.http_client import request_json


class MarketauxClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)

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
            payload = await request_json(
                self._client,
                method="GET",
                url="https://api.marketaux.com/v1/news/all",
                params=params,
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