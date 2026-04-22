"""Add trust linkage fields to execution audits.

Revision ID: 20260325_0002
Revises: 20260321_0001
Create Date: 2026-03-25 00:00:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text


revision = "20260325_0002"
down_revision = "20260321_0001"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _existing_columns(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _existing_indexes(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column_name: str, column_sql: str) -> None:
    if column_name in _existing_columns(table_name):
        return
    op.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))


def upgrade() -> None:
    if not _has_table("execution_audits"):
        return

    _add_column_if_missing("execution_audits", "signal_outcome_id", "INTEGER")
    _add_column_if_missing("execution_audits", "trade_gate_horizon", "VARCHAR(16)")
    _add_column_if_missing("execution_audits", "evidence_basis", "VARCHAR(64)")
    _add_column_if_missing("execution_audits", "trust_window_start", "DATETIME")
    _add_column_if_missing("execution_audits", "trust_window_end", "DATETIME")

    existing_indexes = _existing_indexes("execution_audits")
    if "ix_execution_audits_signal_outcome_id" not in existing_indexes:
        op.create_index(
            "ix_execution_audits_signal_outcome_id",
            "execution_audits",
            ["signal_outcome_id"],
        )


def downgrade() -> None:
    # SQLite does not support dropping columns safely here.
    pass
