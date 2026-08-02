"""Add bar_as_of to scan_results and strategy_replay_runs table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260531_0011"
down_revision = "20260518_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("scan_results")}
    if "bar_as_of" not in columns:
        op.add_column("scan_results", sa.Column("bar_as_of", sa.DateTime(), nullable=True))

    tables = set(inspector.get_table_names())
    if "strategy_replay_runs" not in tables:
        op.create_table(
            "strategy_replay_runs",
            sa.Column("replay_id", sa.String(length=64), primary_key=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
            sa.Column("request_json", sa.Text(), nullable=False, default="{}"),
            sa.Column("response_json", sa.Text(), nullable=False, default="{}"),
            sa.Column("symbol_count", sa.Integer(), nullable=False, default=0),
            sa.Column("snapshot_count", sa.Integer(), nullable=False, default=0),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "strategy_replay_runs" in tables:
        op.drop_table("strategy_replay_runs")
    columns = {column["name"] for column in inspector.get_columns("scan_results")}
    if "bar_as_of" in columns:
        op.drop_column("scan_results", "bar_as_of")
