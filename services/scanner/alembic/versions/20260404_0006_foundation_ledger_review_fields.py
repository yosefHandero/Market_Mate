"""Add provenance, ledger, and review fields.

Revision ID: 20260404_0006
Revises: 20260330_0005
Create Date: 2026-04-04 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260404_0006"
down_revision = "20260330_0005"
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
    _add_column_if_missing("scan_results", "data_grade", "VARCHAR(16) DEFAULT 'research'")
    _add_column_if_missing("scan_results", "bar_age_minutes", "FLOAT")
    _add_column_if_missing("scan_results", "freshness_flags_json", "TEXT")

    _add_column_if_missing("signal_outcomes", "data_grade", "VARCHAR(16) DEFAULT 'research'")

    _add_column_if_missing("automation_intents", "incident_class", "VARCHAR(64)")

    _add_column_if_missing("journal_entries", "override_reason", "TEXT")
    _add_column_if_missing("journal_entries", "action_state", "VARCHAR(16)")

    if not _has_table("paper_positions"):
        op.create_table(
            "paper_positions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("intent_key", sa.String(length=255), nullable=False, unique=True),
            sa.Column("execution_audit_id", sa.Integer(), nullable=True),
            sa.Column("ticker", sa.String(length=16), nullable=False),
            sa.Column("asset_type", sa.String(length=16), nullable=False, server_default="stock"),
            sa.Column("side", sa.String(length=16), nullable=False),
            sa.Column("quantity", sa.Float(), nullable=False),
            sa.Column("simulated_fill_price", sa.Float(), nullable=False),
            sa.Column("notional_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("cost_basis_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("close_price", sa.Float(), nullable=True),
            sa.Column("realized_pnl", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
            sa.Column("opened_at", sa.DateTime(), nullable=False),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("strategy_version", sa.String(length=32), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
        )
        op.create_index("ix_paper_positions_created_at", "paper_positions", ["created_at"])
        op.create_index("ix_paper_positions_updated_at", "paper_positions", ["updated_at"])
        op.create_index("ix_paper_positions_intent_key", "paper_positions", ["intent_key"], unique=True)
        op.create_index("ix_paper_positions_execution_audit_id", "paper_positions", ["execution_audit_id"])
        op.create_index("ix_paper_positions_ticker", "paper_positions", ["ticker"])
        op.create_index("ix_paper_positions_asset_type", "paper_positions", ["asset_type"])
        op.create_index("ix_paper_positions_side", "paper_positions", ["side"])
        op.create_index("ix_paper_positions_status", "paper_positions", ["status"])
        op.create_index("ix_paper_positions_opened_at", "paper_positions", ["opened_at"])
        op.create_index("ix_paper_positions_closed_at", "paper_positions", ["closed_at"])
        op.create_index("ix_paper_positions_strategy_version", "paper_positions", ["strategy_version"])


def downgrade() -> None:
    pass
