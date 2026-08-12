from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fip_api.db.base import Base


class TrainingRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OperationalTrainingRun(Base):
    __tablename__ = "operational_training_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_operational_training_runs_status",
        ),
        CheckConstraint("seed >= 0", name="ck_operational_training_runs_seed_nonnegative"),
        CheckConstraint(
            "maximum_false_positive_rate > 0 AND maximum_false_positive_rate < 1",
            name="ck_operational_training_runs_fpr_range",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_operational_training_runs_attempt_count_nonnegative",
        ),
        UniqueConstraint("candidate_version", name="uq_operational_training_runs_version"),
        UniqueConstraint(
            "configuration_checksum",
            name="uq_operational_training_runs_configuration",
        ),
        Index("ix_operational_training_runs_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    display_id: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("operational_dataset_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    requested_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_version: Mapped[str] = mapped_column(String(64), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_false_positive_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    request_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bundle_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    result_summary: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    evidence_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bundle_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperationalTrainingRunEvent(Base):
    __tablename__ = "operational_training_run_events"
    __table_args__ = (
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_operational_training_run_events_from_status",
        ),
        CheckConstraint(
            "to_status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_operational_training_run_events_to_status",
        ),
        CheckConstraint(
            "sequence_number > 0",
            name="ck_operational_training_run_events_sequence_positive",
        ),
        UniqueConstraint(
            "training_run_id",
            "sequence_number",
            name="uq_operational_training_run_event_sequence",
        ),
        Index(
            "ix_operational_training_run_events_run",
            "training_run_id",
            "sequence_number",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    training_run_id: Mapped[str] = mapped_column(
        ForeignKey("operational_training_runs.id", ondelete="RESTRICT"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str] = mapped_column(String(500), nullable=False)
    actor_username: Mapped[str] = mapped_column(String(120), nullable=False)
    previous_event_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
