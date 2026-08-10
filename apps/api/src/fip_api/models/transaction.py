from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from fip_api.db.base import Base


class IngestionSourceType(StrEnum):
    CSV = "csv"
    API = "api"


class TransactionChannel(StrEnum):
    CARD_PRESENT = "card_present"
    CARD_NOT_PRESENT = "card_not_present"
    ATM = "atm"
    TRANSFER = "transfer"
    OTHER = "other"


class IngestionBatch(Base):
    __tablename__ = "ingestion_batches"
    __table_args__ = (
        CheckConstraint("byte_count > 0", name="ck_ingestion_batches_byte_count_positive"),
        CheckConstraint("row_count > 0", name="ck_ingestion_batches_row_count_positive"),
        CheckConstraint("source_type IN ('csv', 'api')", name="ck_ingestion_batches_source_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    display_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    imported_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("source_row_number > 0", name="ck_transactions_source_row_positive"),
        Index("ix_transactions_occurred_at", "occurred_at"),
        Index("ix_transactions_account_reference", "account_reference"),
        Index("ix_transactions_ingestion_batch_id", "ingestion_batch_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    external_transaction_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    account_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    merchant_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    merchant_category_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    destination_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    ingestion_batch_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_batches.id", ondelete="RESTRICT"), nullable=False
    )
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
