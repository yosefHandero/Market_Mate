"""Add prediction_snapshots table for structural range tracking."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260628_0012"
down_revision = "20260531_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "prediction_snapshots" not in set(inspector.get_table_names()):
        op.create_table(
            "prediction_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("ticker", sa.String(length=16), nullable=False, index=True),
            sa.Column("asset_type", sa.String(length=16), nullable=False, server_default="stock", index=True),
            sa.Column("signal", sa.String(length=16), nullable=False, index=True),
            sa.Column("evidence_grade", sa.String(length=16), nullable=False, server_default="Weak"),
            sa.Column("entry_price", sa.Float(), nullable=False),
            sa.Column("range_low", sa.Float(), nullable=False),
            sa.Column("range_high", sa.Float(), nullable=False),
            sa.Column("horizon", sa.String(length=16), nullable=False, server_default="1h", index=True),
            sa.Column("invalidation", sa.Text(), nullable=False, server_default=""),
            sa.Column("methodology", sa.String(length=32), nullable=False, server_default="structural_stop_target"),
            sa.Column("generated_at", sa.DateTime(), nullable=False, index=True),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending", index=True),
            sa.Column("price_at_horizon", sa.Float(), nullable=True),
            sa.Column("accuracy_outcome", sa.String(length=32), nullable=True, index=True),
            sa.Column("in_range", sa.Boolean(), nullable=True),
            sa.Column("evaluated_at", sa.DateTime(), nullable=True, index=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "prediction_snapshots" in set(inspector.get_table_names()):
        op.drop_table("prediction_snapshots")
