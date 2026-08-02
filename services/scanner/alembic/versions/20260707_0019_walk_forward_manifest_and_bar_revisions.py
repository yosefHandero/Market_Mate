"""Walk-forward run manifest, per-prediction friction, and daily-bar PIT revisions.

Additive only. Existing rows keep working with NULL/default values:
- daily_bar_history gains adjustment_policy / revision_count / revised_at
- walk_forward_predictions gains expected_friction_bps
- walk_forward_runs gains config_fingerprint / code_commit / engine_version /
  universe_json / validation_start / data_quality_json
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260707_0019"
down_revision = "20260706_0018"
branch_labels = None
depends_on = None


def _columns(inspector: sa.engine.reflection.Inspector, table: str) -> set[str]:
    if table not in set(inspector.get_table_names()):
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    bar_cols = _columns(inspector, "daily_bar_history")
    if bar_cols:
        if "adjustment_policy" not in bar_cols:
            op.add_column(
                "daily_bar_history",
                sa.Column(
                    "adjustment_policy",
                    sa.String(length=16),
                    nullable=False,
                    server_default="raw",
                ),
            )
        if "revision_count" not in bar_cols:
            op.add_column(
                "daily_bar_history",
                sa.Column(
                    "revision_count",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                ),
            )
        if "revised_at" not in bar_cols:
            op.add_column(
                "daily_bar_history",
                sa.Column("revised_at", sa.DateTime(), nullable=True),
            )

    pred_cols = _columns(inspector, "walk_forward_predictions")
    if pred_cols and "expected_friction_bps" not in pred_cols:
        op.add_column(
            "walk_forward_predictions",
            sa.Column("expected_friction_bps", sa.Float(), nullable=True),
        )

    run_cols = _columns(inspector, "walk_forward_runs")
    if run_cols:
        if "validation_start" not in run_cols:
            op.add_column(
                "walk_forward_runs",
                sa.Column("validation_start", sa.DateTime(), nullable=True),
            )
        if "config_fingerprint" not in run_cols:
            op.add_column(
                "walk_forward_runs",
                sa.Column("config_fingerprint", sa.String(length=64), nullable=True),
            )
            op.create_index(
                "ix_walk_forward_runs_config_fingerprint",
                "walk_forward_runs",
                ["config_fingerprint"],
            )
        if "code_commit" not in run_cols:
            op.add_column(
                "walk_forward_runs",
                sa.Column("code_commit", sa.String(length=64), nullable=True),
            )
        if "engine_version" not in run_cols:
            op.add_column(
                "walk_forward_runs",
                sa.Column("engine_version", sa.String(length=32), nullable=True),
            )
        if "universe_json" not in run_cols:
            op.add_column(
                "walk_forward_runs",
                sa.Column(
                    "universe_json", sa.Text(), nullable=False, server_default="[]"
                ),
            )
        if "data_quality_json" not in run_cols:
            op.add_column(
                "walk_forward_runs",
                sa.Column(
                    "data_quality_json", sa.Text(), nullable=False, server_default="{}"
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    run_cols = _columns(inspector, "walk_forward_runs")
    if run_cols:
        if "config_fingerprint" in run_cols:
            try:
                op.drop_index(
                    "ix_walk_forward_runs_config_fingerprint",
                    table_name="walk_forward_runs",
                )
            except Exception:
                pass
        for name in (
            "data_quality_json",
            "universe_json",
            "engine_version",
            "code_commit",
            "config_fingerprint",
            "validation_start",
        ):
            if name in run_cols:
                op.drop_column("walk_forward_runs", name)

    pred_cols = _columns(inspector, "walk_forward_predictions")
    if pred_cols and "expected_friction_bps" in pred_cols:
        op.drop_column("walk_forward_predictions", "expected_friction_bps")

    bar_cols = _columns(inspector, "daily_bar_history")
    if bar_cols:
        for name in ("revised_at", "revision_count", "adjustment_policy"):
            if name in bar_cols:
                op.drop_column("daily_bar_history", name)
