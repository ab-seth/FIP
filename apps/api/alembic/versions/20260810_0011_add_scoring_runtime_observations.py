"""Add tamper-evident scoring runtime observations.

Revision ID: 20260810_0011
Revises: 20260810_0010
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0011"
down_revision: str | None = "20260810_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scoring_runtime_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("feature_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("rule_assessment_id", sa.String(length=36), nullable=False),
        sa.Column("observation_schema_version", sa.String(length=64), nullable=False),
        sa.Column("runtime_milliseconds", sa.Integer(), nullable=False),
        sa.Column("rule_assessment_checksum", sa.String(length=64), nullable=False),
        sa.Column("observation_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "runtime_milliseconds >= 0",
            name="ck_scoring_runtime_observations_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["feature_snapshot_id"],
            ["transaction_feature_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_assessment_id"],
            ["transaction_rule_assessments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observation_checksum"),
        sa.UniqueConstraint(
            "rule_assessment_id",
            name="uq_scoring_runtime_observation_rule_assessment",
        ),
    )
    op.create_index(
        "ix_scoring_runtime_observations_created_at",
        "scoring_runtime_observations",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_scoring_runtime_observations_transaction_id",
        "scoring_runtime_observations",
        ["transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scoring_runtime_observations_transaction_id",
        table_name="scoring_runtime_observations",
    )
    op.drop_index(
        "ix_scoring_runtime_observations_created_at",
        table_name="scoring_runtime_observations",
    )
    op.drop_table("scoring_runtime_observations")
