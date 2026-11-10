from dataclasses import dataclass

import httpx

from app.http_client import ProviderRequestError
from app.services.provider_coordination import CoordinationBlocked

NEWS_LOOKBACK_DAYS = 7


@dataclass(frozen=True)
class NewsResult:
    score: float | None
    status: str = "ok"
    endpoint: str | None = None
    http_status: int | None = None
    lookback_start: str | None = None
    latest_article_at: str | None = None


def news_request_failure(error: Exception, *, endpoint: str | None = None) -> NewsResult:
    if isinstance(error, CoordinationBlocked):
        # The coordination store raises fixed codes, independent of remote input.
        return NewsResult(None, str(error), endpoint)
    if isinstance(error, ProviderRequestError):
        status = {
            401: "authentication_failed",
            403: "access_denied",
            408: "timeout",
            429: "rate_limited",
        }.get(error.status_code, "provider_error")
        if error.status_code is not None and 500 <= error.status_code < 600:
            status = "provider_server_error"
        elif isinstance(error.__cause__, (httpx.TimeoutException, TimeoutError)):
            status = "timeout"
        elif isinstance(error.__cause__, httpx.TransportError):
            status = "transport_error"
        return NewsResult(None, status, error.url or endpoint, error.status_code)
    if isinstance(error, (httpx.TimeoutException, TimeoutError)):
        return NewsResult(None, "timeout", endpoint)
    if isinstance(error, httpx.TransportError):
        return NewsResult(None, "transport_error", endpoint)
    return NewsResult(None, "provider_error", endpoint)
