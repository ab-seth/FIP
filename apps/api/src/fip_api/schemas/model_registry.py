from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from fip_api.models import (
    ModelKind,
    ModelLifecycleStatus,
    ModelPurpose,
    ModelRuntimeContract,
)

SHA256_PATTERN = r"^[0-9a-f]{64}$"
MODEL_KEY_PATTERN = r"^[a-z][a-z0-9-]{2,63}$"
VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"


class ModelRegistrationCreate(BaseModel):
    model_key: str = Field(pattern=MODEL_KEY_PATTERN)
    version: str = Field(pattern=VERSION_PATTERN)
    kind: ModelKind
    purpose: ModelPurpose
    runtime_contract: ModelRuntimeContract
    artifact_sha256: str = Field(pattern=SHA256_PATTERN)
    feature_set_version: str = Field(min_length=3, max_length=64)
    training_dataset_id: str = Field(min_length=3, max_length=160)
    training_dataset_checksum: str = Field(pattern=SHA256_PATTERN)
    training_data_approved: bool
    operational_feature_compatible: bool
    decision_threshold: Decimal | None = Field(default=None, ge=0, le=1, decimal_places=10)
    evaluation_metrics: dict[str, float | int | str | bool] = Field(min_length=1)
    model_card_reference: str = Field(min_length=3, max_length=500)
    model_card_checksum: str = Field(pattern=SHA256_PATTERN)

    @field_validator(
        "artifact_sha256",
        "training_dataset_checksum",
        "model_card_checksum",
        mode="before",
    )
    @classmethod
    def normalize_checksum(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value


class ModelTransitionCreate(BaseModel):
    target_status: ModelLifecycleStatus
    reason: str = Field(min_length=12, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ModelLifecycleEventResponse(BaseModel):
    sequence_number: int
    from_status: ModelLifecycleStatus | None
    to_status: ModelLifecycleStatus
    reason: str
    actor_username: str
    previous_event_checksum: str | None
    event_checksum: str
    created_at: datetime


class RegisteredModelResponse(BaseModel):
    id: str
    model_key: str
    version: str
    kind: ModelKind
    purpose: ModelPurpose
    runtime_contract: ModelRuntimeContract
    artifact_sha256: str
    feature_set_version: str
    training_dataset_id: str
    training_dataset_checksum: str
    training_data_approved: bool
    operational_feature_compatible: bool
    decision_threshold: str | None
    evaluation_metrics: dict[str, object]
    model_card_reference: str
    model_card_checksum: str
    registered_by: str
    registration_checksum: str
    current_status: ModelLifecycleStatus
    lineage_verified: bool
    lifecycle: list[ModelLifecycleEventResponse]
    created_at: datetime


class ModelRegistrationResponse(BaseModel):
    created: bool
    model: RegisteredModelResponse


class ModelArtifactInstallationResponse(BaseModel):
    model_id: str
    artifact_sha256: str
    size_bytes: int
    installed: bool
    integrity_verified: bool = True


class ShadowFactorResponse(BaseModel):
    feature: str
    contribution: str
    direction: str


class ShadowPredictionResponse(BaseModel):
    id: str
    transaction_id: str
    model_id: str
    model_key: str
    model_version: str
    feature_set_version: str
    feature_snapshot_checksum: str
    authorization_event_checksum: str
    output_schema_version: str
    score: str
    threshold: str
    would_exceed_model_threshold: bool
    factors: list[ShadowFactorResponse]
    runtime_milliseconds: int
    prediction_checksum: str
    integrity_verified: bool
    shadow_only: bool = True
    affects_operational_score: bool = False
    created_at: datetime


class ShadowRunCreate(BaseModel):
    transaction_ids: list[str] | None = Field(default=None, min_length=1, max_length=1_000)
    limit: int = Field(default=100, ge=1, le=1_000)

    @field_validator("transaction_ids")
    @classmethod
    def validate_unique_transaction_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [transaction_id.strip() for transaction_id in value]
        if any(not transaction_id for transaction_id in normalized):
            raise ValueError("Transaction identifiers cannot be empty.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Transaction identifiers must be unique.")
        return normalized


class ShadowRunResponse(BaseModel):
    model_id: str
    selected_count: int
    created_count: int
    replayed_count: int
    shadow_only: bool = True
    affects_operational_score: bool = False
    predictions: list[ShadowPredictionResponse]
