"""Add investigation cases and governed outcome labels.

Revision ID: 20260809_0007
Revises: 20260809_0006
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_0007"
down_revision: str | None = "20260809_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analyst_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_id", sa.String(length=16), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("feature_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("rule_assessment_id", sa.String(length=36), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("opening_reason", sa.String(length=500), nullable=False),
        sa.Column("opening_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "priority IN ('standard', 'urgent')",
            name="ck_analyst_cases_priority",
        ),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("display_id"),
        sa.UniqueConstraint("opening_checksum"),
        sa.UniqueConstraint("transaction_id", name="uq_analyst_cases_transaction"),
    )
    op.create_index("ix_analyst_cases_created_at", "analyst_cases", ["created_at"], unique=False)

    op.create_table(
        "case_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("actor_username", sa.String(length=120), nullable=False),
        sa.Column("previous_event_checksum", sa.String(length=64), nullable=True),
        sa.Column("event_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('opened', 'review_started', 'note_added', "
            "'classified', 'outcome_reviewed')",
            name="ck_case_events_type",
        ),
        sa.CheckConstraint("sequence_number > 0", name="ck_case_events_sequence_positive"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["case_id"], ["analyst_cases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_checksum"),
        sa.UniqueConstraint("case_id", "sequence_number", name="uq_case_event_sequence"),
    )
    op.create_index("ix_case_events_case_id", "case_events", ["case_id"], unique=False)

    op.create_table(
        "case_outcomes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.String(length=2000), nullable=False),
        sa.Column("determined_by_id", sa.String(length=36), nullable=False),
        sa.Column("outcome_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "classification IN ('confirmed_fraud', 'legitimate', 'inconclusive')",
            name="ck_case_outcomes_classification",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["analyst_cases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["determined_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", name="uq_case_outcomes_case"),
        sa.UniqueConstraint("outcome_checksum"),
    )
    op.create_index("ix_case_outcomes_case_id", "case_outcomes", ["case_id"], unique=False)

    op.create_table(
        "case_outcome_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("outcome_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("reviewed_by_id", sa.String(length=36), nullable=False),
        sa.Column("review_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('approved', 'rejected')",
            name="ck_case_outcome_reviews_status",
        ),
        sa.ForeignKeyConstraint(["outcome_id"], ["case_outcomes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outcome_id", name="uq_case_outcome_reviews_outcome"),
        sa.UniqueConstraint("review_checksum"),
    )
    op.create_index(
        "ix_case_outcome_reviews_outcome_id",
        "case_outcome_reviews",
        ["outcome_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_case_outcome_reviews_outcome_id", table_name="case_outcome_reviews")
    op.drop_table("case_outcome_reviews")
    op.drop_index("ix_case_outcomes_case_id", table_name="case_outcomes")
    op.drop_table("case_outcomes")
    op.drop_index("ix_case_events_case_id", table_name="case_events")
    op.drop_table("case_events")
    op.drop_index("ix_analyst_cases_created_at", table_name="analyst_cases")
    op.drop_table("analyst_cases")
