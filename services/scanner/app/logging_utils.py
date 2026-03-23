from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.config import get_settings
from app.request_context import get_request_id


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key in ("event", "code", "ticker", "run_id", "path", "method"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    if getattr(root, "_market_mate_configured", False):
        return

    handler = logging.StreamHandler()
    if settings.log_json:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
            )
        )

    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    root._market_mate_configured = True  # type: ignore[attr-defined]
