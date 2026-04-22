from __future__ import annotations

import httpx

from app.config import get_settings
from app.http_client import request_json
from app.provider_resilience import AsyncProviderGuard


class FearGreedClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)
        self._guard = AsyncProviderGuard("fear_greed", pace_seconds=1.0)

    async def get_index(self) -> tuple[int | None, str | None]:
        try:
            payload = await self._guard.cached_call(
                key=("fear_greed_index",),
                ttl_seconds=self.settings.fear_greed_cache_seconds,
                stale_ttl_seconds=max(self.settings.fear_greed_cache_seconds * 6, 1800),
                fetcher=self._fetch_index,
            )
        except Exception:
            return None, None

        row = (payload.get("data") or [{}])[0]
        value = row.get("value")
        if value is None:
            return None, None
        try:
            return int(value), row.get("value_classification")
        except Exception:
            return None, row.get("value_classification")

    async def _fetch_index(self) -> dict:
        await self._guard.throttle()
        payload = await request_json(
            self._client,
            method="GET",
            url=self.settings.alt_fng_api_url,
            provider="fear_greed",
            on_backoff=self._guard.register_backoff,
        )
        return payload if isinstance(payload, dict) else {}
