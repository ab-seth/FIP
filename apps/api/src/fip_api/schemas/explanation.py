from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CaseBriefClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=3, max_length=500)
    evidence_refs: list[str] = Field(min_length=1, max_length=8)


class CaseBriefOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str = Field(min_length=12, max_length=1200)
    summary_evidence_refs: list[str] = Field(min_length=1, max_length=12)
    primary_risk_factors: list[CaseBriefClaim] = Field(min_length=1, max_length=8)
    supporting_evidence: list[CaseBriefClaim] = Field(max_length=8)
    uncertainties: list[CaseBriefClaim] = Field(max_length=8)
    recommended_review_steps: list[CaseBriefClaim] = Field(min_length=1, max_length=8)


class CaseBriefCreate(BaseModel):
    hybrid_assessment_id: str | None = None


class GroundingFailureResponse(BaseModel):
    code: str
    location: str
    detail: str


class GroundingValidationResponse(BaseModel):
    schema_valid: bool
    citations_valid: bool
    numerical_claims_valid: bool
    prohibited_actions_absent: bool
    grounding_passed: bool
    failures: list[GroundingFailureResponse]


class CaseBriefValidationResponse(BaseModel):
    provider_candidate: GroundingValidationResponse
    display_output: GroundingValidationResponse
    fallback_used: bool
    fallback_reason: str | None


class CaseBriefResponse(BaseModel):
    id: str
    case_id: str
    transaction_id: str
    rule_assessment_id: str
    hybrid_assessment_id: str | None
    prompt_version: str
    output_schema_version: str
    provider_name: str
    provider_model: str
    generation_mode: Literal["llm", "deterministic_fallback"]
    output: CaseBriefOutput | None
    validation: CaseBriefValidationResponse | None
    evidence_checksum: str
    explanation_checksum: str
    integrity_verified: bool
    generation_milliseconds: int
    requested_by: str
    llm_changed_score: bool = False
    llm_classified_case: bool = False
    financial_action_taken: bool = False
    created_at: datetime


class CaseBriefCreationResponse(BaseModel):
    created: bool
    brief: CaseBriefResponse
