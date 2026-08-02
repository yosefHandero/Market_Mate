"""Evidence campaigns, live-forward provenance on prediction_snapshots, scan windows.

Additive only. Existing prediction_snapshots rows keep NULL provenance (rendered
as pre-campaign evidence and excluded from campaign metrics). A SQLite trigger
makes the immutable core prediction fields tamper-evident once record_hash is set,
while still allowing outcome fields to be filled in on resolution.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260708_0020"
down_revision = "20260707_0019"
branch_labels = None
depends_on = None


_IMMUTABILITY_TRIGGER = "trg_prediction_snapshots_immutable_core"

# Fires only once record_hash is set (campaign-era rows). Blocks changes to the
# immutable identity/prediction columns while permitting outcome-field updates.
_CREATE_TRIGGER_SQL = f"""
CREATE TRIGGER {_IMMUTABILITY_TRIGGER}
BEFORE UPDATE ON prediction_snapshots
FOR EACH ROW
WHEN OLD.record_hash IS NOT NULL AND (
    NEW.ticker <> OLD.ticker
    OR NEW.signal <> OLD.signal
    OR NEW.entry_price <> OLD.entry_price
    OR NEW.range_low <> OLD.range_low
    OR NEW.range_high <> OLD.range_high
    OR NEW.generated_at <> OLD.generated_at
    OR NEW.record_hash <> OLD.record_hash
    OR IFNULL(NEW.campaign_id, '') <> IFNULL(OLD.campaign_id, '')
    OR IFNULL(NEW.config_fingerprint, '') <> IFNULL(OLD.config_fingerprint, '')
    OR IFNULL(NEW.candidate_rank, -1) <> IFNULL(OLD.candidate_rank, -1)
    OR IFNULL(NEW.selection_status, '') <> IFNULL(OLD.selection_status, '')
    OR IFNULL(NEW.rejection_reason, '') <> IFNULL(OLD.rejection_reason, '')
)
BEGIN
    SELECT RAISE(ABORT, 'prediction_snapshots core fields are immutable');
END;
"""


def _columns(inspector: sa.engine.reflection.Inspector, table: str) -> set[str]:
    if table not in set(inspector.get_table_names()):
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


_SNAPSHOT_COLUMNS = (
    ("campaign_id", sa.String(length=64)),
    ("strategy_version", sa.String(length=32)),
    ("code_commit", sa.String(length=64)),
    ("config_fingerprint", sa.String(length=64)),
    ("feature_version", sa.String(length=32)),
    ("provider_source", sa.String(length=32)),
    ("data_cutoff_at", sa.DateTime()),
    ("expected_friction_bps", sa.Float()),
    ("candidate_rank", sa.Integer()),
    ("selection_status", sa.String(length=32)),
    ("rejection_reason", sa.String(length=64)),
    ("resolve_due_at", sa.DateTime()),
    ("resolved_late", sa.Boolean()),
    ("record_hash", sa.String(length=64)),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "evidence_campaigns" not in tables:
        op.create_table(
            "evidence_campaigns",
            sa.Column("campaign_id", sa.String(length=64), primary_key=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
            sa.Column("strategy_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("strategy_version", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("feature_version", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("config_fingerprint", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("code_commit", sa.String(length=64), nullable=True),
            sa.Column("close_reason", sa.String(length=32), nullable=True),
            sa.Column("notes_json", sa.Text(), nullable=True),
        )
        op.create_index("ix_evidence_campaigns_status", "evidence_campaigns", ["status"])
        op.create_index(
            "ix_evidence_campaigns_config_fingerprint",
            "evidence_campaigns",
            ["config_fingerprint"],
        )

    if "scan_windows" not in tables:
        op.create_table(
            "scan_windows",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("window_name", sa.String(length=48), nullable=False),
            sa.Column("expected_start", sa.DateTime(), nullable=False),
            sa.Column("expected_end", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("scan_run_id", sa.String(length=64), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "window_name", "expected_start", name="uq_scan_windows_name_start"
            ),
        )
        op.create_index("ix_scan_windows_window_name", "scan_windows", ["window_name"])
        op.create_index("ix_scan_windows_status", "scan_windows", ["status"])

    snapshot_cols = _columns(inspector, "prediction_snapshots")
    if snapshot_cols:
        for name, coltype in _SNAPSHOT_COLUMNS:
            if name not in snapshot_cols:
                op.add_column(
                    "prediction_snapshots", sa.Column(name, coltype, nullable=True)
                )

    if bind.dialect.name == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_IMMUTABILITY_TRIGGER}")
        op.execute(_CREATE_TRIGGER_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if bind.dialect.name == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_IMMUTABILITY_TRIGGER}")

    snapshot_cols = _columns(inspector, "prediction_snapshots")
    for name, _ in reversed(_SNAPSHOT_COLUMNS):
        if name in snapshot_cols:
            op.drop_column("prediction_snapshots", name)

    if "scan_windows" in tables:
        op.drop_table("scan_windows")
    if "evidence_campaigns" in tables:
        op.drop_table("evidence_campaigns")
