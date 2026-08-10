from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from fip_api.models import RuleRiskLevel


class SemanticFeatureValues(BaseModel):
    amount: str
    currency: str
    occurred_hour_utc: int
    occurred_day_of_week_utc: int
    is_weekend_utc: bool
    is_off_hours_utc: bool
    is_cross_border: bool | None
    channel: str | None
    merchant_reference: str | None
    merchant_category_code: str | None
    source_country: str | None
    destination_country: str | None
    prior_transaction_count_1h: int
    prior_transaction_count_24h: int
    prior_transaction_count_30d: int
    prior_same_currency_count_30d: int
    prior_same_currency_median_amount_30d: str | None
    amount_to_median_ratio_30d: str | None
    merchant_seen_before_30d: bool | None


class RuleTriggerResponse(BaseModel):
    rule_id: str
    title: str
    contribution_points: int
    evidence: dict[str, str | int | bool | None]


class FeatureSnapshotResponse(BaseModel):
    feature_set_version: str
    history_window_start: datetime
    history_window_end: datetime
    history_checksum: str
    snapshot_checksum: str
    values: SemanticFeatureValues
    created_at: datetime


class RuleAssessmentResponse(BaseModel):
    transaction_id: str
    scoring_method: Literal["deterministic_rules"] = "deterministic_rules"
    ruleset_version: str
    risk_band_version: str
    evaluated_rule_count: int
    rule_score: int
    risk_level: RuleRiskLevel
    triggered_rules: list[RuleTriggerResponse]
    assessment_checksum: str
    feature_snapshot: FeatureSnapshotResponse
    created_at: datetime
