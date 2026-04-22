from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.admin import router as admin_router
from app.api.public import protected_router as protected_public_router
from app.api.public import router as public_router
from app.config import get_settings
from app.db import apply_required_schema_patches
from app.dependencies import (
    automation_service,
    coinbase_market_data_service,
    execution_service,
    journal_repository,
    promotion_service,
    risk_service,
    scan_repository,
    scanner_service,
)
from app.errors import AppError
from app.logging_utils import configure_logging
from app.middleware import RequestContextMiddleware

settings = get_settings()
configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.cache_dir_path.mkdir(parents=True, exist_ok=True)
    market_data_task = None
    if coinbase_market_data_service.enabled:
        market_data_task = asyncio.create_task(
            coinbase_market_data_service.run_forever(),
            name="coinbase-advanced-trade-ws",
        )
    schema_patches = apply_required_schema_patches()
    repaired_rows = scan_repository.sync_signal_outcome_returns()
    relinked_audits = scan_repository.backfill_execution_audit_signal_links()
    recovered_automation_intents = await automation_service.recover_due_intents()
    logger.info(
        "startup completed",
        extra={
            "event": "startup",
            "schema_patches_applied": schema_patches,
            "repaired_signal_outcome_returns": repaired_rows,
            "relinked_execution_audits": relinked_audits,
            "recovered_automation_intents": recovered_automation_intents,
        },
    )
    try:
        yield
    finally:
        if market_data_task is not None:
            coinbase_market_data_service.stop()
            market_data_task.cancel()
            try:
                await market_data_task
            except asyncio.CancelledError:
                pass


def _error_response(request: Request, *, status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": message,
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
                "details": details or {},
            },
        },
    )


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origin_items,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _error_response(
            request,
            status_code=exc.status_code,
            code="http_error",
            message=detail,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unexpected request failure", extra={"event": "unhandled_exception"})
        return _error_response(
            request,
            status_code=500,
            code="internal_error",
            message="Internal server error.",
        )

    app.include_router(public_router)
    app.include_router(protected_public_router)
    app.include_router(admin_router)
    return app


app = create_app()