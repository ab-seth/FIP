from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fip_api.db.base import Base


class DatasetReadinessStatus(StrEnum):
    BLOCKED = "blocked"
    READY = "ready"


class DatasetSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class OperationalDatasetSnapshot(Base):
    __tablename__ = "operational_dataset_snapshots"
    __table_args__ = (
        CheckConstraint(
            "readiness_status IN ('blocked', 'ready')",
            name="ck_operational_datasets_readiness_status",
        ),
        CheckConstraint("row_count > 0", name="ck_operational_datasets_row_count_positive"),
        CheckConstraint(
            "positive_count >= 0 AND negative_count >= 0",
            name="ck_operational_datasets_label_counts_nonnegative",
        ),
        CheckConstraint(
            "row_count = positive_count + negative_count",
            name="ck_operational_datasets_label_counts_total",
        ),
        CheckConstraint(
            "row_count = train_count + validation_count + test_count",
            name="ck_operational_datasets_split_counts_total",
        ),
        UniqueConstraint("source_manifest_checksum", name="uq_operational_dataset_source_manifest"),
        Index("ix_operational_datasets_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    display_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(64), nullable=False)
    label_contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    split_contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    positive_count: Mapped[int] = mapped_column(Integer, nullable=False)
    negative_count: Mapped[int] = mapped_column(Integer, nullable=False)
    train_count: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    test_count: Mapped[int] = mapped_column(Integer, nullable=False)
    readiness_status: Mapped[str] = mapped_column(String(16), nullable=False)
    readiness_gates: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    creation_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    source_manifest_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperationalDatasetRow(Base):
    __tablename__ = "operational_dataset_rows"
    __table_args__ = (
        CheckConstraint("row_index > 0", name="ck_operational_dataset_rows_index_positive"),
        CheckConstraint("label IN (0, 1)", name="ck_operational_dataset_rows_binary_label"),
        CheckConstraint(
            "split IN ('train', 'validation', 'test')",
            name="ck_operational_dataset_rows_split",
        ),
        UniqueConstraint("dataset_id", "row_index", name="uq_operational_dataset_row_index"),
        UniqueConstraint(
            "dataset_id",
            "feature_snapshot_id",
            name="uq_operational_dataset_row_feature_snapshot",
        ),
        Index("ix_operational_dataset_rows_dataset_id", "dataset_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("operational_dataset_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("analyst_cases.id", ondelete="RESTRICT"), nullable=False
    )
    feature_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("transaction_feature_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    outcome_id: Mapped[str] = mapped_column(
        ForeignKey("case_outcomes.id", ondelete="RESTRICT"), nullable=False
    )
    review_id: Mapped[str] = mapped_column(
        ForeignKey("case_outcome_reviews.id", ondelete="RESTRICT"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    split: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[int] = mapped_column(Integer, nullable=False)
    feature_values: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    feature_snapshot_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    review_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    row_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
