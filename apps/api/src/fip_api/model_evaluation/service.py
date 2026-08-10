from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.core.checksums import canonical_json_checksum
from fip_api.model_evaluation.metrics import EvaluationObservation, build_evaluation_metrics
from fip_api.model_registry import (
    GovernanceViolation,
    ModelNotFound,
    verify_model_lineage,
    verify_shadow_prediction_integrity,
)
from fip_api.models import (
    ModelLifecycleEvent,
    RegisteredModel,
    ShadowModelEvaluationReport,
    ShadowModelPrediction,
    Transaction,
    TransactionFeatureSnapshot,
    TransactionRuleAssessment,
    User,
)
from fip_api.rules import RISK_BAND_VERSION, RULESET_VERSION
from fip_api.schemas.model_evaluation import (
    ShadowEvaluationCreate,
    ShadowEvaluationReportResponse,
)
from fip_api.scoring.service import verify_rule_assessment_integrity

SHADOW_EVALUATION_SCHEMA_VERSION = "shadow-model-evaluation-v1.0.0"
MINIMUM_WINDOW_PREDICTIONS = 20
MAXIMUM_WINDOW_PREDICTIONS = 10_000


class EvaluationDataInsufficient(ValueError):
    pass


class EvaluationConflict(ValueError):
    pass


@dataclass(frozen=True)
class EvaluationRow:
    prediction: ShadowModelPrediction
    transaction: Transaction
    snapshot: TransactionFeatureSnapshot
    assessment: TransactionRuleAssessment
    authorization_event: ModelLifecycleEvent


def create_shadow_evaluation(
    db: Session,
    *,
    model_id: str,
    payload: ShadowEvaluationCreate,
    actor: User,
) -> tuple[ShadowModelEvaluationReport, bool]:
    model = db.get(RegisteredModel, model_id)
    if model is None:
        raise ModelNotFound("Model version not found.")
    if not verify_model_lineage(db, model):
        raise GovernanceViolation("Model lifecycle integrity verification failed.")

    baseline_start = _as_utc(payload.baseline_window_start)
    baseline_end = _as_utc(payload.baseline_window_end)
    evaluation_start = _as_utc(payload.evaluation_window_start)
    evaluation_end = _as_utc(payload.evaluation_window_end)
    existing = db.scalar(
        select(ShadowModelEvaluationReport).where(
            ShadowModelEvaluationReport.model_id == model.id,
            ShadowModelEvaluationReport.baseline_window_start == baseline_start,
            ShadowModelEvaluationReport.baseline_window_end == baseline_end,
            ShadowModelEvaluationReport.evaluation_window_start == evaluation_start,
            ShadowModelEvaluationReport.evaluation_window_end == evaluation_end,
        )
    )
    if existing is not None:
        if not verify_evaluation_report_integrity(db, existing):
            raise GovernanceViolation("Existing shadow evaluation integrity verification failed.")
        return existing, False

    baseline_rows = _load_window_rows(
        db,
        model_id=model.id,
        window_start=baseline_start,
        window_end=baseline_end,
    )
    evaluation_rows = _load_window_rows(
        db,
        model_id=model.id,
        window_start=evaluation_start,
        window_end=evaluation_end,
    )
    _require_window_size("baseline", baseline_rows)
    _require_window_size("evaluation", evaluation_rows)
    _verify_rows(db, model, baseline_rows)
    _verify_rows(db, model, evaluation_rows)

    metrics = build_evaluation_metrics(
        _observations(baseline_rows),
        _observations(evaluation_rows),
        ruleset_version=RULESET_VERSION,
        risk_band_version=RISK_BAND_VERSION,
    )
    input_lineage_checksum = canonical_json_checksum(
        _input_lineage_facts(baseline_rows, evaluation_rows)
    )
    created_at = datetime.now(UTC)
    report_checksum = canonical_json_checksum(
        _report_facts(
            model_registration_checksum=model.registration_checksum,
            requested_by=actor.username,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            evaluation_start=evaluation_start,
            evaluation_end=evaluation_end,
            baseline_count=len(baseline_rows),
            evaluation_count=len(evaluation_rows),
            metrics=metrics,
            input_lineage_checksum=input_lineage_checksum,
            created_at=created_at,
        )
    )
    report = ShadowModelEvaluationReport(
        model_id=model.id,
        requested_by_id=actor.id,
        report_schema_version=SHADOW_EVALUATION_SCHEMA_VERSION,
        baseline_window_start=baseline_start,
        baseline_window_end=baseline_end,
        evaluation_window_start=evaluation_start,
        evaluation_window_end=evaluation_end,
        baseline_prediction_count=len(baseline_rows),
        evaluation_prediction_count=len(evaluation_rows),
        metrics=metrics,
        input_lineage_checksum=input_lineage_checksum,
        report_checksum=report_checksum,
        created_at=created_at,
    )
    db.add(report)
    db.flush()
    return report, True


def list_shadow_evaluations(
    db: Session,
    model_id: str,
) -> list[ShadowModelEvaluationReport]:
    if db.get(RegisteredModel, model_id) is None:
        raise ModelNotFound("Model version not found.")
    return list(
        db.scalars(
            select(ShadowModelEvaluationReport)
            .where(ShadowModelEvaluationReport.model_id == model_id)
            .order_by(
                ShadowModelEvaluationReport.evaluation_window_start.desc(),
                ShadowModelEvaluationReport.created_at.desc(),
            )
        ).all()
    )


def build_evaluation_response(
    db: Session,
    report: ShadowModelEvaluationReport,
) -> ShadowEvaluationReportResponse:
    model = db.get(RegisteredModel, report.model_id)
    actor = db.get(User, report.requested_by_id)
    if model is None or actor is None:
        raise GovernanceViolation("Shadow evaluation references missing lineage records.")
    return ShadowEvaluationReportResponse(
        id=report.id,
        model_id=model.id,
        model_key=model.model_key,
        model_version=model.version,
        report_schema_version=report.report_schema_version,
        baseline_window_start=report.baseline_window_start,
        baseline_window_end=report.baseline_window_end,
        evaluation_window_start=report.evaluation_window_start,
        evaluation_window_end=report.evaluation_window_end,
        baseline_prediction_count=report.baseline_prediction_count,
        evaluation_prediction_count=report.evaluation_prediction_count,
        metrics=report.metrics,
        input_lineage_checksum=report.input_lineage_checksum,
        report_checksum=report.report_checksum,
        requested_by=actor.username,
        integrity_verified=verify_evaluation_report_integrity(db, report),
        created_at=report.created_at,
    )


def verify_evaluation_report_integrity(
    db: Session,
    report: ShadowModelEvaluationReport,
) -> bool:
    model = db.get(RegisteredModel, report.model_id)
    actor = db.get(User, report.requested_by_id)
    if model is None or actor is None or not verify_model_lineage(db, model):
        return False
    expected_report_checksum = canonical_json_checksum(
        _report_facts(
            model_registration_checksum=model.registration_checksum,
            requested_by=actor.username,
            baseline_start=report.baseline_window_start,
            baseline_end=report.baseline_window_end,
            evaluation_start=report.evaluation_window_start,
            evaluation_end=report.evaluation_window_end,
            baseline_count=report.baseline_prediction_count,
            evaluation_count=report.evaluation_prediction_count,
            metrics=report.metrics,
            input_lineage_checksum=report.input_lineage_checksum,
            created_at=report.created_at,
        )
    )
    if expected_report_checksum != report.report_checksum:
        return False
    try:
        baseline_rows = _load_window_rows(
            db,
            model_id=model.id,
            window_start=report.baseline_window_start,
            window_end=report.baseline_window_end,
            created_before=report.created_at,
        )
        evaluation_rows = _load_window_rows(
            db,
            model_id=model.id,
            window_start=report.evaluation_window_start,
            window_end=report.evaluation_window_end,
            created_before=report.created_at,
        )
        if (
            len(baseline_rows) != report.baseline_prediction_count
            or len(evaluation_rows) != report.evaluation_prediction_count
        ):
            return False
        _verify_rows(db, model, baseline_rows)
        _verify_rows(db, model, evaluation_rows)
    except (EvaluationConflict, GovernanceViolation):
        return False
    expected_lineage = canonical_json_checksum(_input_lineage_facts(baseline_rows, evaluation_rows))
    return expected_lineage == report.input_lineage_checksum


def _load_window_rows(
    db: Session,
    *,
    model_id: str,
    window_start: datetime,
    window_end: datetime,
    created_before: datetime | None = None,
) -> list[EvaluationRow]:
    statement = (
        select(
            ShadowModelPrediction,
            Transaction,
            TransactionFeatureSnapshot,
            TransactionRuleAssessment,
            ModelLifecycleEvent,
        )
        .join(Transaction, ShadowModelPrediction.transaction_id == Transaction.id)
        .join(
            TransactionFeatureSnapshot,
            ShadowModelPrediction.feature_snapshot_id == TransactionFeatureSnapshot.id,
        )
        .join(
            TransactionRuleAssessment,
            TransactionRuleAssessment.feature_snapshot_id == TransactionFeatureSnapshot.id,
        )
        .join(
            ModelLifecycleEvent,
            ShadowModelPrediction.authorization_event_id == ModelLifecycleEvent.id,
        )
        .where(
            ShadowModelPrediction.model_id == model_id,
            Transaction.occurred_at >= _as_utc(window_start),
            Transaction.occurred_at < _as_utc(window_end),
            TransactionRuleAssessment.ruleset_version == RULESET_VERSION,
            TransactionRuleAssessment.risk_band_version == RISK_BAND_VERSION,
        )
        .order_by(Transaction.occurred_at, Transaction.external_transaction_id)
        .limit(MAXIMUM_WINDOW_PREDICTIONS + 1)
    )
    if created_before is not None:
        statement = statement.where(ShadowModelPrediction.created_at <= created_before)
    rows = db.execute(statement).all()
    if len(rows) > MAXIMUM_WINDOW_PREDICTIONS:
        raise EvaluationConflict(
            f"A shadow evaluation window cannot exceed {MAXIMUM_WINDOW_PREDICTIONS} predictions."
        )
    return [
        EvaluationRow(
            prediction=row[0],
            transaction=row[1],
            snapshot=row[2],
            assessment=row[3],
            authorization_event=row[4],
        )
        for row in rows
    ]


def _require_window_size(name: str, rows: list[EvaluationRow]) -> None:
    if len(rows) < MINIMUM_WINDOW_PREDICTIONS:
        raise EvaluationDataInsufficient(
            f"The {name} window requires at least "
            f"{MINIMUM_WINDOW_PREDICTIONS} verified predictions."
        )


def _verify_rows(
    db: Session,
    model: RegisteredModel,
    rows: list[EvaluationRow],
) -> None:
    for row in rows:
        if row.prediction.model_id != model.id:
            raise GovernanceViolation("Shadow evaluation contains a prediction for another model.")
        if row.authorization_event.id != row.prediction.authorization_event_id:
            raise GovernanceViolation("Shadow evaluation authorization lineage is inconsistent.")
        if not verify_shadow_prediction_integrity(db, row.prediction):
            raise GovernanceViolation("Shadow prediction integrity verification failed.")
        if not verify_rule_assessment_integrity(
            row.snapshot,
            row.assessment,
            row.transaction,
        ):
            raise GovernanceViolation("Rule assessment integrity verification failed.")


def _observations(rows: list[EvaluationRow]) -> list[EvaluationObservation]:
    return [
        EvaluationObservation(
            score=row.prediction.score,
            threshold_exceeded=row.prediction.would_exceed_threshold,
            runtime_milliseconds=row.prediction.runtime_milliseconds,
            rule_score=row.assessment.rule_score,
            rule_risk_level=row.assessment.risk_level,
            feature_values=row.snapshot.feature_values,
        )
        for row in rows
    ]


def _input_lineage_facts(
    baseline_rows: list[EvaluationRow],
    evaluation_rows: list[EvaluationRow],
) -> dict[str, object]:
    return {
        "baseline": [_lineage_row(row) for row in baseline_rows],
        "evaluation": [_lineage_row(row) for row in evaluation_rows],
    }


def _lineage_row(row: EvaluationRow) -> dict[str, object]:
    return {
        "external_transaction_id": row.transaction.external_transaction_id,
        "occurred_at": _timestamp_text(row.transaction.occurred_at),
        "prediction_checksum": row.prediction.prediction_checksum,
        "feature_snapshot_checksum": row.snapshot.snapshot_checksum,
        "rule_assessment_checksum": row.assessment.assessment_checksum,
        "authorization_event_checksum": row.authorization_event.event_checksum,
    }


def _report_facts(
    *,
    model_registration_checksum: str,
    requested_by: str,
    baseline_start: datetime,
    baseline_end: datetime,
    evaluation_start: datetime,
    evaluation_end: datetime,
    baseline_count: int,
    evaluation_count: int,
    metrics: dict[str, object],
    input_lineage_checksum: str,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "report_schema_version": SHADOW_EVALUATION_SCHEMA_VERSION,
        "model_registration_checksum": model_registration_checksum,
        "requested_by": requested_by,
        "baseline_window_start": _timestamp_text(baseline_start),
        "baseline_window_end": _timestamp_text(baseline_end),
        "evaluation_window_start": _timestamp_text(evaluation_start),
        "evaluation_window_end": _timestamp_text(evaluation_end),
        "baseline_prediction_count": baseline_count,
        "evaluation_prediction_count": evaluation_count,
        "metrics": metrics,
        "input_lineage_checksum": input_lineage_checksum,
        "created_at": _timestamp_text(created_at),
        "monitoring_only": True,
        "affects_operational_score": False,
        "triggers_automatic_action": False,
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timestamp_text(value: datetime) -> str:
    return _as_utc(value).isoformat()
