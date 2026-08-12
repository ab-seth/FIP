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


class BenchmarkRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SyntheticBenchmarkRun(Base):
    __tablename__ = "synthetic_benchmark_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_synthetic_benchmark_runs_status",
        ),
        CheckConstraint(
            "transaction_count >= 100 AND transaction_count <= 10000",
            name="ck_synthetic_benchmark_runs_count",
        ),
        CheckConstraint("seed >= 0", name="ck_synthetic_benchmark_runs_seed"),
        CheckConstraint("attempt_count >= 0", name="ck_synthetic_benchmark_runs_attempts"),
        UniqueConstraint(
            "configuration_checksum",
            name="uq_synthetic_benchmark_runs_configuration",
        ),
        UniqueConstraint("ingestion_batch_id", name="uq_synthetic_benchmark_runs_batch"),
        Index("ix_synthetic_benchmark_runs_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    display_id: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    requested_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    request_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_distribution: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ingestion_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("ingestion_batches.id", ondelete="RESTRICT"), nullable=True
    )
    result_summary: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    report_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SyntheticBenchmarkRunEvent(Base):
    __tablename__ = "synthetic_benchmark_run_events"
    __table_args__ = (
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_synthetic_benchmark_events_from_status",
        ),
        CheckConstraint(
            "to_status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_synthetic_benchmark_events_to_status",
        ),
        CheckConstraint("sequence_number > 0", name="ck_synthetic_benchmark_events_sequence"),
        UniqueConstraint(
            "benchmark_run_id",
            "sequence_number",
            name="uq_synthetic_benchmark_event_sequence",
        ),
        Index(
            "ix_synthetic_benchmark_events_run",
            "benchmark_run_id",
            "sequence_number",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    benchmark_run_id: Mapped[str] = mapped_column(
        ForeignKey("synthetic_benchmark_runs.id", ondelete="RESTRICT"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str] = mapped_column(String(500), nullable=False)
    actor_username: Mapped[str] = mapped_column(String(120), nullable=False)
    previous_event_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
