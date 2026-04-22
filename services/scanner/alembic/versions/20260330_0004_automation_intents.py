"""Add automation intents table for backend paper loop.

Revision ID: 20260330_0004
Revises: 20260326_0003
Create Date: 2026-03-30 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260330_0004"
down_revision = "20260326_0003"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("automation_intents"):
        return

    op.create_table(
        "automation_intents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False, server_default="stock"),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("horizon", sa.String(length=16), nullable=True),
        sa.Column("window_start", sa.DateTime(), nullable=True),
        sa.Column("window_end", sa.DateTime(), nullable=True),
        sa.Column("intent_key", sa.String(length=255), nullable=False, unique=True),
        sa.Column("intent_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("execution_audit_id", sa.Integer(), nullable=True),
        sa.Column("decision_payload_json", sa.Text(), nullable=True),
        sa.Column("request_payload_json", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_count_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_count_avoided", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_by", sa.String(length=64), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_automation_intents_created_at", "automation_intents", ["created_at"])
    op.create_index("ix_automation_intents_updated_at", "automation_intents", ["updated_at"])
    op.create_index("ix_automation_intents_run_id", "automation_intents", ["run_id"])
    op.create_index("ix_automation_intents_symbol", "automation_intents", ["symbol"])
    op.create_index("ix_automation_intents_asset_type", "automation_intents", ["asset_type"])
    op.create_index("ix_automation_intents_side", "automation_intents", ["side"])
    op.create_index("ix_automation_intents_strategy_version", "automation_intents", ["strategy_version"])
    op.create_index("ix_automation_intents_window_start", "automation_intents", ["window_start"])
    op.create_index("ix_automation_intents_window_end", "automation_intents", ["window_end"])
    op.create_index("ix_automation_intents_intent_key", "automation_intents", ["intent_key"], unique=True)
    op.create_index("ix_automation_intents_intent_hash", "automation_intents", ["intent_hash"])
    op.create_index("ix_automation_intents_status", "automation_intents", ["status"])
    op.create_index("ix_automation_intents_idempotency_key", "automation_intents", ["idempotency_key"])
    op.create_index("ix_automation_intents_execution_audit_id", "automation_intents", ["execution_audit_id"])
    op.create_index("ix_automation_intents_last_attempt_at", "automation_intents", ["last_attempt_at"])
    op.create_index("ix_automation_intents_next_retry_at", "automation_intents", ["next_retry_at"])
    op.create_index("ix_automation_intents_claimed_by", "automation_intents", ["claimed_by"])
    op.create_index("ix_automation_intents_claim_expires_at", "automation_intents", ["claim_expires_at"])
    op.create_index("ix_automation_intents_cooldown_until", "automation_intents", ["cooldown_until"])


def downgrade() -> None:
    pass
