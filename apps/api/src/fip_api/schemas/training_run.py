from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from fip_api.models import ModelKind, ModelRuntimeContract, TrainingRunStatus
from fip_api.schemas.model_registry import VERSION_PATTERN


class TrainingRunCreate(BaseModel):
    dataset_id: str = Field(min_length=3, max_length=36)
    candidate_version: str = Field(pattern=VERSION_PATTERN)
    seed: int = Field(default=42, ge=0, le=2_147_483_647)
    maximum_false_positive_rate: Decimal = Field(
        default=Decimal("0.05"), gt=0, lt=1, decimal_places=6
    )
    reason: str = Field(min_length=12, max_length=500)

    @field_validator("dataset_id", "candidate_version", "reason", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class TrainingRunEventResponse(BaseModel):
    sequence_number: int
    from_status: TrainingRunStatus | None
    to_status: TrainingRunStatus
    detail: str
    actor_username: str
    previous_event_checksum: str | None
    event_checksum: str
    created_at: datetime


class TrainingCandidateResponse(BaseModel):
    model_key: str
    version: str
    kind: ModelKind
    runtime_contract: ModelRuntimeContract
    artifact_sha256: str
    model_card_checksum: str
    registration_payload_checksum: str
    decision_threshold: str | None
    evaluation_metrics: dict[str, object]
    selected_model: str
    registration_download: str
    model_card_download: str
    artifact_download: str


class TrainingRunResponse(BaseModel):
    id: str
    display_id: str
    dataset_id: str
    dataset_display_id: str
    dataset_checksum: str
    requested_by: str
    candidate_version: str
    seed: int
    maximum_false_positive_rate: str
    reason: str
    pipeline_version: str
    configuration_checksum: str
    status: TrainingRunStatus
    attempt_count: int
    candidates: dict[Literal["supervised", "anomaly"], TrainingCandidateResponse] | None
    evidence_checksum: str | None
    manifest_checksum: str | None
    bundle_checksum: str | None
    error_code: str | None
    error_message: str | None
    integrity_verified: bool
    events: list[TrainingRunEventResponse]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    candidate_only: bool = True
    automatic_registration: bool = False
    automatic_shadow_promotion: bool = False
    affects_operational_score: bool = False


class TrainingRunCreationResponse(BaseModel):
    created: bool
    run: TrainingRunResponse
