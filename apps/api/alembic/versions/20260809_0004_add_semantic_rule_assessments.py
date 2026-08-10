"""Add semantic feature snapshots and deterministic rule assessments.

Revision ID: 20260809_0004
Revises: 20260809_0003
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_0004"
down_revision: str | None = "20260809_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transaction_feature_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("feature_set_version", sa.String(length=64), nullable=False),
        sa.Column("history_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("history_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("history_checksum", sa.String(length=64), nullable=False),
        sa.Column("feature_values", sa.JSON(), nullable=False),
        sa.Column("snapshot_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_checksum"),
        sa.UniqueConstraint(
            "transaction_id",
            "feature_set_version",
            name="uq_transaction_feature_snapshot_version",
        ),
    )
    op.create_index(
        "ix_feature_snapshots_transaction_id",
        "transaction_feature_snapshots",
        ["transaction_id"],
        unique=False,
    )
    op.create_table(
        "transaction_rule_assessments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("feature_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("ruleset_version", sa.String(length=64), nullable=False),
        sa.Column("risk_band_version", sa.String(length=64), nullable=False),
        sa.Column("rule_score", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("triggered_rules", sa.JSON(), nullable=False),
        sa.Column("assessment_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="ck_transaction_rule_assessments_risk_level",
        ),
        sa.CheckConstraint(
            "rule_score >= 0 AND rule_score <= 100",
            name="ck_transaction_rule_assessments_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["feature_snapshot_id"],
            ["transaction_feature_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_checksum"),
        sa.UniqueConstraint(
            "feature_snapshot_id",
            "ruleset_version",
            "risk_band_version",
            name="uq_transaction_rule_assessment_versions",
        ),
    )
    op.create_index(
        "ix_rule_assessments_transaction_id",
        "transaction_rule_assessments",
        ["transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_rule_assessments_transaction_id", table_name="transaction_rule_assessments")
    op.drop_table("transaction_rule_assessments")
    op.drop_index("ix_feature_snapshots_transaction_id", table_name="transaction_feature_snapshots")
    op.drop_table("transaction_feature_snapshots")
