from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from fip_api.db.base import Base


class CaseBrief(Base):
    __tablename__ = "case_briefs"
    __table_args__ = (
        CheckConstraint(
            "generation_mode IN ('llm', 'deterministic_fallback')",
            name="ck_case_briefs_generation_mode",
        ),
        CheckConstraint(
            "generation_milliseconds >= 0",
            name="ck_case_briefs_generation_milliseconds_nonnegative",
        ),
        Index("ix_case_briefs_case_id", "case_id"),
        Index("ix_case_briefs_transaction_id", "transaction_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(
        ForeignKey("analyst_cases.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False
    )
    rule_assessment_id: Mapped[str] = mapped_column(
        ForeignKey("transaction_rule_assessments.id", ondelete="RESTRICT"), nullable=False
    )
    hybrid_assessment_id: Mapped[str | None] = mapped_column(
        ForeignKey("hybrid_risk_assessments.id", ondelete="RESTRICT"), nullable=True
    )
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    output_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_model: Mapped[str] = mapped_column(String(120), nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    input_evidence: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    evidence_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_output: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    provider_raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_output: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    validation_report: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    generation_milliseconds: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    explanation_checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
