from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ResearchDatasetEvidenceResponse(BaseModel):
    dataset_id: str
    display_name: str
    source_page: str
    provenance: str
    observation_period: str
    provider_license: str
    provider_md5: str
    source_file_sha256: str
    row_count: int
    positive_count: int
    negative_count: int
    prevalence: str
    feature_count: int
    operational_feature_compatible: bool = False
    operational_block_reason: str


class ResearchPartitionEvidenceResponse(BaseModel):
    name: Literal["train", "calibration", "validation", "test"]
    purpose: str
    row_count: int
    positive_count: int
    minimum_event_time: int
    maximum_event_time: int


class ResearchValidationMetricsResponse(BaseModel):
    average_precision: str
    roc_auc: str
    brier_score: str
    expected_calibration_error: str
    precision: str
    recall: str
    f1: str
    false_positive_rate: str
    alert_rate: str
    threshold: str


class ResearchCandidateEvidenceResponse(BaseModel):
    model_key: str
    display_name: str
    selected: bool
    validation: ResearchValidationMetricsResponse


class ResearchTestEvidenceResponse(ResearchValidationMetricsResponse):
    row_count: int
    positive_count: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int


class ResearchFeatureImportanceResponse(BaseModel):
    feature: str
    mean_pr_auc_decrease: str
    standard_deviation: str


class ResearchExplainabilityEvidenceResponse(BaseModel):
    method: str
    repeats: int
    validation_sample_fraction: str
    semantic_limit: str
    features: list[ResearchFeatureImportanceResponse]


class ResearchRuntimeEvidenceResponse(BaseModel):
    python: str
    numpy: str
    scikit_learn: str


class ResearchArtifactEvidenceResponse(BaseModel):
    metrics_sha256: str
    model_card_sha256: str
    model_artifact_sha256: str
    run_manifest_sha256: str


class ResearchReproducibilityEvidenceResponse(BaseModel):
    pipeline_version: str
    random_seed: int
    maximum_validation_false_positive_rate: str
    split_contract: str
    runtime: ResearchRuntimeEvidenceResponse
    artifacts: ResearchArtifactEvidenceResponse


class ResearchClaimsBoundaryResponse(BaseModel):
    evidence_scope: Literal["research_methodology"] = "research_methodology"
    research_only: bool = True
    real_public_transactions: bool = True
    eligible_for_operational_promotion: bool = False
    demonstrates_institution_specific_efficacy: bool = False
    affects_operational_score: bool = False
    triggers_automatic_action: bool = False
    statement: str


class ResearchEvidenceResponse(BaseModel):
    schema_version: str
    run_id: str
    created_at: datetime
    dataset: ResearchDatasetEvidenceResponse
    partitions: list[ResearchPartitionEvidenceResponse]
    candidates: list[ResearchCandidateEvidenceResponse]
    selected_model: str
    held_out_test: ResearchTestEvidenceResponse
    explainability: ResearchExplainabilityEvidenceResponse
    reproducibility: ResearchReproducibilityEvidenceResponse
    claims: ResearchClaimsBoundaryResponse
    evidence_checksum: str
    integrity_verified: bool
    read_only: bool = True
    changes_operational_state: bool = False
