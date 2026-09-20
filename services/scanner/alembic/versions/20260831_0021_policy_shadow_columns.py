"""Add policy identity and decision_role to prediction_snapshots.

Additive only. Existing rows stay NULL (treated as production hybrid_legacy).
Challenger shadow decisions are persisted with decision_role='shadow' and
never mix into production readiness surfaces.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260831_0021"
down_revision = "20260708_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("prediction_snapshots") as batch:
        batch.add_column(sa.Column("policy_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("policy_version", sa.String(32), nullable=True))
        batch.add_column(sa.Column("decision_role", sa.String(16), nullable=True))
        batch.add_column(sa.Column("decision_fingerprint", sa.String(64), nullable=True))
    op.create_index(
        "ix_prediction_snapshots_policy_id",
        "prediction_snapshots",
        ["policy_id"],
    )
    op.create_index(
        "ix_prediction_snapshots_decision_role",
        "prediction_snapshots",
        ["decision_role"],
    )


def downgrade() -> None:
    op.drop_index("ix_prediction_snapshots_decision_role", table_name="prediction_snapshots")
    op.drop_index("ix_prediction_snapshots_policy_id", table_name="prediction_snapshots")
    with op.batch_alter_table("prediction_snapshots") as batch:
        batch.drop_column("decision_fingerprint")
        batch.drop_column("decision_role")
        batch.drop_column("policy_version")
        batch.drop_column("policy_id")
