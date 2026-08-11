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


class HybridRiskAssessment(Base):
    __tablename__ = "hybrid_risk_assessments"
    __table_args__ = (
        CheckConstraint(
            "rules_weight >= 0 AND rules_weight <= 1",
            name="ck_hybrid_risk_rules_weight_range",
        ),
        CheckConstraint(
            "supervised_weight >= 0 AND supervised_weight <= 1",
            name="ck_hybrid_risk_supervised_weight_range",
        ),
        CheckConstraint(
            "anomaly_weight >= 0 AND anomaly_weight <= 1",
            name="ck_hybrid_risk_anomaly_weight_range",
        ),
        CheckConstraint(
            "rules_weight + supervised_weight + anomaly_weight = 1",
            name="ck_hybrid_risk_weights_total",
        ),
        CheckConstraint(
            "rule_score >= 0 AND rule_score <= 100",
            name="ck_hybrid_risk_rule_score_range",
        ),
        CheckConstraint(
            "supervised_score >= 0 AND supervised_score <= 1",
            name="ck_hybrid_risk_supervised_score_range",
        ),
        CheckConstraint(
            "anomaly_score >= 0 AND anomaly_score <= 1",
            name="ck_hybrid_risk_anomaly_score_range",
        ),
        CheckConstraint(
            "combined_score >= 0 AND combined_score <= 100",
            name="ck_hybrid_risk_combined_score_range",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="ck_hybrid_risk_level",
        ),
        UniqueConstraint(
            "feature_snapshot_id",
            "rule_assessment_id",
            "policy_version",
            "supervised_prediction_id",
            "anomaly_prediction_id",
            name="uq_hybrid_risk_evidence_set",
        ),
        Index("ix_hybrid_risk_transaction_id", "transaction_id"),
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
    supervised_prediction_id: Mapped[str] = mapped_column(
        ForeignKey("shadow_model_predictions.id", ondelete="RESTRICT"), nullable=False
    )
    anomaly_prediction_id: Mapped[str] = mapped_column(
        ForeignKey("shadow_model_predictions.id", ondelete="RESTRICT"), nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    rules_weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    supervised_weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    anomaly_weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    rule_score: Mapped[int] = mapped_column(Integer, nullable=False)
    supervised_score: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    anomaly_score: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    combined_score: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_package: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    assessment_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
