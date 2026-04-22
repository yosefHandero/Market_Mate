#!/usr/bin/env python3
"""Save GET /automation/status, /readyz, and /orders/audits for hourly burn-in evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCANNER_ROOT = Path(__file__).resolve().parent.parent
if str(SCANNER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCANNER_ROOT))


def _http_get_json(base_url: str, path: str, *, params: dict[str, str] | None, token: str | None) -> object:
    query = f"?{urlencode(params)}" if params else ""
    request = Request(f"{base_url.rstrip('/')}{path}{query}")
    if token:
        request.add_header("X-API-Key", token)
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _capture_once(base_url: str, token: str | None, output_dir: Path, label: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    automation = _http_get_json(base_url, "/automation/status", params=None, token=token)
    readyz = _http_get_json(base_url, "/readyz", params=None, token=token)
    audits = _http_get_json(base_url, "/orders/audits", params={"limit": "200"}, token=token)
    _write_json(output_dir / f"{label}-automation-status.json", automation)
    _write_json(output_dir / f"{label}-readyz.json", readyz)
    _write_json(output_dir / f"{label}-orders-audits.json", audits)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect hourly automation evidence JSON snapshots.")
    parser.add_argument("--base-url", default=os.environ.get("SCANNER_BASE_URL", "http://127.0.0.1:8005"))
    parser.add_argument(
        "--token",
        default=os.environ.get("SCANNER_READ_API_TOKEN") or os.environ.get("SCANNER_ADMIN_API_TOKEN"),
        help="X-API-Key for protected routes (or set SCANNER_READ_API_TOKEN).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(SCANNER_ROOT / "var" / "hourly-evidence"),
        help="Directory for JSON files.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="How many captures to take (default 1).",
    )
    parser.add_argument(
        "--interval-minutes",
        type=int,
        default=60,
        help="Sleep between iterations when iterations > 1.",
    )
    parser.add_argument(
        "--prefix",
        default="hour",
        help="Filename prefix (default hour); timestamp is always included.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    token = args.token or None
    if not token:
        print(
            "Warning: no --token or SCANNER_READ_API_TOKEN; protected routes may return 401.",
            file=sys.stderr,
        )

    for i in range(args.iterations):
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        label = f"{args.prefix}-{ts}"
        _capture_once(args.base_url, token, output_dir, label)
        print(output_dir / f"{label}-automation-status.json")
        if i + 1 < args.iterations:
            time.sleep(max(1, args.interval_minutes) * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
