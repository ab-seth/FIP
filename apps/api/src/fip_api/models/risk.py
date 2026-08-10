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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from fip_api.db.base import Base


class RuleRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TransactionFeatureSnapshot(Base):
    __tablename__ = "transaction_feature_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "transaction_id",
            "feature_set_version",
            name="uq_transaction_feature_snapshot_version",
        ),
        Index("ix_feature_snapshots_transaction_id", "transaction_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False
    )
    feature_set_version: Mapped[str] = mapped_column(String(64), nullable=False)
    history_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    history_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    history_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_values: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    snapshot_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TransactionRuleAssessment(Base):
    __tablename__ = "transaction_rule_assessments"
    __table_args__ = (
        CheckConstraint(
            "rule_score >= 0 AND rule_score <= 100",
            name="ck_transaction_rule_assessments_score_range",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="ck_transaction_rule_assessments_risk_level",
        ),
        UniqueConstraint(
            "feature_snapshot_id",
            "ruleset_version",
            "risk_band_version",
            name="uq_transaction_rule_assessment_versions",
        ),
        Index("ix_rule_assessments_transaction_id", "transaction_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False
    )
    feature_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("transaction_feature_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    ruleset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_band_version: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    triggered_rules: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    assessment_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
