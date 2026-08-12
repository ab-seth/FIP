from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from fip_api.models import DatasetReadinessStatus, DatasetSplit


class DatasetSnapshotCreate(BaseModel):
    reason: str = Field(min_length=12, max_length=500)
    cutoff_at: datetime | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class DatasetReadinessGateResponse(BaseModel):
    gate: str
    passed: bool
    observed: object
    required: str
    detail: str


class DatasetReadinessResponse(BaseModel):
    cutoff_at: datetime
    eligible_label_count: int
    positive_label_count: int
    negative_label_count: int
    excluded_integrity_failures: int
    excluded_feature_contract_mismatches: int
    excluded_temporal_leakage: int
    excluded_synthetic_sources: int
    feature_set_version: str
    label_contract_version: str
    readiness_status: DatasetReadinessStatus
    gates: list[DatasetReadinessGateResponse]


class DatasetSplitCountsResponse(BaseModel):
    train: int
    validation: int
    test: int


class DatasetSummaryResponse(BaseModel):
    id: str
    display_id: str
    feature_set_version: str
    label_contract_version: str
    split_contract_version: str
    feature_names: list[str]
    row_count: int
    positive_count: int
    negative_count: int
    split_counts: DatasetSplitCountsResponse
    readiness_status: DatasetReadinessStatus
    readiness_gates: list[DatasetReadinessGateResponse]
    creation_reason: str
    cutoff_at: datetime
    created_by: str
    source_manifest_checksum: str
    dataset_checksum: str
    integrity_verified: bool
    created_at: datetime


class DatasetRowResponse(BaseModel):
    row_index: int
    occurred_at: datetime
    split: DatasetSplit
    label: int
    feature_values: dict[str, object]
    feature_snapshot_checksum: str
    outcome_checksum: str
    review_checksum: str
    row_checksum: str


class DatasetDetailResponse(DatasetSummaryResponse):
    rows: list[DatasetRowResponse]
    rows_truncated: bool


class DatasetSnapshotCreateResponse(BaseModel):
    created: bool
    dataset: DatasetDetailResponse
