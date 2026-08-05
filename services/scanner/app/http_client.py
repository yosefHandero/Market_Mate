from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

RETRY_JITTER_RATIO = 0.2
# Cap provider-dictated Retry-After / backoff sleeps. A single 429 carrying a
# large Retry-After must not freeze a scan for minutes while the provider guard
# holds its pace lock. Matches RATE_LIMIT_COOLDOWN_SECONDS in provider_resilience.
MAX_RETRY_BACKOFF_SECONDS = 60.0


class ProviderRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        url: str,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.url = url
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.status_code = status_code


def _apply_retry_jitter(delay_seconds: float) -> float:
    if delay_seconds <= 0:
        return 0.0
    return delay_seconds * (1.0 + random.uniform(0.0, RETRY_JITTER_RATIO))


def _body_preview(response: httpx.Response) -> str:
    try:
        text = response.text
    except Exception:
        return ""
    return text[:240].strip()


def _looks_like_html(payload: str) -> bool:
    snippet = payload.lstrip().lower()
    return snippet.startswith("<!doctype html") or snippet.startswith("<html") or snippet.startswith("<body")


def _parse_retry_after(header_value: str | None) -> float | None:
    if not header_value:
        return None
    raw = header_value.strip()
    if not raw:
        return None
    try:
        return max(float(raw), 0.0)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except Exception:
            return None
        return max((parsed - datetime.now(parsed.tzinfo)).total_seconds(), 0.0)


def _raise_response_error(response: httpx.Response, *, provider: str, url: str) -> None:
    status_code = response.status_code
    preview = _body_preview(response)
    lowered_preview = preview.lower()
    content_type = (response.headers.get("content-type") or "").lower()
    retry_after = _parse_retry_after(response.headers.get("retry-after"))
    throttled = status_code == 429 or "rate limit" in lowered_preview or "throttl" in lowered_preview
    blocked = any(
        token in lowered_preview
        for token in ("access denied", "forbidden", "captcha", "cloudflare", "temporarily unavailable")
    )
    upstream_temporary = status_code in {408, 425, 500, 502, 503, 504}

    if throttled:
        raise ProviderRequestError(
            f"{provider} rate limited request to {url}",
            provider=provider,
            url=url,
            retryable=True,
            retry_after_seconds=retry_after,
            status_code=status_code,
        )
    if upstream_temporary:
        raise ProviderRequestError(
            f"{provider} temporary failure for {url} (status {status_code})",
            provider=provider,
            url=url,
            retryable=True,
            retry_after_seconds=retry_after,
            status_code=status_code,
        )
    if status_code == 403 and blocked:
        raise ProviderRequestError(
            f"{provider} blocked request to {url}",
            provider=provider,
            url=url,
            retryable=True,
            retry_after_seconds=retry_after,
            status_code=status_code,
        )
    if status_code >= 400:
        raise ProviderRequestError(
            f"{provider} returned HTTP {status_code} for {url}",
            provider=provider,
            url=url,
            retryable=False,
            status_code=status_code,
        )
    if "json" not in content_type and preview:
        retryable = _looks_like_html(preview) or blocked
        raise ProviderRequestError(
            f"{provider} returned non-JSON content for {url}",
            provider=provider,
            url=url,
            retryable=retryable,
            status_code=status_code,
        )


def parse_json_response(
    response: httpx.Response,
    *,
    provider: str,
    url: str,
) -> Any:
    _raise_response_error(response, provider=provider, url=url)

    preview = _body_preview(response)
    if _looks_like_html(preview):
        raise ProviderRequestError(
            f"{provider} returned HTML instead of JSON for {url}",
            provider=provider,
            url=url,
            retryable=True,
            status_code=response.status_code,
        )

    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise ProviderRequestError(
            f"{provider} returned invalid JSON for {url}",
            provider=provider,
            url=url,
            retryable=_looks_like_html(preview) or "temporarily unavailable" in preview.lower(),
            status_code=response.status_code,
        ) from exc


async def request_json(
    client: httpx.AsyncClient,
    *,
    method: str,
    url: str,
    provider: str = "external_provider",
    on_backoff: Callable[..., Awaitable[None] | None] | None = None,
    **kwargs: Any,
) -> Any:
    settings = get_settings()
    last_error: Exception | None = None
    max_attempts = settings.provider_retry_attempts + 1
    for attempt in range(1, max_attempts + 2):
        try:
            response = await client.request(method, url, **kwargs)
            return parse_json_response(response, provider=provider, url=url)
        except ProviderRequestError as exc:
            last_error = exc
            if exc.status_code == 429:
                logger.warning(
                    "provider rate limited",
                    extra={
                        "event": "provider_rate_limited",
                        "provider": provider,
                        "url": url,
                        "status_code": exc.status_code,
                        "retry_after_seconds": exc.retry_after_seconds,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                    },
                )
            if not exc.retryable or attempt > settings.provider_retry_attempts:
                raise
            delay_seconds = _apply_retry_jitter(
                min(
                    max(
                        settings.provider_retry_backoff_seconds * attempt,
                        float(exc.retry_after_seconds or 0.0),
                    ),
                    MAX_RETRY_BACKOFF_SECONDS,
                )
            )
            logger.info(
                "provider retry scheduled",
                extra={
                    "event": "provider_retry",
                    "provider": provider,
                    "url": url,
                    "attempt": attempt,
                    "delay_seconds": round(delay_seconds, 3),
                    "status_code": exc.status_code,
                },
            )
            if on_backoff is not None:
                maybe_result = on_backoff(
                    delay_seconds,
                    rate_limited=exc.status_code == 429,
                )
                if asyncio.iscoroutine(maybe_result):
                    await maybe_result
            await asyncio.sleep(delay_seconds)
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            last_error = exc
            if attempt > settings.provider_retry_attempts:
                raise
            delay_seconds = _apply_retry_jitter(settings.provider_retry_backoff_seconds * attempt)
            logger.warning(
                "provider request timeout or transport error",
                extra={
                    "event": "provider_timeout",
                    "provider": provider,
                    "url": url,
                    "attempt": attempt,
                    "delay_seconds": round(delay_seconds, 3),
                    "error_type": type(exc).__name__,
                },
            )
            if on_backoff is not None:
                maybe_result = on_backoff(delay_seconds, rate_limited=False)
                if asyncio.iscoroutine(maybe_result):
                    await maybe_result
            await asyncio.sleep(delay_seconds)
    raise RuntimeError(f"Request failed for {url}: {last_error}")
