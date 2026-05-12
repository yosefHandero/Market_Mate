"""Add recommended action snapshot to execution audits.

Revision ID: 20260513_0008
Revises: 20260512_0007
Create Date: 2026-05-13 00:00:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text


revision = "20260513_0008"
down_revision = "20260512_0007"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _existing_columns(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if not _has_table("execution_audits"):
        return
    if "recommended_action_snapshot" in _existing_columns("execution_audits"):
        return
    op.execute(
        text(
            "ALTER TABLE execution_audits "
            "ADD COLUMN recommended_action_snapshot VARCHAR(16)"
        )
    )


def downgrade() -> None:
    if "recommended_action_snapshot" not in _existing_columns("execution_audits"):
        return
    with op.batch_alter_table("execution_audits") as batch_op:
        batch_op.drop_column("recommended_action_snapshot")
