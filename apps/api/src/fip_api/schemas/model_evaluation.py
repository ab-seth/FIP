from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator


class ShadowEvaluationCreate(BaseModel):
    baseline_window_start: datetime
    baseline_window_end: datetime
    evaluation_window_start: datetime
    evaluation_window_end: datetime

    @field_validator(
        "baseline_window_start",
        "baseline_window_end",
        "evaluation_window_start",
        "evaluation_window_end",
    )
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Shadow evaluation windows must include a timezone.")
        return value

    @model_validator(mode="after")
    def validate_window_order(self) -> ShadowEvaluationCreate:
        if self.baseline_window_start >= self.baseline_window_end:
            raise ValueError("The baseline window start must be before its end.")
        if self.baseline_window_end > self.evaluation_window_start:
            raise ValueError("Baseline and evaluation windows cannot overlap.")
        if self.evaluation_window_start >= self.evaluation_window_end:
            raise ValueError("The evaluation window start must be before its end.")
        return self


class ShadowEvaluationReportResponse(BaseModel):
    id: str
    model_id: str
    model_key: str
    model_version: str
    report_schema_version: str
    baseline_window_start: datetime
    baseline_window_end: datetime
    evaluation_window_start: datetime
    evaluation_window_end: datetime
    baseline_prediction_count: int
    evaluation_prediction_count: int
    metrics: dict[str, object]
    input_lineage_checksum: str
    report_checksum: str
    requested_by: str
    integrity_verified: bool
    monitoring_only: bool = True
    affects_operational_score: bool = False
    triggers_automatic_action: bool = False
    created_at: datetime


class ShadowEvaluationCreationResponse(BaseModel):
    created: bool
    report: ShadowEvaluationReportResponse
