from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import get_settings


async def request_json(
    client: httpx.AsyncClient,
    *,
    method: str,
    url: str,
    **kwargs: Any,
) -> Any:
    settings = get_settings()
    last_error: Exception | None = None
    for attempt in range(1, settings.provider_retry_attempts + 2):
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt > settings.provider_retry_attempts:
                raise
            await asyncio.sleep(settings.provider_retry_backoff_seconds * attempt)
    raise RuntimeError(f"Request failed for {url}: {last_error}")
