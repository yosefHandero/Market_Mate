from __future__ import annotations

import httpx

from app.config import get_settings
from app.http_client import request_json


class FearGreedClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds)

    async def get_index(self) -> tuple[int | None, str | None]:
        try:
            payload = await request_json(
                self._client,
                method="GET",
                url=self.settings.alt_fng_api_url,
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
