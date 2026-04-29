from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header

from app.config import Settings, get_settings
from app.errors import AppError


def _extract_token(raw_value: str | None) -> str:
    if not raw_value:
        return ""
    value = raw_value.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value


def _require_token(
    *,
    provided_values: list[str | None],
    expected_token: str,
    error_message: str,
) -> None:
    provided = next((token for token in (_extract_token(value) for value in provided_values) if token), "")
    if not expected_token or not provided or not secrets.compare_digest(provided, expected_token):
        raise AppError(message=error_message, status_code=401, code="unauthorized")


def require_read_access(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.read_auth_required:
        return
    provided = next((token for token in (_extract_token(value) for value in [authorization, x_api_key]) if token), "")
    expected_tokens = [token for token in [settings.read_api_token, settings.admin_api_token] if token]
    if not provided or not any(secrets.compare_digest(provided, token) for token in expected_tokens):
        raise AppError(
            message="Read access requires a valid API token.",
            status_code=401,
            code="unauthorized",
        )


def require_admin_access(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.admin_auth_required:
        return
    _require_token(
        provided_values=[authorization, x_api_key],
        expected_token=settings.admin_api_token,
        error_message="Admin access requires a valid API token.",
    )
