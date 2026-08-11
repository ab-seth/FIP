from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from fip_api.schemas.model_evaluation import ShadowEvaluationReportResponse

EvaluationGateStatus = Literal[
    "passed",
    "failed",
    "not_observed",
    "not_demonstrated",
]


class EvaluationGateResponse(BaseModel):
    gate: str
    status: EvaluationGateStatus
    observed: str | int | bool | None
    target: str
    detail: str


class LatencySummaryResponse(BaseModel):
    observation_count: int
    mean_milliseconds: str | None
    p95_milliseconds: str | None
    maximum_milliseconds: int | None
    target_milliseconds: int
    status: EvaluationGateStatus


class EvaluationVolumeResponse(BaseModel):
    transactions: int
    rule_assessments: int
    low_risk: int
    medium_risk: int
    high_risk: int
    cases: int
    open_cases: int
    in_review_cases: int
    classified_cases: int
    confirmed_fraud: int
    legitimate: int
    inconclusive: int


class ExplanationEvaluationResponse(BaseModel):
    total_briefs: int
    validated_llm_briefs: int
    deterministic_fallbacks: int
    fallback_rate: str | None
    provider_candidate_grounding_failures: int
    displayed_grounding_failures: int
    fallback_reasons: dict[str, int]
    llm_latency: LatencySummaryResponse


class ModelEvidenceResponse(BaseModel):
    registered_models: int
    verified_model_lineages: int
    shadow_predictions: int
    hybrid_assessments: int
    shadow_evaluation_reports: int
    verified_shadow_evaluation_reports: int


class IntegritySummaryResponse(BaseModel):
    case_events: int
    case_records: int
    case_integrity_failures: int
    model_records: int
    model_integrity_failures: int
    case_brief_records: int
    case_brief_integrity_failures: int
    hybrid_records: int
    hybrid_integrity_failures: int
    dataset_records: int
    dataset_integrity_failures: int
    evaluation_report_records: int
    evaluation_report_integrity_failures: int
    scoring_observation_records: int
    scoring_observation_integrity_failures: int


class VersionLineageResponse(BaseModel):
    feature_set: str
    ruleset: str
    risk_bands: str
    scoring_runtime_observation: str
    shadow_output: str
    hybrid_policy: str
    case_brief_prompt: str
    case_brief_output: str
    model_evaluation_report: str
    label_contract: str
    split_contract: str


class SystemEvaluationRecordResponse(BaseModel):
    schema_version: str
    evidence_as_of: datetime | None
    overall_status: Literal["passed", "attention", "evidence_pending"]
    volume: EvaluationVolumeResponse
    scoring_latency: LatencySummaryResponse
    explanations: ExplanationEvaluationResponse
    model_evidence: ModelEvidenceResponse
    integrity: IntegritySummaryResponse
    versions: VersionLineageResponse
    gates: list[EvaluationGateResponse]
    latest_model_evaluations: list[ShadowEvaluationReportResponse]
    snapshot_checksum: str
    read_only: bool = True
    changes_operational_state: bool = False
