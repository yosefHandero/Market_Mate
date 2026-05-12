"""Add maintenance state table.

Revision ID: 20260514_0009
Revises: 20260513_0008
Create Date: 2026-05-14 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260514_0009"
down_revision = "20260513_0008"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("maintenance_state"):
        return

    op.create_table(
        "maintenance_state",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("last_sync_signal_returns_at", sa.DateTime(), nullable=True),
        sa.Column("last_backfill_audit_links_at", sa.DateTime(), nullable=True),
        sa.Column("last_recover_due_intents_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    if not _has_table("maintenance_state"):
        return

    op.drop_table("maintenance_state")
