from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.observability import metrics
from app.request_context import request_id_var

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        token = request_id_var.set(request_id)
        started_at = perf_counter()
        request.state.request_id = request_id

        try:
            response = await call_next(request)
            elapsed = perf_counter() - started_at
            response.headers["X-Request-ID"] = request_id
            metrics.increment(f"http.requests.{request.method}.{request.url.path}")
            metrics.observe_duration("http.request.duration", elapsed)
            logger.info(
                "request completed",
                extra={
                    "event": "http_request",
                    "path": request.url.path,
                    "method": request.method,
                    "status_code": response.status_code,
                },
            )
            return response
        finally:
            request_id_var.reset(token)
