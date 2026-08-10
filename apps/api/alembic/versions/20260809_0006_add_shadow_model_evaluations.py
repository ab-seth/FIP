"""Add immutable shadow-model evaluation reports.

Revision ID: 20260809_0006
Revises: 20260809_0005
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_0006"
down_revision: str | None = "20260809_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shadow_model_evaluation_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_id", sa.String(length=36), nullable=False),
        sa.Column("report_schema_version", sa.String(length=64), nullable=False),
        sa.Column("baseline_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluation_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluation_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_prediction_count", sa.Integer(), nullable=False),
        sa.Column("evaluation_prediction_count", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("input_lineage_checksum", sa.String(length=64), nullable=False),
        sa.Column("report_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "baseline_prediction_count >= 20",
            name="ck_shadow_evaluations_baseline_count",
        ),
        sa.CheckConstraint(
            "baseline_window_start < baseline_window_end",
            name="ck_shadow_evaluations_baseline_window",
        ),
        sa.CheckConstraint(
            "evaluation_prediction_count >= 20",
            name="ck_shadow_evaluations_evaluation_count",
        ),
        sa.CheckConstraint(
            "evaluation_window_start < evaluation_window_end",
            name="ck_shadow_evaluations_evaluation_window",
        ),
        sa.CheckConstraint(
            "baseline_window_end <= evaluation_window_start",
            name="ck_shadow_evaluations_nonoverlapping_windows",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["registered_models.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_checksum"),
        sa.UniqueConstraint(
            "model_id",
            "baseline_window_start",
            "baseline_window_end",
            "evaluation_window_start",
            "evaluation_window_end",
            name="uq_shadow_evaluation_model_windows",
        ),
    )
    op.create_index(
        "ix_shadow_evaluations_model_id",
        "shadow_model_evaluation_reports",
        ["model_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shadow_evaluations_model_id",
        table_name="shadow_model_evaluation_reports",
    )
    op.drop_table("shadow_model_evaluation_reports")
