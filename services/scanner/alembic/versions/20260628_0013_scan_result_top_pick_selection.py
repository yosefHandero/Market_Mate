"""Add readiness and official top-pick selection columns to scan_results."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260628_0013"
down_revision = "20260628_0012"
branch_labels = None
depends_on = None


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing = _existing_columns("scan_results")
    if "readiness_score" not in existing:
        op.add_column(
            "scan_results",
            sa.Column("readiness_score", sa.Float(), nullable=False, server_default="0"),
        )
    if "readiness_band" not in existing:
        op.add_column(
            "scan_results",
            sa.Column("readiness_band", sa.String(length=16), nullable=False, server_default="none"),
        )
    if "readiness_hard_stop" not in existing:
        op.add_column(
            "scan_results",
            sa.Column("readiness_hard_stop", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "readiness_reason" not in existing:
        op.add_column("scan_results", sa.Column("readiness_reason", sa.Text(), nullable=True))
    if "selection_rank" not in existing:
        op.add_column("scan_results", sa.Column("selection_rank", sa.Integer(), nullable=True))
    if "is_top_pick" not in existing:
        op.add_column(
            "scan_results",
            sa.Column("is_top_pick", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    existing = _existing_columns("scan_results")
    if "is_top_pick" in existing:
        op.drop_column("scan_results", "is_top_pick")
    if "selection_rank" in existing:
        op.drop_column("scan_results", "selection_rank")
    if "readiness_reason" in existing:
        op.drop_column("scan_results", "readiness_reason")
    if "readiness_hard_stop" in existing:
        op.drop_column("scan_results", "readiness_hard_stop")
    if "readiness_band" in existing:
        op.drop_column("scan_results", "readiness_band")
    if "readiness_score" in existing:
        op.drop_column("scan_results", "readiness_score")
