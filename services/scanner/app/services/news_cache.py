from __future__ import annotations

import math
import time

from app.clients.news_result import NEWS_LOOKBACK_DAYS
from app.config import get_settings
from app.services.provider_coordination import ProviderCoordination, content_key


class NewsCacheService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.coordination = ProviderCoordination(self.settings.cache_dir_path)

    def _key(self, ticker: str) -> str:
        # Legacy JSON can contain failures encoded as neutral; leave it intact
        # and exclude it from the new success-only cache.
        return content_key(["combined-news-v4", ticker.upper(), self.settings.marketaux_api_token,
                            self.settings.finnhub_api_key, "en", 10, NEWS_LOOKBACK_DAYS])

    def get(self, ticker: str) -> tuple[float | None, str | None]:
        item = self.coordination.read_cache(self._key(ticker))
        if item is None:
            return None, None
        age_minutes = max(0, int((time.time() - item["checked_at"]) // 60))
        label = f"Cached news from {age_minutes} minute(s) ago"
        return float(item["sentiment_score"]), label

    def set(self, ticker: str, sentiment_score: float) -> None:
        if sentiment_score is None or not math.isfinite(sentiment_score):
            raise ValueError("Only successful finite sentiment results may be cached")
        self.coordination.write_cache(self._key(ticker), {
            "sentiment_score": sentiment_score,
            "checked_at": time.time(),
        }, self.settings.news_cache_minutes * 60)
