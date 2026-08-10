from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
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


class ModelKind(StrEnum):
    SUPERVISED = "supervised"
    ANOMALY = "anomaly"


class ModelPurpose(StrEnum):
    RESEARCH = "research"
    OPERATIONAL = "operational"


class ModelRuntimeContract(StrEnum):
    BINARY_PROBABILITY = "binary-probability-v1"
    ANOMALY_SCORE = "anomaly-score-v1"


class ModelLifecycleStatus(StrEnum):
    CANDIDATE = "candidate"
    SHADOW = "shadow"
    RETIRED = "retired"
    REJECTED = "rejected"


class RegisteredModel(Base):
    __tablename__ = "registered_models"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('supervised', 'anomaly')",
            name="ck_registered_models_kind",
        ),
        CheckConstraint(
            "purpose IN ('research', 'operational')",
            name="ck_registered_models_purpose",
        ),
        CheckConstraint(
            "runtime_contract IN ('binary-probability-v1', 'anomaly-score-v1')",
            name="ck_registered_models_runtime_contract",
        ),
        CheckConstraint(
            "decision_threshold IS NULL OR (decision_threshold >= 0 AND decision_threshold <= 1)",
            name="ck_registered_models_threshold_range",
        ),
        UniqueConstraint("model_key", "version", name="uq_registered_model_key_version"),
        Index("ix_registered_models_model_key", "model_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    model_key: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    runtime_contract: Mapped[str] = mapped_column(String(48), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(64), nullable=False)
    training_dataset_id: Mapped[str] = mapped_column(String(160), nullable=False)
    training_dataset_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    training_data_approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    operational_feature_compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    decision_threshold: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    evaluation_metrics: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    model_card_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    model_card_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    registered_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    registration_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModelLifecycleEvent(Base):
    __tablename__ = "model_lifecycle_events"
    __table_args__ = (
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('candidate', 'shadow', 'retired', 'rejected')",
            name="ck_model_lifecycle_events_from_status",
        ),
        CheckConstraint(
            "to_status IN ('candidate', 'shadow', 'retired', 'rejected')",
            name="ck_model_lifecycle_events_to_status",
        ),
        CheckConstraint(
            "sequence_number > 0",
            name="ck_model_lifecycle_events_sequence_positive",
        ),
        UniqueConstraint(
            "model_id",
            "sequence_number",
            name="uq_model_lifecycle_event_sequence",
        ),
        Index("ix_model_lifecycle_events_model_id", "model_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    model_id: Mapped[str] = mapped_column(
        ForeignKey("registered_models.id", ondelete="RESTRICT"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    previous_event_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ShadowModelPrediction(Base):
    __tablename__ = "shadow_model_predictions"
    __table_args__ = (
        CheckConstraint(
            "score >= 0 AND score <= 1",
            name="ck_shadow_model_predictions_score_range",
        ),
        CheckConstraint(
            "threshold >= 0 AND threshold <= 1",
            name="ck_shadow_model_predictions_threshold_range",
        ),
        CheckConstraint(
            "runtime_milliseconds >= 0",
            name="ck_shadow_model_predictions_runtime_nonnegative",
        ),
        UniqueConstraint(
            "feature_snapshot_id",
            "model_id",
            name="uq_shadow_prediction_snapshot_model",
        ),
        Index("ix_shadow_predictions_transaction_id", "transaction_id"),
        Index("ix_shadow_predictions_model_id", "model_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False
    )
    feature_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("transaction_feature_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(
        ForeignKey("registered_models.id", ondelete="RESTRICT"), nullable=False
    )
    authorization_event_id: Mapped[str] = mapped_column(
        ForeignKey("model_lifecycle_events.id", ondelete="RESTRICT"), nullable=False
    )
    output_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    would_exceed_threshold: Mapped[bool] = mapped_column(Boolean, nullable=False)
    factor_contributions: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    runtime_milliseconds: Mapped[int] = mapped_column(Integer, nullable=False)
    prediction_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ShadowModelEvaluationReport(Base):
    __tablename__ = "shadow_model_evaluation_reports"
    __table_args__ = (
        CheckConstraint(
            "baseline_window_start < baseline_window_end",
            name="ck_shadow_evaluations_baseline_window",
        ),
        CheckConstraint(
            "baseline_window_end <= evaluation_window_start",
            name="ck_shadow_evaluations_nonoverlapping_windows",
        ),
        CheckConstraint(
            "evaluation_window_start < evaluation_window_end",
            name="ck_shadow_evaluations_evaluation_window",
        ),
        CheckConstraint(
            "baseline_prediction_count >= 20",
            name="ck_shadow_evaluations_baseline_count",
        ),
        CheckConstraint(
            "evaluation_prediction_count >= 20",
            name="ck_shadow_evaluations_evaluation_count",
        ),
        UniqueConstraint(
            "model_id",
            "baseline_window_start",
            "baseline_window_end",
            "evaluation_window_start",
            "evaluation_window_end",
            name="uq_shadow_evaluation_model_windows",
        ),
        Index("ix_shadow_evaluations_model_id", "model_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    model_id: Mapped[str] = mapped_column(
        ForeignKey("registered_models.id", ondelete="RESTRICT"), nullable=False
    )
    requested_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    report_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    baseline_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evaluation_window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    evaluation_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    baseline_prediction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluation_prediction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    input_lineage_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    report_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
