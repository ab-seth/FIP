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


class CasePriority(StrEnum):
    STANDARD = "standard"
    URGENT = "urgent"


class CaseStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    CLASSIFIED = "classified"


class CaseEventType(StrEnum):
    OPENED = "opened"
    REVIEW_STARTED = "review_started"
    NOTE_ADDED = "note_added"
    CLASSIFIED = "classified"
    OUTCOME_REVIEWED = "outcome_reviewed"
    BRIEF_GENERATED = "brief_generated"


class CaseClassification(StrEnum):
    CONFIRMED_FRAUD = "confirmed_fraud"
    LEGITIMATE = "legitimate"
    INCONCLUSIVE = "inconclusive"


class OutcomeReviewStatus(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class AnalystCase(Base):
    __tablename__ = "analyst_cases"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('standard', 'urgent')",
            name="ck_analyst_cases_priority",
        ),
        UniqueConstraint("transaction_id", name="uq_analyst_cases_transaction"),
        Index("ix_analyst_cases_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    display_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False
    )
    feature_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("transaction_feature_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    rule_assessment_id: Mapped[str] = mapped_column(
        ForeignKey("transaction_rule_assessments.id", ondelete="RESTRICT"), nullable=False
    )
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    opening_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    opening_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CaseEvent(Base):
    __tablename__ = "case_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('opened', 'review_started', 'note_added', "
            "'classified', 'outcome_reviewed', 'brief_generated')",
            name="ck_case_events_type",
        ),
        CheckConstraint("sequence_number > 0", name="ck_case_events_sequence_positive"),
        UniqueConstraint("case_id", "sequence_number", name="uq_case_event_sequence"),
        Index("ix_case_events_case_id", "case_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(
        ForeignKey("analyst_cases.id", ondelete="RESTRICT"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    actor_username: Mapped[str] = mapped_column(String(120), nullable=False)
    previous_event_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CaseOutcome(Base):
    __tablename__ = "case_outcomes"
    __table_args__ = (
        CheckConstraint(
            "classification IN ('confirmed_fraud', 'legitimate', 'inconclusive')",
            name="ck_case_outcomes_classification",
        ),
        UniqueConstraint("case_id", name="uq_case_outcomes_case"),
        Index("ix_case_outcomes_case_id", "case_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(
        ForeignKey("analyst_cases.id", ondelete="RESTRICT"), nullable=False
    )
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(String(2000), nullable=False)
    determined_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    outcome_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CaseOutcomeReview(Base):
    __tablename__ = "case_outcome_reviews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('approved', 'rejected')",
            name="ck_case_outcome_reviews_status",
        ),
        UniqueConstraint("outcome_id", name="uq_case_outcome_reviews_outcome"),
        Index("ix_case_outcome_reviews_outcome_id", "outcome_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    outcome_id: Mapped[str] = mapped_column(
        ForeignKey("case_outcomes.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    reviewed_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    review_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
