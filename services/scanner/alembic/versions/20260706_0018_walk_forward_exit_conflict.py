"""Add exit_conflict column to walk_forward_predictions."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260706_0018"
down_revision = "20260706_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "walk_forward_predictions" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("walk_forward_predictions")}
    if "exit_conflict" not in columns:
        op.add_column(
            "walk_forward_predictions",
            sa.Column("exit_conflict", sa.Boolean(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "walk_forward_predictions" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("walk_forward_predictions")}
    if "exit_conflict" in columns:
        op.drop_column("walk_forward_predictions", "exit_conflict")
