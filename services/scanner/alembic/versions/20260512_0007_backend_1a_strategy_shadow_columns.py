"""Add Backend 1A strategy and shadow columns.

Revision ID: 20260512_0007
Revises: 20260404_0006
Create Date: 2026-05-12 00:00:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text


revision = "20260512_0007"
down_revision = "20260404_0006"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _existing_columns(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _add_column_if_missing(table_name: str, column_name: str, column_sql: str) -> None:
    if column_name in _existing_columns(table_name):
        return
    op.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))


def _drop_columns_if_present(table_name: str, column_names: tuple[str, ...]) -> None:
    columns_to_drop = [
        column_name
        for column_name in column_names
        if column_name in _existing_columns(table_name)
    ]
    if not columns_to_drop:
        return

    # Alembic batch mode safely handles SQLite table rewrites when native DROP COLUMN is limited.
    with op.batch_alter_table(table_name) as batch_op:
        for column_name in columns_to_drop:
            batch_op.drop_column(column_name)


def upgrade() -> None:
    _add_column_if_missing("scan_runs", "shadow_enabled", "BOOLEAN DEFAULT 0")
    _add_column_if_missing("scan_runs", "strategy_variant", "VARCHAR(32) DEFAULT 'layered-v4'")

    _add_column_if_missing("scan_results", "comparison_json", "TEXT")
    _add_column_if_missing("scan_results", "layer_details_json", "TEXT")
    _add_column_if_missing("scan_results", "strategy_variant", "VARCHAR(32) DEFAULT 'layered-v4'")

    _add_column_if_missing("signal_outcomes", "strategy_variant", "VARCHAR(32) DEFAULT 'layered-v4'")


def downgrade() -> None:
    _drop_columns_if_present("scan_runs", ("shadow_enabled", "strategy_variant"))
    _drop_columns_if_present(
        "scan_results",
        ("comparison_json", "layer_details_json", "strategy_variant"),
    )
    _drop_columns_if_present("signal_outcomes", ("strategy_variant",))
