"""Add weekly horizon columns and sample_source taxonomy."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260629_0014"
down_revision = "20260628_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    signal_columns = {column["name"] for column in inspector.get_columns("signal_outcomes")}
    if "price_after_1w" not in signal_columns:
        op.add_column("signal_outcomes", sa.Column("price_after_1w", sa.Float(), nullable=True))
        op.add_column("signal_outcomes", sa.Column("return_after_1w", sa.Float(), nullable=True))
        op.add_column("signal_outcomes", sa.Column("evaluated_at_1w", sa.DateTime(), nullable=True))
        op.add_column("signal_outcomes", sa.Column("status_1w", sa.String(length=16), server_default="pending", nullable=False))
        op.add_column("signal_outcomes", sa.Column("sample_source", sa.String(length=32), server_default="live_paper_forward", nullable=False))
        op.add_column("signal_outcomes", sa.Column("pattern_name", sa.String(length=64), nullable=True))

    if "prediction_snapshots" in set(inspector.get_table_names()):
        prediction_columns = {column["name"] for column in inspector.get_columns("prediction_snapshots")}
        if "sample_source" not in prediction_columns:
            op.add_column(
                "prediction_snapshots",
                sa.Column("sample_source", sa.String(length=32), server_default="live_paper_forward", nullable=False),
            )
            op.add_column("prediction_snapshots", sa.Column("pattern_name", sa.String(length=64), nullable=True))
            op.add_column("prediction_snapshots", sa.Column("pattern_metadata_json", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    signal_columns = {column["name"] for column in inspector.get_columns("signal_outcomes")}
    for column in ("pattern_name", "sample_source", "status_1w", "evaluated_at_1w", "return_after_1w", "price_after_1w"):
        if column in signal_columns:
            op.drop_column("signal_outcomes", column)

    if "prediction_snapshots" in set(inspector.get_table_names()):
        prediction_columns = {column["name"] for column in inspector.get_columns("prediction_snapshots")}
        for column in ("pattern_metadata_json", "pattern_name", "sample_source"):
            if column in prediction_columns:
                op.drop_column("prediction_snapshots", column)
