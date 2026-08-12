"""Add durable operational candidate training runs.

Revision ID: 20260811_0012
Revises: 20260810_0011
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260811_0012"
down_revision: str | None = "20260810_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operational_training_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_id", sa.String(length=24), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_version", sa.String(length=64), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("maximum_false_positive_rate", sa.Numeric(8, 6), nullable=False),
        sa.Column("request_reason", sa.String(length=500), nullable=False),
        sa.Column("pipeline_version", sa.String(length=64), nullable=False),
        sa.Column("dataset_checksum", sa.String(length=64), nullable=False),
        sa.Column("configuration_checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("bundle_key", sa.String(length=120), nullable=True),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("evidence_checksum", sa.String(length=64), nullable=True),
        sa.Column("manifest_checksum", sa.String(length=64), nullable=True),
        sa.Column("bundle_checksum", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_operational_training_runs_status",
        ),
        sa.CheckConstraint(
            "seed >= 0",
            name="ck_operational_training_runs_seed_nonnegative",
        ),
        sa.CheckConstraint(
            "maximum_false_positive_rate > 0 AND maximum_false_positive_rate < 1",
            name="ck_operational_training_runs_fpr_range",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_operational_training_runs_attempt_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["operational_dataset_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_version", name="uq_operational_training_runs_version"),
        sa.UniqueConstraint(
            "configuration_checksum",
            name="uq_operational_training_runs_configuration",
        ),
        sa.UniqueConstraint("display_id"),
    )
    op.create_index(
        "ix_operational_training_runs_status_created",
        "operational_training_runs",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "operational_training_run_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("training_run_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=False),
        sa.Column("actor_username", sa.String(length=120), nullable=False),
        sa.Column("previous_event_checksum", sa.String(length=64), nullable=True),
        sa.Column("event_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_operational_training_run_events_from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_operational_training_run_events_to_status",
        ),
        sa.CheckConstraint(
            "sequence_number > 0",
            name="ck_operational_training_run_events_sequence_positive",
        ),
        sa.ForeignKeyConstraint(
            ["training_run_id"],
            ["operational_training_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_checksum"),
        sa.UniqueConstraint(
            "training_run_id",
            "sequence_number",
            name="uq_operational_training_run_event_sequence",
        ),
    )
    op.create_index(
        "ix_operational_training_run_events_run",
        "operational_training_run_events",
        ["training_run_id", "sequence_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_operational_training_run_events_run",
        table_name="operational_training_run_events",
    )
    op.drop_table("operational_training_run_events")
    op.drop_index(
        "ix_operational_training_runs_status_created",
        table_name="operational_training_runs",
    )
    op.drop_table("operational_training_runs")
