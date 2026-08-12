"""Add deterministic synthetic system benchmark evidence.

Revision ID: 20260811_0013
Revises: 20260811_0012
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260811_0013"
down_revision: str | None = "20260811_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_ingestion_batches_source_type",
        "ingestion_batches",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ingestion_batches_source_type",
        "ingestion_batches",
        "source_type IN ('csv', 'api', 'synthetic')",
    )
    op.create_table(
        "synthetic_benchmark_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_id", sa.String(length=24), nullable=False),
        sa.Column("requested_by_id", sa.String(length=36), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("request_reason", sa.String(length=500), nullable=False),
        sa.Column("generator_version", sa.String(length=64), nullable=False),
        sa.Column("configuration_checksum", sa.String(length=64), nullable=False),
        sa.Column("dataset_checksum", sa.String(length=64), nullable=False),
        sa.Column("profile_distribution", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingestion_batch_id", sa.String(length=36), nullable=True),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("report_checksum", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_synthetic_benchmark_runs_status",
        ),
        sa.CheckConstraint(
            "transaction_count >= 100 AND transaction_count <= 10000",
            name="ck_synthetic_benchmark_runs_count",
        ),
        sa.CheckConstraint("seed >= 0", name="ck_synthetic_benchmark_runs_seed"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_synthetic_benchmark_runs_attempts"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["ingestion_batch_id"], ["ingestion_batches.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("display_id"),
        sa.UniqueConstraint(
            "configuration_checksum", name="uq_synthetic_benchmark_runs_configuration"
        ),
        sa.UniqueConstraint("ingestion_batch_id", name="uq_synthetic_benchmark_runs_batch"),
    )
    op.create_index(
        "ix_synthetic_benchmark_runs_status_created",
        "synthetic_benchmark_runs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_table(
        "synthetic_benchmark_run_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("benchmark_run_id", sa.String(length=36), nullable=False),
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
            name="ck_synthetic_benchmark_events_from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_synthetic_benchmark_events_to_status",
        ),
        sa.CheckConstraint("sequence_number > 0", name="ck_synthetic_benchmark_events_sequence"),
        sa.ForeignKeyConstraint(
            ["benchmark_run_id"], ["synthetic_benchmark_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_checksum"),
        sa.UniqueConstraint(
            "benchmark_run_id",
            "sequence_number",
            name="uq_synthetic_benchmark_event_sequence",
        ),
    )
    op.create_index(
        "ix_synthetic_benchmark_events_run",
        "synthetic_benchmark_run_events",
        ["benchmark_run_id", "sequence_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_synthetic_benchmark_events_run",
        table_name="synthetic_benchmark_run_events",
    )
    op.drop_table("synthetic_benchmark_run_events")
    op.drop_index(
        "ix_synthetic_benchmark_runs_status_created",
        table_name="synthetic_benchmark_runs",
    )
    op.drop_table("synthetic_benchmark_runs")
    op.drop_constraint(
        "ck_ingestion_batches_source_type",
        "ingestion_batches",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ingestion_batches_source_type",
        "ingestion_batches",
        "source_type IN ('csv', 'api')",
    )
