"""Add idempotency payload hash to execution audits.

Revision ID: 20260326_0003
Revises: 20260325_0002
Create Date: 2026-03-26 00:00:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text


revision = "20260326_0003"
down_revision = "20260325_0002"
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
    if not _has_table("execution_audits"):
        return
    _add_column_if_missing(
        "execution_audits",
        "idempotency_payload_hash",
        "VARCHAR(64)",
    )


def downgrade() -> None:
    pass
