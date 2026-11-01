"""Freeze newly agreed paper terms; leave historical contracts unknown."""

from alembic import op
import sqlalchemy as sa


revision = "20261011_0025"
down_revision = "20260928_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        ("source_run_id", sa.String(64)),
        ("policy_id", sa.String(64)),
        ("policy_version", sa.String(32)),
        ("decision_fingerprint", sa.String(64)),
        ("holding_horizon", sa.String(16)),
        ("holding_duration_seconds", sa.Integer()),
        ("exit_method", sa.String(32)),
        ("exit_due_at", sa.DateTime()),
    )
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("paper_positions")}
    for name, column_type in columns:
        if name not in existing:
            op.add_column("paper_positions", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("paper_positions") as batch:
        for name in (
            "source_run_id", "policy_id", "policy_version", "decision_fingerprint",
            "holding_horizon", "holding_duration_seconds", "exit_method", "exit_due_at",
        ):
            batch.drop_column(name)
