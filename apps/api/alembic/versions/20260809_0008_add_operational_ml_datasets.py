"""Add immutable operational ML dataset snapshots.

Revision ID: 20260809_0008
Revises: 20260809_0007
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_0008"
down_revision: str | None = "20260809_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operational_dataset_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_id", sa.String(length=20), nullable=False),
        sa.Column("feature_set_version", sa.String(length=64), nullable=False),
        sa.Column("label_contract_version", sa.String(length=64), nullable=False),
        sa.Column("split_contract_version", sa.String(length=64), nullable=False),
        sa.Column("feature_names", sa.JSON(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("positive_count", sa.Integer(), nullable=False),
        sa.Column("negative_count", sa.Integer(), nullable=False),
        sa.Column("train_count", sa.Integer(), nullable=False),
        sa.Column("validation_count", sa.Integer(), nullable=False),
        sa.Column("test_count", sa.Integer(), nullable=False),
        sa.Column("readiness_status", sa.String(length=16), nullable=False),
        sa.Column("readiness_gates", sa.JSON(), nullable=False),
        sa.Column("creation_reason", sa.String(length=500), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("source_manifest_checksum", sa.String(length=64), nullable=False),
        sa.Column("dataset_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "readiness_status IN ('blocked', 'ready')",
            name="ck_operational_datasets_readiness_status",
        ),
        sa.CheckConstraint(
            "row_count > 0",
            name="ck_operational_datasets_row_count_positive",
        ),
        sa.CheckConstraint(
            "positive_count >= 0 AND negative_count >= 0",
            name="ck_operational_datasets_label_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "row_count = positive_count + negative_count",
            name="ck_operational_datasets_label_counts_total",
        ),
        sa.CheckConstraint(
            "row_count = train_count + validation_count + test_count",
            name="ck_operational_datasets_split_counts_total",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_checksum"),
        sa.UniqueConstraint("display_id"),
        sa.UniqueConstraint(
            "source_manifest_checksum",
            name="uq_operational_dataset_source_manifest",
        ),
    )
    op.create_index(
        "ix_operational_datasets_created_at",
        "operational_dataset_snapshots",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "operational_dataset_rows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("feature_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("outcome_id", sa.String(length=36), nullable=False),
        sa.Column("review_id", sa.String(length=36), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("split", sa.String(length=16), nullable=False),
        sa.Column("label", sa.Integer(), nullable=False),
        sa.Column("feature_values", sa.JSON(), nullable=False),
        sa.Column("feature_snapshot_checksum", sa.String(length=64), nullable=False),
        sa.Column("outcome_checksum", sa.String(length=64), nullable=False),
        sa.Column("review_checksum", sa.String(length=64), nullable=False),
        sa.Column("row_checksum", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "row_index > 0",
            name="ck_operational_dataset_rows_index_positive",
        ),
        sa.CheckConstraint(
            "label IN (0, 1)",
            name="ck_operational_dataset_rows_binary_label",
        ),
        sa.CheckConstraint(
            "split IN ('train', 'validation', 'test')",
            name="ck_operational_dataset_rows_split",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["analyst_cases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["operational_dataset_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["feature_snapshot_id"],
            ["transaction_feature_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["outcome_id"], ["case_outcomes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["case_outcome_reviews.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("row_checksum"),
        sa.UniqueConstraint(
            "dataset_id",
            "feature_snapshot_id",
            name="uq_operational_dataset_row_feature_snapshot",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "row_index",
            name="uq_operational_dataset_row_index",
        ),
    )
    op.create_index(
        "ix_operational_dataset_rows_dataset_id",
        "operational_dataset_rows",
        ["dataset_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_operational_dataset_rows_dataset_id",
        table_name="operational_dataset_rows",
    )
    op.drop_table("operational_dataset_rows")
    op.drop_index(
        "ix_operational_datasets_created_at",
        table_name="operational_dataset_snapshots",
    )
    op.drop_table("operational_dataset_snapshots")
