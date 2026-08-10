"""Create transaction intake records.

Revision ID: 20260809_0003
Revises: 20260807_0002
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_0003"
down_revision: str | None = "20260807_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_id", sa.String(length=16), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("source_checksum", sa.String(length=64), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("imported_by_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("byte_count > 0", name="ck_ingestion_batches_byte_count_positive"),
        sa.CheckConstraint("row_count > 0", name="ck_ingestion_batches_row_count_positive"),
        sa.CheckConstraint(
            "source_type IN ('csv', 'api')", name="ck_ingestion_batches_source_type"
        ),
        sa.ForeignKeyConstraint(["imported_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("display_id"),
        sa.UniqueConstraint("source_checksum"),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("external_transaction_id", sa.String(length=120), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("account_reference", sa.String(length=120), nullable=False),
        sa.Column("merchant_reference", sa.String(length=120), nullable=True),
        sa.Column("merchant_category_code", sa.String(length=12), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=True),
        sa.Column("source_country", sa.String(length=2), nullable=True),
        sa.Column("destination_country", sa.String(length=2), nullable=True),
        sa.Column("ingestion_batch_id", sa.String(length=36), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        sa.CheckConstraint("source_row_number > 0", name="ck_transactions_source_row_positive"),
        sa.ForeignKeyConstraint(
            ["ingestion_batch_id"], ["ingestion_batches.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_transaction_id"),
    )
    op.create_index(
        "ix_transactions_account_reference",
        "transactions",
        ["account_reference"],
        unique=False,
    )
    op.create_index(
        "ix_transactions_ingestion_batch_id",
        "transactions",
        ["ingestion_batch_id"],
        unique=False,
    )
    op.create_index("ix_transactions_occurred_at", "transactions", ["occurred_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_transactions_occurred_at", table_name="transactions")
    op.drop_index("ix_transactions_ingestion_batch_id", table_name="transactions")
    op.drop_index("ix_transactions_account_reference", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("ingestion_batches")
