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
from app.config_doctor import diagnose_scanner_env
from app.db import get_schema_status
from app.dependencies import (
    automation_service,
    execution_service,
    promotion_service,
    risk_service,
    scan_repository,
    scanner_service,
)
from app.errors import AppError
from app.logging_utils import configure_logging
from app.middleware import RequestContextMiddleware
from app.services.startup_maintenance import StartupMaintenanceService

settings = get_settings()
configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.cache_dir_path.mkdir(parents=True, exist_ok=True)
    # Paper-only enforcement now lives in Settings.forbid_live_execution, so any
    # process that reaches this point has already validated that live-execution
    # flags are false. ExecutionService keeps a per-request safeguard as well.
    # Coinbase WebSocket runs in the worker process only to avoid duplicate connections
    # when API and worker are both up during wake-and-scan windows.
    schema_status = get_schema_status()
    logger.info(
        "startup schema status",
        extra={
            "event": "startup_schema_status",
            "ok": schema_status.ok,
            "missing_items": schema_status.missing_items,
        },
    )
    env_report = diagnose_scanner_env()
    if env_report.duplicate_keys or env_report.unused_keys or env_report.likely_misconfigured:
        logger.warning(
            "scanner env configuration issues detected",
            extra={
                "event": "startup_env_config_warning",
                "duplicate_key_count": len(env_report.duplicate_keys),
                "unused_key_count": len(env_report.unused_keys),
                "likely_misconfigured_count": len(env_report.likely_misconfigured),
                "duplicate_keys": env_report.duplicate_keys,
                "unused_keys": env_report.unused_keys,
                "likely_misconfigured": env_report.likely_misconfigured,
            },
        )
    startup_maintenance_result = None
    try:
        startup_maintenance_result = await asyncio.wait_for(
            StartupMaintenanceService(
                sync_signal_outcome_returns=scan_repository.sync_signal_outcome_returns,
                backfill_execution_audit_signal_links=scan_repository.backfill_execution_audit_signal_links,
                recover_due_intents=automation_service.recover_due_intents,
            ).run_if_due(),
            timeout=settings.startup_check_timeout_seconds,
        )
    except TimeoutError:
        logger.warning(
            "startup maintenance exceeded timeout",
            extra={
                "event": "startup_maintenance_timeout",
                "timeout_seconds": settings.startup_check_timeout_seconds,
            },
        )
    logger.info(
        "startup completed",
        extra={
            "event": "startup",
            "schema_ok": schema_status.ok,
            "missing_schema_items": schema_status.missing_items,
            "repaired_signal_outcome_returns": (
                startup_maintenance_result.repaired_signal_outcome_returns
                if startup_maintenance_result
                else None
            ),
            "relinked_execution_audits": (
                startup_maintenance_result.relinked_execution_audits
                if startup_maintenance_result
                else None
            ),
            "recovered_automation_intents": (
                startup_maintenance_result.recovered_automation_intents
                if startup_maintenance_result
                else None
            ),
            "startup_maintenance_ran_tasks": (
                list(startup_maintenance_result.ran_tasks) if startup_maintenance_result else []
            ),
            "startup_maintenance_skipped_tasks": (
                list(startup_maintenance_result.skipped_tasks) if startup_maintenance_result else []
            ),
        },
    )
    yield


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
        if isinstance(exc.detail, dict):
            message = str(exc.detail.get("message", "Request failed."))
            details = exc.detail
        elif isinstance(exc.detail, str):
            message = exc.detail
            details = {}
        else:
            message = "Request failed."
            details = {}
        return _error_response(
            request,
            status_code=exc.status_code,
            code="http_error",
            message=message,
            details=details,
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
    app.include_router(admin_router)
    app.include_router(protected_public_router)
    return app


app = create_app()
