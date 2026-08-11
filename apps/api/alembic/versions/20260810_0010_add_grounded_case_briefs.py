"""Add immutable grounded case briefs.

Revision ID: 20260810_0010
Revises: 20260810_0009
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0010"
down_revision: str | None = "20260810_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_case_events_type", "case_events", type_="check")
    op.create_check_constraint(
        "ck_case_events_type",
        "case_events",
        "event_type IN ('opened', 'review_started', 'note_added', "
        "'classified', 'outcome_reviewed', 'brief_generated')",
    )
    op.create_table(
        "case_briefs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("rule_assessment_id", sa.String(length=36), nullable=False),
        sa.Column("hybrid_assessment_id", sa.String(length=36), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("output_schema_version", sa.String(length=64), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("provider_model", sa.String(length=120), nullable=False),
        sa.Column("generation_mode", sa.String(length=32), nullable=False),
        sa.Column("input_evidence", sa.JSON(), nullable=False),
        sa.Column("evidence_checksum", sa.String(length=64), nullable=False),
        sa.Column("provider_output", sa.JSON(), nullable=True),
        sa.Column("provider_raw_output", sa.Text(), nullable=True),
        sa.Column("display_output", sa.JSON(), nullable=False),
        sa.Column("validation_report", sa.JSON(), nullable=False),
        sa.Column("generation_milliseconds", sa.Integer(), nullable=False),
        sa.Column("requested_by_id", sa.String(length=36), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("explanation_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "generation_mode IN ('llm', 'deterministic_fallback')",
            name="ck_case_briefs_generation_mode",
        ),
        sa.CheckConstraint(
            "generation_milliseconds >= 0",
            name="ck_case_briefs_generation_milliseconds_nonnegative",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["analyst_cases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["rule_assessment_id"],
            ["transaction_rule_assessments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["hybrid_assessment_id"],
            ["hybrid_risk_assessments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("explanation_checksum"),
        sa.UniqueConstraint("request_fingerprint"),
    )
    op.create_index("ix_case_briefs_case_id", "case_briefs", ["case_id"], unique=False)
    op.create_index(
        "ix_case_briefs_transaction_id",
        "case_briefs",
        ["transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_case_briefs_transaction_id", table_name="case_briefs")
    op.drop_index("ix_case_briefs_case_id", table_name="case_briefs")
    op.drop_table("case_briefs")
    op.drop_constraint("ck_case_events_type", "case_events", type_="check")
    op.create_check_constraint(
        "ck_case_events_type",
        "case_events",
        "event_type IN ('opened', 'review_started', 'note_added', "
        "'classified', 'outcome_reviewed')",
    )
