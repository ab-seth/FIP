from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from fip_api.models import (
    CaseClassification,
    CaseEventType,
    CasePriority,
    CaseStatus,
    OutcomeReviewStatus,
    RuleRiskLevel,
)


class CaseReviewStart(BaseModel):
    reason: str = Field(min_length=8, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CaseNoteCreate(BaseModel):
    note: str = Field(min_length=3, max_length=2000)

    @field_validator("note", mode="before")
    @classmethod
    def strip_note(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CaseOutcomeCreate(BaseModel):
    classification: CaseClassification
    rationale: str = Field(min_length=12, max_length=2000)

    @field_validator("rationale", mode="before")
    @classmethod
    def strip_rationale(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CaseOutcomeReviewCreate(BaseModel):
    status: OutcomeReviewStatus
    reason: str = Field(min_length=12, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CaseTransactionResponse(BaseModel):
    id: str
    external_transaction_id: str
    occurred_at: datetime
    amount: Decimal
    currency: str
    account_reference: str
    merchant_reference: str | None
    channel: str | None


class CaseRuleEvidenceResponse(BaseModel):
    rule_score: int
    risk_level: RuleRiskLevel
    ruleset_version: str
    assessment_checksum: str
    feature_set_version: str
    feature_snapshot_checksum: str
    triggered_rules: list[dict[str, object]]
    feature_values: dict[str, object]


class CaseEventResponse(BaseModel):
    sequence_number: int
    event_type: CaseEventType
    payload: dict[str, object]
    actor_username: str
    previous_event_checksum: str | None
    event_checksum: str
    created_at: datetime


class CaseOutcomeReviewResponse(BaseModel):
    status: OutcomeReviewStatus
    reason: str
    reviewed_by: str
    review_checksum: str
    created_at: datetime


class CaseOutcomeResponse(BaseModel):
    id: str
    classification: CaseClassification
    rationale: str
    determined_by: str
    outcome_checksum: str
    review: CaseOutcomeReviewResponse | None
    training_eligible: bool
    created_at: datetime


class CaseSummaryResponse(BaseModel):
    id: str
    display_id: str
    status: CaseStatus
    priority: CasePriority
    transaction: CaseTransactionResponse
    risk_score: int
    risk_level: RuleRiskLevel
    triggered_rule_count: int
    outcome: CaseOutcomeResponse | None
    opening_checksum: str
    integrity_verified: bool
    created_at: datetime
    last_activity_at: datetime


class CaseDetailResponse(CaseSummaryResponse):
    opening_reason: str
    evidence: CaseRuleEvidenceResponse
    events: list[CaseEventResponse]
