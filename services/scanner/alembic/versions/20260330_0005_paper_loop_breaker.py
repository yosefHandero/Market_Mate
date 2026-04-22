"""Persisted paper-loop circuit breaker row.

Revision ID: 20260330_0005
Revises: 20260330_0004
Create Date: 2026-03-30 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260330_0005"
down_revision = "20260330_0004"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("paper_loop_breaker"):
        return

    op.create_table(
        "paper_loop_breaker",
        sa.Column("breaker_key", sa.String(length=32), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=False, server_default="closed"),
        sa.Column("open_until", sa.DateTime(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("failures_in_window", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failures_window_started_at", sa.DateTime(), nullable=True),
        sa.Column("probe_owner", sa.String(length=64), nullable=True),
        sa.Column("probe_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("breaker_key"),
    )
    op.create_index("ix_paper_loop_breaker_phase", "paper_loop_breaker", ["phase"])
    op.create_index("ix_paper_loop_breaker_open_until", "paper_loop_breaker", ["open_until"])
    op.create_index("ix_paper_loop_breaker_probe_owner", "paper_loop_breaker", ["probe_owner"])
    op.create_index("ix_paper_loop_breaker_probe_expires_at", "paper_loop_breaker", ["probe_expires_at"])
    op.create_index("ix_paper_loop_breaker_updated_at", "paper_loop_breaker", ["updated_at"])


def downgrade() -> None:
    pass
