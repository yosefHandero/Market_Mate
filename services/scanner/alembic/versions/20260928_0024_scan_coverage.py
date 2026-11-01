"""Persist scan-time coverage; historical coverage remains unknown."""

from alembic import op
import sqlalchemy as sa


revision = "20260928_0024"
down_revision = "20260906_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scan_runs", sa.Column("coverage_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("scan_runs") as batch:
        batch.drop_column("coverage_json")
