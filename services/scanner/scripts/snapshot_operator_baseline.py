#!/usr/bin/env python3
"""Emit a JSON snapshot of frozen operator settings for burn-in / 95+ evidence runs.

Uses local Settings (same as the API process when run from the scanner service root).
Optionally probes livez, startupz, and readyz on a running API (--base-url).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SCANNER_ROOT = Path(__file__).resolve().parent.parent
if str(SCANNER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCANNER_ROOT))

from app.config import get_settings


def _http_get_json(base_url: str, path: str, *, token: str | None = None) -> dict:
    request = Request(f"{base_url.rstrip('/')}{path}")
    if token:
        request.add_header("X-API-Key", token)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _settings_freeze(settings) -> dict[str, object]:
    return {
        "app_env": settings.app_env,
        "app_version": settings.app_version,
        "app_instance_id": settings.app_instance_id,
        "health_max_stale_minutes": settings.health_max_stale_minutes,
        "require_readyz_for_execution": settings.require_readyz_for_execution,
        "scan_interval_seconds": settings.scan_interval_seconds,
        "scheduler_enabled": settings.scheduler_enabled,
        "scheduler_poll_seconds": settings.scheduler_poll_seconds,
        "execution_enabled": settings.execution_enabled,
        "allow_live_trading": settings.allow_live_trading,
        "paper_loop_enabled": settings.paper_loop_enabled,
        "paper_loop_phase": settings.paper_loop_phase,
        "paper_loop_kill_switch": settings.paper_loop_kill_switch,
        "paper_loop_max_actions_per_cycle": settings.paper_loop_max_actions_per_cycle,
        "paper_loop_max_requests_per_hour": settings.paper_loop_max_requests_per_hour,
        "paper_loop_max_requests_per_day": settings.paper_loop_max_requests_per_day,
        "paper_loop_max_requests_per_symbol_window": settings.paper_loop_max_requests_per_symbol_window,
        "paper_loop_symbol_window_seconds": settings.paper_loop_symbol_window_seconds,
        "paper_loop_claim_ttl_seconds": settings.paper_loop_claim_ttl_seconds,
        "paper_loop_retry_max_attempts": settings.paper_loop_retry_max_attempts,
        "paper_loop_retry_base_seconds": settings.paper_loop_retry_base_seconds,
        "paper_loop_retry_jitter_ratio": settings.paper_loop_retry_jitter_ratio,
        "paper_loop_breaker_failures_to_open": settings.paper_loop_breaker_failures_to_open,
        "paper_loop_breaker_failure_window_minutes": settings.paper_loop_breaker_failure_window_minutes,
        "paper_loop_breaker_open_minutes": settings.paper_loop_breaker_open_minutes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Print operator baseline JSON for evidence runs.")
    parser.add_argument(
        "--base-url",
        default=None,
        help="If set, GET /livez, /startupz, /readyz and merge under http_probe.",
    )
    parser.add_argument(
        "--read-token",
        default=None,
        help="If set with --base-url, also GET /automation/status (protected).",
    )
    args = parser.parse_args()

    settings = get_settings()
    payload: dict[str, object] = {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "settings_snapshot": _settings_freeze(settings),
    }

    if args.base_url:
        probe: dict[str, object | str] = {}
        for path in ("/livez", "/startupz", "/readyz"):
            try:
                probe[path] = _http_get_json(args.base_url, path)
            except HTTPError as exc:
                probe[path] = {"error": "http_error", "status": exc.code, "reason": str(exc.reason)}
            except URLError as exc:
                probe[path] = {"error": "url_error", "reason": str(exc.reason)}
        if args.read_token:
            try:
                probe["/automation/status"] = _http_get_json(
                    args.base_url, "/automation/status", token=args.read_token
                )
            except HTTPError as exc:
                probe["/automation/status"] = {
                    "error": "http_error",
                    "status": exc.code,
                    "reason": str(exc.reason),
                }
            except URLError as exc:
                probe["/automation/status"] = {"error": "url_error", "reason": str(exc.reason)}
        payload["http_probe"] = probe

    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
