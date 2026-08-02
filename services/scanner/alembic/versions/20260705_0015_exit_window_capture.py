"""Add exit-window capture and resolution columns to prediction_snapshots."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260705_0015"
down_revision = "20260629_0014"
branch_labels = None
depends_on = None

_EXIT_WINDOW_CAPTURE_COLUMNS = (
    ("estimated_exit_price", sa.Float()),
    ("invalidation_level", sa.Float()),
    ("projected_range_high", sa.Float()),
)

_EXIT_WINDOW_RESOLUTION_COLUMNS = (
    ("exit_window_status", sa.String(length=16)),
    ("exit_hit", sa.Boolean()),
    ("invalidation_hit", sa.Boolean()),
    ("protected_return_pct", sa.Float()),
    ("hold_return_pct", sa.Float()),
    ("exit_window_helped", sa.Boolean()),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "prediction_snapshots" not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns("prediction_snapshots")}
    for name, column_type in _EXIT_WINDOW_CAPTURE_COLUMNS:
        if name not in existing:
            op.add_column("prediction_snapshots", sa.Column(name, column_type, nullable=True))
    for name, column_type in _EXIT_WINDOW_RESOLUTION_COLUMNS:
        if name not in existing:
            op.add_column("prediction_snapshots", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "prediction_snapshots" not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns("prediction_snapshots")}
    for name, _ in reversed(_EXIT_WINDOW_RESOLUTION_COLUMNS + _EXIT_WINDOW_CAPTURE_COLUMNS):
        if name in existing:
            op.drop_column("prediction_snapshots", name)
