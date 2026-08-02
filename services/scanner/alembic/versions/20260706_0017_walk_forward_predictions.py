"""Add walk_forward_runs and walk_forward_predictions tables for the proof engine."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260706_0017"
down_revision = "20260706_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "walk_forward_runs" not in existing:
        op.create_table(
            "walk_forward_runs",
            sa.Column("run_id", sa.String(length=64), primary_key=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="complete"),
            sa.Column("params_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("window_start", sa.DateTime(), nullable=True),
            sa.Column("window_end", sa.DateTime(), nullable=True),
            sa.Column("holdout_start", sa.DateTime(), nullable=True),
            sa.Column("symbol_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("prediction_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metrics_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("verdict_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("coverage_json", sa.Text(), nullable=False, server_default="{}"),
        )
        op.create_index("ix_walk_forward_runs_created_at", "walk_forward_runs", ["created_at"])

    if "walk_forward_predictions" not in existing:
        op.create_table(
            "walk_forward_predictions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(length=64), nullable=False),
            sa.Column("as_of", sa.DateTime(), nullable=False),
            sa.Column("asset_type", sa.String(length=16), nullable=False, server_default="stock"),
            sa.Column("ticker", sa.String(length=24), nullable=False),
            sa.Column("selection_rank", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sample_source", sa.String(length=32), nullable=False, server_default="historical"),
            sa.Column("pattern_name", sa.String(length=64), nullable=False, server_default="range_neutral"),
            sa.Column("decision_signal", sa.String(length=16), nullable=False, server_default="BUY"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("upside_probability_pct", sa.Float(), nullable=True),
            sa.Column("historical_hit_rate_pct", sa.Float(), nullable=True),
            sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("entry_price", sa.Float(), nullable=False, server_default="0"),
            sa.Column("projected_range_low", sa.Float(), nullable=True),
            sa.Column("projected_range_high", sa.Float(), nullable=True),
            sa.Column("estimated_exit_price", sa.Float(), nullable=True),
            sa.Column("invalidation_level", sa.Float(), nullable=True),
            sa.Column("stop_growing_signal", sa.Text(), nullable=True),
            sa.Column("horizon", sa.String(length=8), nullable=False, server_default="1w"),
            sa.Column("forward_days", sa.Integer(), nullable=False, server_default="7"),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
            sa.Column("resolve_due_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("price_after_1w", sa.Float(), nullable=True),
            sa.Column("return_after_1w", sa.Float(), nullable=True),
            sa.Column("in_range", sa.Boolean(), nullable=True),
            sa.Column("accuracy_outcome", sa.String(length=16), nullable=True),
            sa.Column("exit_window_status", sa.String(length=16), nullable=True),
            sa.Column("exit_hit", sa.Boolean(), nullable=True),
            sa.Column("invalidation_hit", sa.Boolean(), nullable=True),
            sa.Column("protected_return_pct", sa.Float(), nullable=True),
            sa.Column("hold_return_pct", sa.Float(), nullable=True),
            sa.Column("exit_window_helped", sa.Boolean(), nullable=True),
            sa.Column("evaluated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_walk_forward_predictions_run_id", "walk_forward_predictions", ["run_id"])
        op.create_index("ix_walk_forward_predictions_as_of", "walk_forward_predictions", ["as_of"])
        op.create_index("ix_walk_forward_predictions_asset_type", "walk_forward_predictions", ["asset_type"])
        op.create_index("ix_walk_forward_predictions_ticker", "walk_forward_predictions", ["ticker"])
        op.create_index("ix_walk_forward_predictions_sample_source", "walk_forward_predictions", ["sample_source"])
        op.create_index("ix_walk_forward_predictions_status", "walk_forward_predictions", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    if "walk_forward_predictions" in existing:
        op.drop_table("walk_forward_predictions")
    if "walk_forward_runs" in existing:
        op.drop_table("walk_forward_runs")
