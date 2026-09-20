"""Add policy_id to walk_forward_predictions.

Additive only. Walk-forward runs evaluate replayable DecisionPolicy
implementations; stamping each stored prediction with the policy that
produced it lets the ruler scope WF evidence per policy. Existing rows stay
NULL (pre-policy weekly path).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260901_0022"
down_revision = "20260831_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("walk_forward_predictions") as batch:
        batch.add_column(sa.Column("policy_id", sa.String(64), nullable=True))
    op.create_index(
        "ix_walk_forward_predictions_policy_id",
        "walk_forward_predictions",
        ["policy_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_walk_forward_predictions_policy_id",
        table_name="walk_forward_predictions",
    )
    with op.batch_alter_table("walk_forward_predictions") as batch:
        batch.drop_column("policy_id")
