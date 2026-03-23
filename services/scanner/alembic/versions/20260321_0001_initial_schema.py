"""Create production-ready scanner schema.

Revision ID: 20260321_0001
Revises:
Create Date: 2026-03-21 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260321_0001"
down_revision = None
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _existing_columns(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _add_column_if_missing(table_name: str, column_name: str, column_sql: str) -> None:
    if column_name in _existing_columns(table_name):
        return
    op.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))


def upgrade() -> None:
    if not _has_table("scan_runs"):
        op.create_table(
            "scan_runs",
            sa.Column("run_id", sa.String(length=64), primary_key=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("market_status", sa.String(length=16), nullable=False),
            sa.Column("scan_count", sa.Integer(), nullable=False),
            sa.Column("watchlist_size", sa.Integer(), nullable=False),
            sa.Column("alerts_sent", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("fear_greed_value", sa.Integer(), nullable=True),
            sa.Column("fear_greed_label", sa.String(length=32), nullable=True),
        )
        op.create_index("ix_scan_runs_created_at", "scan_runs", ["created_at"])
        op.create_index("ix_scan_runs_market_status", "scan_runs", ["market_status"])

    if not _has_table("scan_results"):
        op.create_table(
            "scan_results",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("ticker", sa.String(length=16), nullable=False),
            sa.Column("asset_type", sa.String(length=16), nullable=False, server_default="stock"),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("calibrated_confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("calibration_source", sa.String(length=16), nullable=False, server_default="raw"),
            sa.Column("buy_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("sell_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("decision_signal", sa.String(length=16), nullable=False, server_default="HOLD"),
            sa.Column("scoring_version", sa.String(length=32), nullable=False, server_default="v2-directional"),
            sa.Column("explanation", sa.Text(), nullable=False),
            sa.Column("price", sa.Float(), nullable=False),
            sa.Column("price_change_pct", sa.Float(), nullable=False),
            sa.Column("relative_volume", sa.Float(), nullable=False),
            sa.Column("sentiment_score", sa.Float(), nullable=False),
            sa.Column("filing_flag", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("breakout_flag", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("market_status", sa.String(length=16), nullable=False),
            sa.Column("sector_strength_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("relative_strength_pct", sa.Float(), nullable=False, server_default="0"),
            sa.Column("options_flow_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("options_flow_summary", sa.Text(), nullable=False, server_default="No options signal."),
            sa.Column("options_flow_bullish", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("options_call_put_ratio", sa.Float(), nullable=False, server_default="0"),
            sa.Column("alert_sent", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("news_checked", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("news_source", sa.String(length=32), nullable=False, server_default="none"),
            sa.Column("news_cache_label", sa.Text(), nullable=True),
            sa.Column("signal_label", sa.String(length=16), nullable=False, server_default="weak"),
            sa.Column("data_quality", sa.String(length=16), nullable=False, server_default="ok"),
            sa.Column("volatility_regime", sa.String(length=16), nullable=False, server_default="normal"),
            sa.Column("benchmark_ticker", sa.String(length=16), nullable=True),
            sa.Column("benchmark_change_pct", sa.Float(), nullable=True),
            sa.Column("gate_passed", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("gate_reason", sa.Text(), nullable=False, server_default="Signal gate not evaluated."),
            sa.Column("gate_checks_json", sa.Text(), nullable=True),
            sa.Column("coingecko_price_change_pct_24h", sa.Float(), nullable=True),
            sa.Column("coingecko_market_cap_rank", sa.Integer(), nullable=True),
            sa.Column("fear_greed_value", sa.Integer(), nullable=True),
            sa.Column("fear_greed_label", sa.String(length=32), nullable=True),
            sa.Column("provider_status", sa.String(length=16), nullable=False, server_default="ok"),
            sa.Column("provider_warnings_json", sa.Text(), nullable=True),
        )

    if not _has_table("signal_outcomes"):
        op.create_table(
            "signal_outcomes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(length=64), nullable=False),
            sa.Column("ticker", sa.String(length=16), nullable=False),
            sa.Column("asset_type", sa.String(length=16), nullable=False, server_default="stock"),
            sa.Column("signal", sa.String(length=16), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("calibrated_confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("calibration_source", sa.String(length=16), nullable=False, server_default="raw"),
            sa.Column("raw_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("score_band", sa.String(length=16), nullable=False, server_default="0-59"),
            sa.Column("scoring_version", sa.String(length=32), nullable=False, server_default="v2-directional"),
            sa.Column("market_status", sa.String(length=16), nullable=True),
            sa.Column("buy_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("sell_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("signal_label", sa.String(length=16), nullable=True),
            sa.Column("gate_passed", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("gate_reason", sa.Text(), nullable=True),
            sa.Column("news_source", sa.String(length=32), nullable=True),
            sa.Column("relative_volume", sa.Float(), nullable=True),
            sa.Column("price_change_pct", sa.Float(), nullable=True),
            sa.Column("relative_strength_pct", sa.Float(), nullable=True),
            sa.Column("options_flow_score", sa.Float(), nullable=True),
            sa.Column("options_flow_bullish", sa.Boolean(), nullable=True),
            sa.Column("volatility_regime", sa.String(length=16), nullable=True),
            sa.Column("data_quality", sa.String(length=16), nullable=True),
            sa.Column("benchmark_change_pct", sa.Float(), nullable=True),
            sa.Column("entry_price", sa.Float(), nullable=False),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
            sa.Column("price_after_15m", sa.Float(), nullable=True),
            sa.Column("return_after_15m", sa.Float(), nullable=True),
            sa.Column("evaluated_at_15m", sa.DateTime(), nullable=True),
            sa.Column("status_15m", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("price_after_1h", sa.Float(), nullable=True),
            sa.Column("return_after_1h", sa.Float(), nullable=True),
            sa.Column("evaluated_at_1h", sa.DateTime(), nullable=True),
            sa.Column("status_1h", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("price_after_1d", sa.Float(), nullable=True),
            sa.Column("return_after_1d", sa.Float(), nullable=True),
            sa.Column("evaluated_at_1d", sa.DateTime(), nullable=True),
            sa.Column("status_1d", sa.String(length=16), nullable=False, server_default="pending"),
        )

    if not _has_table("journal_entries"):
        op.create_table(
            "journal_entries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("ticker", sa.String(length=16), nullable=False),
            sa.Column("run_id", sa.String(length=64), nullable=True),
            sa.Column("decision", sa.String(length=16), nullable=False),
            sa.Column("entry_price", sa.Float(), nullable=True),
            sa.Column("exit_price", sa.Float(), nullable=True),
            sa.Column("pnl_pct", sa.Float(), nullable=True),
            sa.Column("signal_label", sa.String(length=16), nullable=True),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("news_source", sa.String(length=32), nullable=True),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _has_table("execution_audits"):
        op.create_table(
            "execution_audits",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("ticker", sa.String(length=16), nullable=False),
            sa.Column("asset_type", sa.String(length=16), nullable=False, server_default="stock"),
            sa.Column("side", sa.String(length=16), nullable=False),
            sa.Column("order_type", sa.String(length=16), nullable=False),
            sa.Column("qty", sa.Float(), nullable=False),
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("idempotency_key", sa.String(length=128), nullable=True),
            sa.Column("lifecycle_status", sa.String(length=32), nullable=False, server_default="previewed"),
            sa.Column("latest_price", sa.Float(), nullable=True),
            sa.Column("notional_estimate", sa.Float(), nullable=True),
            sa.Column("signal_run_id", sa.String(length=64), nullable=True),
            sa.Column("signal_generated_at", sa.DateTime(), nullable=True),
            sa.Column("latest_signal", sa.String(length=16), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("trade_gate_allowed", sa.Boolean(), nullable=True),
            sa.Column("trade_gate_reason", sa.Text(), nullable=True),
            sa.Column("submitted", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("broker_order_id", sa.String(length=64), nullable=True),
            sa.Column("broker_status", sa.String(length=32), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("preview_payload", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("request_payload", sa.Text(), nullable=True),
            sa.Column("broker_payload", sa.Text(), nullable=True),
        )

    if not _has_table("scheduler_state"):
        op.create_table(
            "scheduler_state",
            sa.Column("scheduler_key", sa.String(length=32), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="300"),
            sa.Column("lease_owner", sa.String(length=64), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
            sa.Column("next_run_at", sa.DateTime(), nullable=True),
            sa.Column("last_run_started_at", sa.DateTime(), nullable=True),
            sa.Column("last_run_finished_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    legacy_additions = {
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

    for table_name, columns in legacy_additions.items():
        for column_name, column_sql in columns.items():
            _add_column_if_missing(table_name, column_name, column_sql)


def downgrade() -> None:
    pass
