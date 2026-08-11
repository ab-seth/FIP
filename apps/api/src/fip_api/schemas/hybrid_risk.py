from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from fip_api.models import RuleRiskLevel


class HybridAssessmentCreate(BaseModel):
    supervised_prediction_id: str
    anomaly_prediction_id: str


class HybridWeightsResponse(BaseModel):
    rules: str
    supervised: str
    anomaly: str


class HybridComponentResponse(BaseModel):
    source_score: str
    normalized_score: str
    weight: str
    contribution_points: str


class HybridComponentsResponse(BaseModel):
    rules: HybridComponentResponse
    supervised: HybridComponentResponse
    anomaly: HybridComponentResponse


class HybridRiskAssessmentResponse(BaseModel):
    id: str
    transaction_id: str
    feature_snapshot_id: str
    rule_assessment_id: str
    supervised_prediction_id: str
    anomaly_prediction_id: str
    policy_version: str
    evidence_schema_version: str
    weights: HybridWeightsResponse
    components: HybridComponentsResponse
    combined_score: str
    risk_level: RuleRiskLevel
    evidence: dict[str, object]
    created_by: str
    assessment_checksum: str
    integrity_verified: bool
    decision_support_only: bool = True
    shadow_inputs_only: bool = True
    affects_case_priority: bool = False
    affects_transaction_action: bool = False
    llm_influenced_score: bool = False
    created_at: datetime


class HybridAssessmentCreationResponse(BaseModel):
    created: bool
    assessment: HybridRiskAssessmentResponse
