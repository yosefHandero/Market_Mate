from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(
    settings.database_url,
    future=True,
    connect_args=connect_args,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)
Base = declarative_base()

REQUIRED_TABLE_COLUMNS: dict[str, dict[str, str]] = {
    "scan_runs": {
        "alerts_sent": "INTEGER DEFAULT 0",
        "fear_greed_value": "INTEGER",
        "fear_greed_label": "VARCHAR(32)",
    },
    "scan_results": {
        "asset_type": "VARCHAR(16) DEFAULT 'stock'",
        "calibrated_confidence": "FLOAT DEFAULT 0",
        "calibration_source": "VARCHAR(16) DEFAULT 'raw'",
        "buy_score": "FLOAT DEFAULT 0",
        "sell_score": "FLOAT DEFAULT 0",
        "decision_signal": "VARCHAR(16) DEFAULT 'HOLD'",
        "scoring_version": "VARCHAR(32) DEFAULT 'v2-directional'",
        "sector_strength_score": "FLOAT DEFAULT 0",
        "relative_strength_pct": "FLOAT DEFAULT 0",
        "options_flow_score": "FLOAT DEFAULT 0",
        "options_flow_summary": "TEXT DEFAULT 'No options signal.'",
        "options_flow_bullish": "BOOLEAN DEFAULT 0",
        "options_call_put_ratio": "FLOAT DEFAULT 0",
        "alert_sent": "BOOLEAN DEFAULT 0",
        "news_checked": "BOOLEAN DEFAULT 0",
        "news_source": "VARCHAR(32) DEFAULT 'none'",
        "news_cache_label": "TEXT",
        "signal_label": "VARCHAR(16) DEFAULT 'weak'",
        "data_quality": "VARCHAR(16) DEFAULT 'ok'",
        "volatility_regime": "VARCHAR(16) DEFAULT 'normal'",
        "benchmark_ticker": "VARCHAR(16)",
        "benchmark_change_pct": "FLOAT",
        "gate_passed": "BOOLEAN DEFAULT 0",
        "gate_reason": "TEXT DEFAULT 'Signal gate not evaluated.'",
        "gate_checks_json": "TEXT",
        "coingecko_price_change_pct_24h": "FLOAT",
        "coingecko_market_cap_rank": "INTEGER",
        "fear_greed_value": "INTEGER",
        "fear_greed_label": "VARCHAR(32)",
        "provider_status": "VARCHAR(16) DEFAULT 'ok'",
        "provider_warnings_json": "TEXT",
    },
    "signal_outcomes": {
        "asset_type": "VARCHAR(16) DEFAULT 'stock'",
        "confidence": "FLOAT DEFAULT 0",
        "calibrated_confidence": "FLOAT DEFAULT 0",
        "calibration_source": "VARCHAR(16) DEFAULT 'raw'",
        "raw_score": "FLOAT DEFAULT 0",
        "score_band": "VARCHAR(16) DEFAULT '0-59'",
        "scoring_version": "VARCHAR(32) DEFAULT 'v2-directional'",
        "market_status": "VARCHAR(16)",
        "buy_score": "FLOAT DEFAULT 0",
        "sell_score": "FLOAT DEFAULT 0",
        "signal_label": "VARCHAR(16)",
        "gate_passed": "BOOLEAN DEFAULT 0",
        "gate_reason": "TEXT",
        "news_source": "VARCHAR(32)",
        "relative_volume": "FLOAT",
        "price_change_pct": "FLOAT",
        "relative_strength_pct": "FLOAT",
        "options_flow_score": "FLOAT",
        "options_flow_bullish": "BOOLEAN",
        "volatility_regime": "VARCHAR(16)",
        "data_quality": "VARCHAR(16)",
        "benchmark_change_pct": "FLOAT",
        "price_after_15m": "FLOAT",
        "return_after_15m": "FLOAT",
        "evaluated_at_15m": "DATETIME",
        "status_15m": "VARCHAR(16) DEFAULT 'pending'",
        "price_after_1h": "FLOAT",
        "return_after_1h": "FLOAT",
        "evaluated_at_1h": "DATETIME",
        "status_1h": "VARCHAR(16) DEFAULT 'pending'",
        "price_after_1d": "FLOAT",
        "return_after_1d": "FLOAT",
        "evaluated_at_1d": "DATETIME",
        "status_1d": "VARCHAR(16) DEFAULT 'pending'",
    },
    "journal_entries": {
        "signal_label": "VARCHAR(16)",
        "score": "FLOAT",
        "news_source": "VARCHAR(32)",
        "notes": "TEXT DEFAULT ''",
    },
    "execution_audits": {
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
        "ticker": "VARCHAR(16)",
        "asset_type": "VARCHAR(16) DEFAULT 'stock'",
        "side": "VARCHAR(16)",
        "order_type": "VARCHAR(16)",
        "qty": "FLOAT",
        "dry_run": "BOOLEAN DEFAULT 0",
        "idempotency_key": "VARCHAR(128)",
        "lifecycle_status": "VARCHAR(32) DEFAULT 'previewed'",
        "latest_price": "FLOAT",
        "notional_estimate": "FLOAT",
        "signal_run_id": "VARCHAR(64)",
        "signal_generated_at": "DATETIME",
        "latest_signal": "VARCHAR(16)",
        "confidence": "FLOAT",
        "trade_gate_allowed": "BOOLEAN",
        "trade_gate_reason": "TEXT",
        "submitted": "BOOLEAN DEFAULT 0",
        "broker_order_id": "VARCHAR(64)",
        "broker_status": "VARCHAR(32)",
        "error_message": "TEXT",
        "preview_payload": "TEXT DEFAULT '{}'",
        "request_payload": "TEXT",
        "broker_payload": "TEXT",
    },
    "scheduler_state": {
        "scheduler_key": "VARCHAR(32)",
        "enabled": "BOOLEAN DEFAULT 0",
        "interval_seconds": "INTEGER DEFAULT 300",
        "lease_owner": "VARCHAR(64)",
        "lease_expires_at": "DATETIME",
        "next_run_at": "DATETIME",
        "last_run_started_at": "DATETIME",
        "last_run_finished_at": "DATETIME",
        "last_error": "TEXT",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    },
}


@dataclass(frozen=True)
class SchemaStatus:
    ok: bool
    applied_changes: list[str]
    missing_items: list[str]


def _missing_columns(table_name: str) -> list[str]:
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return [f"{table_name}.__missing_table__"]
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    return [
        f"{table_name}.{column_name}"
        for column_name in REQUIRED_TABLE_COLUMNS.get(table_name, {})
        if column_name not in columns
    ]


def ensure_schema() -> SchemaStatus:
    return get_schema_status()


def get_schema_status(*, applied_changes: list[str] | None = None) -> SchemaStatus:
    missing_items: list[str] = []
    for table_name in REQUIRED_TABLE_COLUMNS:
        missing_items.extend(_missing_columns(table_name))
    return SchemaStatus(
        ok=not missing_items,
        applied_changes=applied_changes or [],
        missing_items=missing_items,
    )


def check_database_connection() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


