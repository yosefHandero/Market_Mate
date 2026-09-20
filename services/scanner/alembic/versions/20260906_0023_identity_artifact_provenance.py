"""Add decision and learned-artifact provenance fields.

Additive only. Existing evidence remains nullable/ambiguous and must be
excluded from identity-specific promotion unless compatibility is proven.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260906_0023"
down_revision = "20260901_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("evidence_campaigns") as batch:
        batch.add_column(sa.Column("effective_policy_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("effective_policy_version", sa.String(32), nullable=True))
        batch.add_column(sa.Column("effective_decision_fingerprint", sa.String(64), nullable=True))
        batch.add_column(sa.Column("learned_artifacts_fingerprint", sa.String(64), nullable=True))
        batch.add_column(sa.Column("learned_artifacts_json", sa.Text(), nullable=True))
    op.create_index(
        "ix_evidence_campaigns_effective_policy_id",
        "evidence_campaigns",
        ["effective_policy_id"],
    )
    op.create_index(
        "ix_evidence_campaigns_effective_decision_fingerprint",
        "evidence_campaigns",
        ["effective_decision_fingerprint"],
    )
    op.create_index(
        "ix_evidence_campaigns_learned_artifacts_fingerprint",
        "evidence_campaigns",
        ["learned_artifacts_fingerprint"],
    )

    with op.batch_alter_table("prediction_snapshots") as batch:
        batch.add_column(sa.Column("learned_artifacts_fingerprint", sa.String(64), nullable=True))
    op.create_index(
        "ix_prediction_snapshots_learned_artifacts_fingerprint",
        "prediction_snapshots",
        ["learned_artifacts_fingerprint"],
    )

    with op.batch_alter_table("walk_forward_runs") as batch:
        batch.add_column(sa.Column("policy_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("policy_version", sa.String(32), nullable=True))
        batch.add_column(sa.Column("decision_fingerprint", sa.String(64), nullable=True))
        batch.add_column(sa.Column("learned_artifacts_fingerprint", sa.String(64), nullable=True))
        batch.add_column(sa.Column("learned_artifacts_json", sa.Text(), nullable=True))
    op.create_index("ix_walk_forward_runs_policy_id", "walk_forward_runs", ["policy_id"])
    op.create_index(
        "ix_walk_forward_runs_decision_fingerprint",
        "walk_forward_runs",
        ["decision_fingerprint"],
    )
    op.create_index(
        "ix_walk_forward_runs_learned_artifacts_fingerprint",
        "walk_forward_runs",
        ["learned_artifacts_fingerprint"],
    )

    with op.batch_alter_table("walk_forward_predictions") as batch:
        batch.add_column(sa.Column("policy_version", sa.String(32), nullable=True))
        batch.add_column(sa.Column("decision_fingerprint", sa.String(64), nullable=True))
        batch.add_column(sa.Column("learned_artifacts_fingerprint", sa.String(64), nullable=True))
    op.create_index(
        "ix_walk_forward_predictions_decision_fingerprint",
        "walk_forward_predictions",
        ["decision_fingerprint"],
    )
    op.create_index(
        "ix_walk_forward_predictions_learned_artifacts_fingerprint",
        "walk_forward_predictions",
        ["learned_artifacts_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_walk_forward_predictions_learned_artifacts_fingerprint",
        table_name="walk_forward_predictions",
    )
    op.drop_index(
        "ix_walk_forward_predictions_decision_fingerprint",
        table_name="walk_forward_predictions",
    )
    with op.batch_alter_table("walk_forward_predictions") as batch:
        batch.drop_column("learned_artifacts_fingerprint")
        batch.drop_column("decision_fingerprint")
        batch.drop_column("policy_version")

    op.drop_index(
        "ix_walk_forward_runs_learned_artifacts_fingerprint",
        table_name="walk_forward_runs",
    )
    op.drop_index("ix_walk_forward_runs_decision_fingerprint", table_name="walk_forward_runs")
    op.drop_index("ix_walk_forward_runs_policy_id", table_name="walk_forward_runs")
    with op.batch_alter_table("walk_forward_runs") as batch:
        batch.drop_column("learned_artifacts_json")
        batch.drop_column("learned_artifacts_fingerprint")
        batch.drop_column("decision_fingerprint")
        batch.drop_column("policy_version")
        batch.drop_column("policy_id")

    op.drop_index(
        "ix_prediction_snapshots_learned_artifacts_fingerprint",
        table_name="prediction_snapshots",
    )
    with op.batch_alter_table("prediction_snapshots") as batch:
        batch.drop_column("learned_artifacts_fingerprint")

    op.drop_index(
        "ix_evidence_campaigns_learned_artifacts_fingerprint",
        table_name="evidence_campaigns",
    )
    op.drop_index(
        "ix_evidence_campaigns_effective_decision_fingerprint",
        table_name="evidence_campaigns",
    )
    op.drop_index("ix_evidence_campaigns_effective_policy_id", table_name="evidence_campaigns")
    with op.batch_alter_table("evidence_campaigns") as batch:
        batch.drop_column("learned_artifacts_json")
        batch.drop_column("learned_artifacts_fingerprint")
        batch.drop_column("effective_decision_fingerprint")
        batch.drop_column("effective_policy_version")
        batch.drop_column("effective_policy_id")
