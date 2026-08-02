"""Add persistent daily_bar_history table for walk-forward proof caching."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260706_0016"
down_revision = "20260705_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "daily_bar_history" in set(inspector.get_table_names()):
        return
    op.create_table(
        "daily_bar_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=24), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False, server_default="stock"),
        sa.Column("bar_date", sa.String(length=10), nullable=False),
        sa.Column("bar_ts", sa.String(length=40), nullable=False),
        sa.Column("open", sa.Float(), nullable=False, server_default="0"),
        sa.Column("high", sa.Float(), nullable=False, server_default="0"),
        sa.Column("low", sa.Float(), nullable=False, server_default="0"),
        sa.Column("close", sa.Float(), nullable=False, server_default="0"),
        sa.Column("volume", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="alpaca"),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "symbol", "asset_type", "bar_date", name="uq_daily_bar_history_symbol_asset_date"
        ),
    )
    op.create_index("ix_daily_bar_history_symbol", "daily_bar_history", ["symbol"])
    op.create_index("ix_daily_bar_history_asset_type", "daily_bar_history", ["asset_type"])
    op.create_index("ix_daily_bar_history_bar_date", "daily_bar_history", ["bar_date"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "daily_bar_history" not in set(inspector.get_table_names()):
        return
    op.drop_table("daily_bar_history")
