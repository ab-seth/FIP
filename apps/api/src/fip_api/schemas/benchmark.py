from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from fip_api.models.benchmark import BenchmarkRunStatus


class BenchmarkRunCreate(BaseModel):
    transaction_count: int = Field(default=10_000, ge=100, le=10_000)
    seed: int = Field(default=42, ge=0, le=2_147_483_647)
    reason: str = Field(min_length=12, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class BenchmarkRunEventResponse(BaseModel):
    sequence_number: int
    from_status: BenchmarkRunStatus | None
    to_status: BenchmarkRunStatus
    detail: str
    actor_username: str
    previous_event_checksum: str | None
    event_checksum: str
    created_at: datetime


class BenchmarkResultResponse(BaseModel):
    processed_transaction_count: int
    rule_assessment_count: int
    verified_runtime_observation_count: int
    risk_distribution: dict[str, int]
    opened_case_count: int
    mean_scoring_milliseconds: str | None
    p95_scoring_milliseconds: str | None
    maximum_scoring_milliseconds: int | None
    under_latency_target_count: int
    elapsed_milliseconds: int | None
    throughput_per_second: str | None
    transaction_set_checksum: str
    assessment_set_checksum: str
    runtime_set_checksum: str
    case_set_checksum: str
    volume_target_met: bool
    latency_target_met: bool
    pipeline_complete: bool
    acceptance_met: bool


class BenchmarkRunResponse(BaseModel):
    id: str
    display_id: str
    requested_by: str
    transaction_count: int
    seed: int
    reason: str
    generator_version: str
    configuration_checksum: str
    dataset_checksum: str
    profile_distribution: dict[str, object]
    status: BenchmarkRunStatus
    attempt_count: int
    ingestion_batch_id: str | None
    ingestion_batch_display_id: str | None
    result: BenchmarkResultResponse | None
    report_checksum: str | None
    error_code: str | None
    error_message: str | None
    integrity_verified: bool
    events: list[BenchmarkRunEventResponse]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    synthetic_only: bool = True
    eligible_for_operational_training: bool = False
    model_efficacy_claim: bool = False
    changes_operational_configuration: bool = False


class BenchmarkRunCreationResponse(BaseModel):
    created: bool
    run: BenchmarkRunResponse


class BenchmarkReportResponse(BaseModel):
    schema_version: str
    run: BenchmarkRunResponse
    report_checksum: str
    evidence_statement: str
