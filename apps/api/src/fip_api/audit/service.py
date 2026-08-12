from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.cases import verify_case_integrity
from fip_api.explainability import verify_case_brief_integrity
from fip_api.hybrid_scoring import verify_hybrid_assessment_integrity
from fip_api.model_evaluation import verify_evaluation_report_integrity
from fip_api.model_registry import verify_model_lineage, verify_shadow_prediction_integrity
from fip_api.models import (
    AnalystCase,
    CaseBrief,
    CaseEvent,
    HybridRiskAssessment,
    ModelLifecycleEvent,
    OperationalDatasetSnapshot,
    OperationalTrainingRun,
    OperationalTrainingRunEvent,
    RegisteredModel,
    ScoringRuntimeObservation,
    ShadowModelEvaluationReport,
    ShadowModelPrediction,
    Transaction,
    User,
)
from fip_api.schemas.audit import (
    AuditCategory,
    AuditIntegrityFilter,
    AuditLedgerEntryResponse,
    AuditLedgerResponse,
    AuditLedgerSummaryResponse,
)
from fip_api.scoring import verify_scoring_runtime_observation
from fip_api.training_datasets import verify_dataset_integrity
from fip_api.training_operations import (
    get_training_artifact_store,
    verify_training_run_integrity,
)

AUDIT_LEDGER_SCHEMA_VERSION = "audit-ledger-v1.0.0"


def build_audit_ledger(
    db: Session,
    *,
    category: AuditCategory | None = None,
    integrity: AuditIntegrityFilter = "all",
    query: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> AuditLedgerResponse:
    entries = _collect_entries(db)
    entries.sort(key=lambda entry: (_timestamp(entry.occurred_at), entry.id), reverse=True)

    category_counts = Counter(entry.category for entry in entries)
    verified_records = sum(entry.integrity_verified for entry in entries)
    summary = AuditLedgerSummaryResponse(
        total_records=len(entries),
        verified_records=verified_records,
        failed_records=len(entries) - verified_records,
        chained_records=sum(
            entry.previous_checksum is not None or entry.sequence_number == 1 for entry in entries
        ),
        category_counts=dict(sorted(category_counts.items())),
    )

    filtered = entries
    if category is not None:
        filtered = [entry for entry in filtered if entry.category == category]
    if integrity != "all":
        expected = integrity == "verified"
        filtered = [entry for entry in filtered if entry.integrity_verified is expected]
    normalized_query = query.strip() if query is not None else ""
    if normalized_query:
        needle = normalized_query.casefold()
        filtered = [entry for entry in filtered if needle in _search_text(entry)]

    total = len(filtered)
    start = (page - 1) * page_size
    return AuditLedgerResponse(
        schema_version=AUDIT_LEDGER_SCHEMA_VERSION,
        entries=filtered[start : start + page_size],
        summary=summary,
        total=total,
        page=page,
        page_size=page_size,
        page_count=ceil(total / page_size) if total else 0,
        category=category,
        integrity=integrity,
        query=normalized_query or None,
    )


def _collect_entries(db: Session) -> list[AuditLedgerEntryResponse]:
    users = {user.id: user.username for user in db.scalars(select(User)).all()}
    transactions = {
        transaction.id: transaction for transaction in db.scalars(select(Transaction)).all()
    }
    cases = {case.id: case for case in db.scalars(select(AnalystCase)).all()}
    cases_by_transaction = {case.transaction_id: case for case in cases.values()}
    models = {model.id: model for model in db.scalars(select(RegisteredModel)).all()}

    case_integrity = {case.id: verify_case_integrity(db, case) for case in cases.values()}
    model_integrity = {model.id: verify_model_lineage(db, model) for model in models.values()}

    entries: list[AuditLedgerEntryResponse] = []
    entries.extend(_case_entries(db, cases, case_integrity))
    entries.extend(_model_lifecycle_entries(db, models, model_integrity, users))
    entries.extend(
        _shadow_prediction_entries(
            db,
            models,
            transactions,
            cases_by_transaction,
        )
    )
    entries.extend(_scoring_entries(db, transactions, cases_by_transaction))
    entries.extend(_brief_entries(db, cases, users))
    entries.extend(
        _hybrid_entries(
            db,
            transactions,
            cases_by_transaction,
            users,
        )
    )
    entries.extend(_dataset_entries(db, users))
    entries.extend(_training_entries(db))
    entries.extend(_evaluation_entries(db, models, users))
    return entries


def _case_entries(
    db: Session,
    cases: dict[str, AnalystCase],
    integrity: dict[str, bool],
) -> list[AuditLedgerEntryResponse]:
    entries: list[AuditLedgerEntryResponse] = []
    events = db.scalars(select(CaseEvent)).all()
    for event in events:
        case = cases.get(event.case_id)
        if case is None:
            continue
        action, detail = _case_event_copy(event)
        entries.append(
            AuditLedgerEntryResponse(
                id=f"case-event:{event.id}",
                category="case",
                action=action,
                subject_id=case.id,
                subject_label=case.display_id,
                actor_username=event.actor_username,
                detail=detail,
                sequence_number=event.sequence_number,
                occurred_at=_utc_datetime(event.created_at),
                checksum=event.event_checksum,
                previous_checksum=event.previous_event_checksum,
                integrity_verified=integrity.get(case.id, False),
                href=f"/cases/{case.id}#audit-ledger",
                metadata={"event_type": event.event_type},
            )
        )
    return entries


def _model_lifecycle_entries(
    db: Session,
    models: dict[str, RegisteredModel],
    integrity: dict[str, bool],
    users: dict[str, str],
) -> list[AuditLedgerEntryResponse]:
    entries: list[AuditLedgerEntryResponse] = []
    events = db.scalars(select(ModelLifecycleEvent)).all()
    for event in events:
        model = models.get(event.model_id)
        if model is None:
            continue
        transition = (
            f"{event.from_status} to {event.to_status}"
            if event.from_status is not None
            else f"registered as {event.to_status}"
        )
        entries.append(
            AuditLedgerEntryResponse(
                id=f"model-event:{event.id}",
                category="model",
                action="Model lifecycle recorded",
                subject_id=model.id,
                subject_label=f"{model.model_key} / {model.version}",
                actor_username=users.get(event.actor_user_id, "unknown actor"),
                detail=f"Lifecycle {transition}. {event.reason}",
                sequence_number=event.sequence_number,
                occurred_at=_utc_datetime(event.created_at),
                checksum=event.event_checksum,
                previous_checksum=event.previous_event_checksum,
                integrity_verified=integrity.get(model.id, False),
                href="/evaluation#model-evidence",
                metadata={
                    "from_status": event.from_status,
                    "to_status": event.to_status,
                },
            )
        )
    return entries


def _shadow_prediction_entries(
    db: Session,
    models: dict[str, RegisteredModel],
    transactions: dict[str, Transaction],
    cases_by_transaction: dict[str, AnalystCase],
) -> list[AuditLedgerEntryResponse]:
    entries: list[AuditLedgerEntryResponse] = []
    predictions = db.scalars(select(ShadowModelPrediction)).all()
    for prediction in predictions:
        model = models.get(prediction.model_id)
        transaction = transactions.get(prediction.transaction_id)
        case = cases_by_transaction.get(prediction.transaction_id)
        label = f"{model.model_key} / {model.version}" if model is not None else prediction.model_id
        transaction_label = (
            transaction.external_transaction_id
            if transaction is not None
            else prediction.transaction_id
        )
        entries.append(
            AuditLedgerEntryResponse(
                id=f"shadow-prediction:{prediction.id}",
                category="model",
                action="Shadow prediction recorded",
                subject_id=prediction.id,
                subject_label=f"{label} · {transaction_label}",
                actor_username="fip-shadow-runtime",
                detail=(
                    f"Decision-isolated score {prediction.score} against threshold "
                    f"{prediction.threshold}; runtime {prediction.runtime_milliseconds} ms."
                ),
                sequence_number=None,
                occurred_at=_utc_datetime(prediction.created_at),
                checksum=prediction.prediction_checksum,
                previous_checksum=None,
                integrity_verified=verify_shadow_prediction_integrity(db, prediction),
                href=f"/cases/{case.id}" if case is not None else "/evaluation#model-evidence",
                metadata={
                    "model_id": prediction.model_id,
                    "transaction_id": prediction.transaction_id,
                    "would_exceed_threshold": prediction.would_exceed_threshold,
                },
            )
        )
    return entries


def _scoring_entries(
    db: Session,
    transactions: dict[str, Transaction],
    cases_by_transaction: dict[str, AnalystCase],
) -> list[AuditLedgerEntryResponse]:
    entries: list[AuditLedgerEntryResponse] = []
    observations = db.scalars(select(ScoringRuntimeObservation)).all()
    for observation in observations:
        transaction = transactions.get(observation.transaction_id)
        case = cases_by_transaction.get(observation.transaction_id)
        subject_label = (
            transaction.external_transaction_id
            if transaction is not None
            else observation.transaction_id
        )
        entries.append(
            AuditLedgerEntryResponse(
                id=f"scoring-observation:{observation.id}",
                category="scoring",
                action="Rules assessment observed",
                subject_id=observation.transaction_id,
                subject_label=subject_label,
                actor_username="fip-scoring",
                detail=(
                    f"Verified scoring runtime observation: {observation.runtime_milliseconds} ms."
                ),
                sequence_number=None,
                occurred_at=_utc_datetime(observation.created_at),
                checksum=observation.observation_checksum,
                previous_checksum=None,
                integrity_verified=verify_scoring_runtime_observation(db, observation),
                href=f"/cases/{case.id}" if case is not None else "/",
                metadata={
                    "rule_assessment_id": observation.rule_assessment_id,
                    "runtime_milliseconds": observation.runtime_milliseconds,
                },
            )
        )
    return entries


def _brief_entries(
    db: Session,
    cases: dict[str, AnalystCase],
    users: dict[str, str],
) -> list[AuditLedgerEntryResponse]:
    entries: list[AuditLedgerEntryResponse] = []
    briefs = db.scalars(select(CaseBrief)).all()
    for brief in briefs:
        case = cases.get(brief.case_id)
        case_label = case.display_id if case is not None else brief.case_id
        entries.append(
            AuditLedgerEntryResponse(
                id=f"case-brief:{brief.id}",
                category="explanation",
                action="Grounded case brief sealed",
                subject_id=brief.id,
                subject_label=case_label,
                actor_username=users.get(brief.requested_by_id, "unknown actor"),
                detail=(
                    f"{brief.generation_mode.replace('_', ' ')} output sealed after "
                    f"{brief.generation_milliseconds} ms."
                ),
                sequence_number=None,
                occurred_at=_utc_datetime(brief.created_at),
                checksum=brief.explanation_checksum,
                previous_checksum=None,
                integrity_verified=verify_case_brief_integrity(db, brief),
                href=f"/cases/{brief.case_id}#case-brief",
                metadata={
                    "generation_mode": brief.generation_mode,
                    "prompt_version": brief.prompt_version,
                },
            )
        )
    return entries


def _hybrid_entries(
    db: Session,
    transactions: dict[str, Transaction],
    cases_by_transaction: dict[str, AnalystCase],
    users: dict[str, str],
) -> list[AuditLedgerEntryResponse]:
    entries: list[AuditLedgerEntryResponse] = []
    assessments = db.scalars(select(HybridRiskAssessment)).all()
    for assessment in assessments:
        transaction = transactions.get(assessment.transaction_id)
        case = cases_by_transaction.get(assessment.transaction_id)
        subject_label = (
            transaction.external_transaction_id
            if transaction is not None
            else assessment.transaction_id
        )
        entries.append(
            AuditLedgerEntryResponse(
                id=f"hybrid-assessment:{assessment.id}",
                category="hybrid",
                action="Hybrid evidence assessment sealed",
                subject_id=assessment.id,
                subject_label=subject_label,
                actor_username=users.get(assessment.created_by_id, "unknown actor"),
                detail=(
                    f"Decision-support score {assessment.combined_score}; "
                    f"{assessment.risk_level} risk under {assessment.policy_version}."
                ),
                sequence_number=None,
                occurred_at=_utc_datetime(assessment.created_at),
                checksum=assessment.assessment_checksum,
                previous_checksum=None,
                integrity_verified=verify_hybrid_assessment_integrity(db, assessment),
                href=f"/cases/{case.id}" if case is not None else "/evaluation#model-evidence",
                metadata={
                    "policy_version": assessment.policy_version,
                    "risk_level": assessment.risk_level,
                },
            )
        )
    return entries


def _dataset_entries(
    db: Session,
    users: dict[str, str],
) -> list[AuditLedgerEntryResponse]:
    entries: list[AuditLedgerEntryResponse] = []
    datasets = db.scalars(select(OperationalDatasetSnapshot)).all()
    for dataset in datasets:
        entries.append(
            AuditLedgerEntryResponse(
                id=f"dataset:{dataset.id}",
                category="dataset",
                action="Operational dataset snapshot sealed",
                subject_id=dataset.id,
                subject_label=dataset.display_id,
                actor_username=users.get(dataset.created_by_id, "unknown actor"),
                detail=(
                    f"{dataset.row_count} governed rows; readiness {dataset.readiness_status}."
                ),
                sequence_number=None,
                occurred_at=_utc_datetime(dataset.created_at),
                checksum=dataset.dataset_checksum,
                previous_checksum=None,
                integrity_verified=verify_dataset_integrity(db, dataset),
                href="/ml/datasets#dataset-archive",
                metadata={
                    "readiness_status": dataset.readiness_status,
                    "row_count": dataset.row_count,
                },
            )
        )
    return entries


def _evaluation_entries(
    db: Session,
    models: dict[str, RegisteredModel],
    users: dict[str, str],
) -> list[AuditLedgerEntryResponse]:
    entries: list[AuditLedgerEntryResponse] = []
    reports = db.scalars(select(ShadowModelEvaluationReport)).all()
    for report in reports:
        model = models.get(report.model_id)
        subject_label = (
            f"{model.model_key} / {model.version}" if model is not None else report.model_id
        )
        entries.append(
            AuditLedgerEntryResponse(
                id=f"evaluation-report:{report.id}",
                category="evaluation",
                action="Shadow evaluation report sealed",
                subject_id=report.id,
                subject_label=subject_label,
                actor_username=users.get(report.requested_by_id, "unknown actor"),
                detail=(
                    f"Compared {report.baseline_prediction_count} baseline and "
                    f"{report.evaluation_prediction_count} evaluation predictions."
                ),
                sequence_number=None,
                occurred_at=_utc_datetime(report.created_at),
                checksum=report.report_checksum,
                previous_checksum=None,
                integrity_verified=verify_evaluation_report_integrity(db, report),
                href="/evaluation#model-evaluation-archive",
                metadata={"report_schema_version": report.report_schema_version},
            )
        )
    return entries


def _training_entries(
    db: Session,
) -> list[AuditLedgerEntryResponse]:
    entries: list[AuditLedgerEntryResponse] = []
    store = get_training_artifact_store()
    runs = {run.id: run for run in db.scalars(select(OperationalTrainingRun)).all()}
    integrity = {
        run.id: verify_training_run_integrity(db, run, store=store) for run in runs.values()
    }
    events = db.scalars(select(OperationalTrainingRunEvent)).all()
    for event in events:
        run = runs.get(event.training_run_id)
        if run is None:
            continue
        entries.append(
            AuditLedgerEntryResponse(
                id=f"training-run-event:{event.id}",
                category="training",
                action=_training_event_action(event.to_status),
                subject_id=run.id,
                subject_label=f"{run.display_id} / {run.candidate_version}",
                actor_username=event.actor_username,
                detail=event.detail,
                sequence_number=event.sequence_number,
                occurred_at=_utc_datetime(event.created_at),
                checksum=event.event_checksum,
                previous_checksum=event.previous_event_checksum,
                integrity_verified=integrity[run.id],
                href="/ml/training",
                metadata={
                    "status": event.to_status,
                    "dataset_checksum": run.dataset_checksum,
                    "configuration_checksum": run.configuration_checksum,
                    "bundle_checksum": run.bundle_checksum or "pending",
                },
            )
        )
    return entries


def _training_event_action(status: str) -> str:
    return {
        "queued": "Candidate training queued",
        "running": "Candidate training started",
        "succeeded": "Candidate bundle sealed",
        "failed": "Candidate training failed",
    }.get(status, "Candidate training event recorded")


def _case_event_copy(event: CaseEvent) -> tuple[str, str]:
    copy = {
        "opened": ("Case opened", "Deterministic risk evidence opened a governed case."),
        "review_started": ("Review started", "An analyst placed the case under review."),
        "note_added": ("Case note retained", "An analyst note was appended to the case record."),
        "classified": ("Case classified", "A final human classification was sealed."),
        "outcome_reviewed": (
            "Outcome independently reviewed",
            "An evaluator recorded the outcome's dataset eligibility decision.",
        ),
        "brief_generated": (
            "Case brief linked",
            "A grounded explanation was linked into the case event chain.",
        ),
    }
    return copy.get(
        event.event_type,
        ("Case event recorded", "A governed case event was appended."),
    )


def _search_text(entry: AuditLedgerEntryResponse) -> str:
    return " ".join(
        (
            entry.category,
            entry.action,
            entry.subject_id,
            entry.subject_label,
            entry.actor_username,
            entry.detail,
            entry.checksum,
        )
    ).casefold()


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> float:
    return _utc_datetime(value).timestamp()
