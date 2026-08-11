from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
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


class ScoringRuntimeObservation(Base):
    __tablename__ = "scoring_runtime_observations"
    __table_args__ = (
        CheckConstraint(
            "runtime_milliseconds >= 0",
            name="ck_scoring_runtime_observations_nonnegative",
        ),
        UniqueConstraint(
            "rule_assessment_id",
            name="uq_scoring_runtime_observation_rule_assessment",
        ),
        Index("ix_scoring_runtime_observations_transaction_id", "transaction_id"),
        Index("ix_scoring_runtime_observations_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False
    )
    feature_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("transaction_feature_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    rule_assessment_id: Mapped[str] = mapped_column(
        ForeignKey("transaction_rule_assessments.id", ondelete="RESTRICT"), nullable=False
    )
    observation_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_milliseconds: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_assessment_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
