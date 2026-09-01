from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from fip_api.core.checksums import canonical_json_checksum
from fip_api.core.config import get_settings
from fip_api.core.object_store import S3ObjectStore
from fip_api.models import (
    DatasetReadinessStatus,
    OperationalDatasetSnapshot,
    OperationalTrainingRun,
    OperationalTrainingRunEvent,
    RegisteredModel,
    TrainingRunStatus,
    User,
)
from fip_api.operational_ml import PIPELINE_VERSION
from fip_api.schemas.training_run import (
    TrainingCandidateResponse,
    TrainingRunCreate,
    TrainingRunEventResponse,
    TrainingRunResponse,
)
from fip_api.training_datasets import DatasetNotFound, get_dataset, verify_dataset_integrity
from fip_api.training_operations.artifacts import (
    S3TrainingArtifactStore,
    TrainingArtifactStore,
    TrainingBundleError,
    TrainingBundleInspection,
)

SUPERVISED_MODEL_KEY = "canonical-fraud-classifier"
ANOMALY_MODEL_KEY = "canonical-transaction-anomaly"
CandidateKind = Literal["supervised", "anomaly"]
CANDIDATE_KINDS: tuple[CandidateKind, ...] = ("supervised", "anomaly")


class TrainingRunNotFound(LookupError):
    pass


class TrainingRunConflict(ValueError):
    pass


class TrainingRunStateError(ValueError):
    pass


def get_training_artifact_store() -> TrainingArtifactStore:
    settings = get_settings()
    if settings.artifact_store == "s3":
        return S3TrainingArtifactStore(
            settings.training_artifact_root,
            max_artifact_bytes=settings.training_artifact_max_bytes,
            object_store=S3ObjectStore.from_settings(settings),
        )
    return TrainingArtifactStore(
        settings.training_artifact_root,
        max_artifact_bytes=settings.training_artifact_max_bytes,
    )


def request_training_run(
    db: Session,
    *,
    payload: TrainingRunCreate,
    actor: User,
) -> tuple[OperationalTrainingRun, bool]:
    try:
        dataset = get_dataset(db, payload.dataset_id)
    except DatasetNotFound as exc:
        raise TrainingRunNotFound(str(exc)) from exc
    if dataset.readiness_status != DatasetReadinessStatus.READY.value:
        raise TrainingRunConflict("Only a training-ready operational dataset may be queued.")
    if not verify_dataset_integrity(db, dataset):
        raise TrainingRunConflict("The selected operational dataset failed integrity verification.")

    maximum_fpr = _quantized_fpr(payload.maximum_false_positive_rate)
    configuration_checksum = canonical_json_checksum(
        _configuration_facts(
            dataset=dataset,
            candidate_version=payload.candidate_version,
            seed=payload.seed,
            maximum_false_positive_rate=maximum_fpr,
        )
    )
    existing_configuration = db.scalar(
        select(OperationalTrainingRun).where(
            OperationalTrainingRun.configuration_checksum == configuration_checksum
        )
    )
    if existing_configuration is not None:
        return existing_configuration, False

    existing_version = db.scalar(
        select(OperationalTrainingRun).where(
            OperationalTrainingRun.candidate_version == payload.candidate_version
        )
    )
    if existing_version is not None:
        raise TrainingRunConflict(
            "The candidate version already belongs to a different training configuration."
        )
    registered = db.scalar(
        select(RegisteredModel.id).where(
            RegisteredModel.model_key.in_([SUPERVISED_MODEL_KEY, ANOMALY_MODEL_KEY]),
            RegisteredModel.version == payload.candidate_version,
        )
    )
    if registered is not None:
        raise TrainingRunConflict("The candidate version is already present in the model registry.")

    run_id = uuid4()
    created_at = datetime.now(UTC)
    run = OperationalTrainingRun(
        id=str(run_id),
        display_id=f"TRN-{run_id.hex[:10].upper()}",
        dataset_id=dataset.id,
        requested_by_id=actor.id,
        candidate_version=payload.candidate_version,
        seed=payload.seed,
        maximum_false_positive_rate=maximum_fpr,
        request_reason=payload.reason,
        pipeline_version=PIPELINE_VERSION,
        dataset_checksum=dataset.dataset_checksum,
        configuration_checksum=configuration_checksum,
        status=TrainingRunStatus.QUEUED.value,
        attempt_count=0,
        created_at=created_at,
    )
    db.add(run)
    db.flush()
    _append_event(
        db,
        run=run,
        from_status=None,
        to_status=TrainingRunStatus.QUEUED,
        detail="Administrator queued an offline candidate-training run.",
        actor_username=actor.username,
        created_at=created_at,
    )
    db.flush()
    return run, True


def list_training_runs(db: Session) -> list[OperationalTrainingRun]:
    return list(
        db.scalars(
            select(OperationalTrainingRun).order_by(
                OperationalTrainingRun.created_at.desc(),
                OperationalTrainingRun.id,
            )
        ).all()
    )


def get_training_run(db: Session, run_id: str) -> OperationalTrainingRun:
    run = db.scalar(
        select(OperationalTrainingRun).where(
            or_(
                OperationalTrainingRun.id == run_id,
                OperationalTrainingRun.display_id == run_id,
            )
        )
    )
    if run is None:
        raise TrainingRunNotFound("Operational training run not found.")
    return run


def retry_training_run(
    db: Session,
    *,
    run_id: str,
    actor: User,
) -> OperationalTrainingRun:
    run = db.scalar(
        select(OperationalTrainingRun)
        .where(
            or_(
                OperationalTrainingRun.id == run_id,
                OperationalTrainingRun.display_id == run_id,
            )
        )
        .with_for_update()
    )
    if run is None:
        raise TrainingRunNotFound("Operational training run not found.")
    if run.status != TrainingRunStatus.FAILED.value:
        raise TrainingRunConflict("Only a failed training run may be queued again.")
    dataset = db.get(OperationalDatasetSnapshot, run.dataset_id)
    if (
        dataset is None
        or dataset.readiness_status != DatasetReadinessStatus.READY.value
        or not verify_dataset_integrity(db, dataset)
    ):
        raise TrainingRunConflict(
            "The pinned operational dataset is not currently eligible for another attempt."
        )
    now = datetime.now(UTC)
    run.status = TrainingRunStatus.QUEUED.value
    run.worker_id = None
    run.started_at = None
    run.completed_at = None
    run.lease_expires_at = None
    run.error_code = None
    run.error_message = None
    _append_event(
        db,
        run=run,
        from_status=TrainingRunStatus.FAILED,
        to_status=TrainingRunStatus.QUEUED,
        detail="Administrator authorized another attempt for the same immutable configuration.",
        actor_username=actor.username,
        created_at=now,
    )
    db.flush()
    return run


def claim_next_training_run(
    db: Session,
    *,
    worker_id: str,
    lease_minutes: int,
) -> OperationalTrainingRun | None:
    now = datetime.now(UTC)
    expired = list(
        db.scalars(
            select(OperationalTrainingRun)
            .where(
                OperationalTrainingRun.status == TrainingRunStatus.RUNNING.value,
                OperationalTrainingRun.lease_expires_at < now,
            )
            .with_for_update(skip_locked=True)
        ).all()
    )
    for abandoned in expired:
        _transition_to_failed(
            db,
            run=abandoned,
            error_code="worker_lease_expired",
            error_message="The training worker lease expired before completion.",
            actor_username="training-worker",
            completed_at=now,
        )

    run = db.scalar(
        select(OperationalTrainingRun)
        .where(OperationalTrainingRun.status == TrainingRunStatus.QUEUED.value)
        .order_by(OperationalTrainingRun.created_at, OperationalTrainingRun.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if run is None:
        return None
    previous = TrainingRunStatus(run.status)
    run.status = TrainingRunStatus.RUNNING.value
    run.worker_id = worker_id[:120]
    run.attempt_count += 1
    run.started_at = now
    run.completed_at = None
    run.lease_expires_at = now + timedelta(minutes=lease_minutes)
    run.error_code = None
    run.error_message = None
    _append_event(
        db,
        run=run,
        from_status=previous,
        to_status=TrainingRunStatus.RUNNING,
        detail=f"Worker {run.worker_id} claimed the offline training run.",
        actor_username="training-worker",
        created_at=now,
    )
    db.flush()
    return run


def complete_training_run(
    db: Session,
    *,
    run_id: str,
    worker_id: str,
    inspection: TrainingBundleInspection,
) -> OperationalTrainingRun:
    run = db.scalar(
        select(OperationalTrainingRun).where(OperationalTrainingRun.id == run_id).with_for_update()
    )
    if run is None:
        raise TrainingRunNotFound("Operational training run not found.")
    _require_worker_ownership(run, worker_id)
    completed_at = datetime.now(UTC)
    run.status = TrainingRunStatus.SUCCEEDED.value
    run.bundle_key = inspection.bundle_key
    run.result_summary = inspection.summary
    run.evidence_checksum = inspection.evidence_checksum
    run.manifest_checksum = inspection.manifest_checksum
    run.bundle_checksum = inspection.bundle_checksum
    run.completed_at = completed_at
    run.lease_expires_at = None
    _append_event(
        db,
        run=run,
        from_status=TrainingRunStatus.RUNNING,
        to_status=TrainingRunStatus.SUCCEEDED,
        detail="Checksummed supervised and anomaly candidate bundles were sealed.",
        actor_username="training-worker",
        created_at=completed_at,
    )
    db.flush()
    return run


def fail_training_run(
    db: Session,
    *,
    run_id: str,
    worker_id: str,
    error_code: str,
    error_message: str,
) -> OperationalTrainingRun:
    run = db.scalar(
        select(OperationalTrainingRun).where(OperationalTrainingRun.id == run_id).with_for_update()
    )
    if run is None:
        raise TrainingRunNotFound("Operational training run not found.")
    _require_worker_ownership(run, worker_id)
    _transition_to_failed(
        db,
        run=run,
        error_code=error_code,
        error_message=error_message,
        actor_username="training-worker",
        completed_at=datetime.now(UTC),
    )
    db.flush()
    return run


def build_training_run_response(
    db: Session,
    run: OperationalTrainingRun,
    store: TrainingArtifactStore,
) -> TrainingRunResponse:
    dataset = db.get(OperationalDatasetSnapshot, run.dataset_id)
    requester = db.get(User, run.requested_by_id)
    if dataset is None or requester is None:
        raise TrainingRunStateError("The training run references missing lineage records.")
    events = _events(db, run.id)
    integrity_verified = verify_training_run_integrity(
        db,
        run,
        store=store,
        dataset=dataset,
        events=events,
    )
    candidates = (
        _candidate_responses(run)
        if integrity_verified and run.status == TrainingRunStatus.SUCCEEDED.value
        else None
    )
    return TrainingRunResponse(
        id=run.id,
        display_id=run.display_id,
        dataset_id=run.dataset_id,
        dataset_display_id=dataset.display_id,
        dataset_checksum=run.dataset_checksum,
        requested_by=requester.username,
        candidate_version=run.candidate_version,
        seed=run.seed,
        maximum_false_positive_rate=_decimal_text(run.maximum_false_positive_rate),
        reason=run.request_reason,
        pipeline_version=run.pipeline_version,
        configuration_checksum=run.configuration_checksum,
        status=TrainingRunStatus(run.status),
        attempt_count=run.attempt_count,
        candidates=candidates,
        evidence_checksum=run.evidence_checksum,
        manifest_checksum=run.manifest_checksum,
        bundle_checksum=run.bundle_checksum,
        error_code=run.error_code,
        error_message=run.error_message,
        integrity_verified=integrity_verified,
        events=[
            TrainingRunEventResponse(
                sequence_number=event.sequence_number,
                from_status=(
                    TrainingRunStatus(event.from_status) if event.from_status is not None else None
                ),
                to_status=TrainingRunStatus(event.to_status),
                detail=event.detail,
                actor_username=event.actor_username,
                previous_event_checksum=event.previous_event_checksum,
                event_checksum=event.event_checksum,
                created_at=event.created_at,
            )
            for event in events
        ],
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


def verify_training_run_integrity(
    db: Session,
    run: OperationalTrainingRun,
    *,
    store: TrainingArtifactStore,
    dataset: OperationalDatasetSnapshot | None = None,
    events: list[OperationalTrainingRunEvent] | None = None,
) -> bool:
    dataset = dataset or db.get(OperationalDatasetSnapshot, run.dataset_id)
    events = events if events is not None else _events(db, run.id)
    if dataset is None or dataset.dataset_checksum != run.dataset_checksum:
        return False
    expected_configuration = canonical_json_checksum(
        _configuration_facts(
            dataset=dataset,
            candidate_version=run.candidate_version,
            seed=run.seed,
            maximum_false_positive_rate=run.maximum_false_positive_rate,
        )
    )
    if (
        run.pipeline_version != PIPELINE_VERSION
        or run.configuration_checksum != expected_configuration
        or not _verify_event_chain(run, events)
        or not verify_dataset_integrity(db, dataset)
    ):
        return False
    status = TrainingRunStatus(run.status)
    if status is TrainingRunStatus.SUCCEEDED:
        if any(
            value is None
            for value in (
                run.bundle_key,
                run.result_summary,
                run.evidence_checksum,
                run.manifest_checksum,
                run.bundle_checksum,
                run.completed_at,
            )
        ):
            return False
        try:
            inspection = store.inspect(
                str(run.bundle_key),
                candidate_version=run.candidate_version,
                configuration_checksum=run.configuration_checksum,
                dataset_checksum=run.dataset_checksum,
                dataset_display_id=dataset.display_id,
                dataset_feature_set_version=dataset.feature_set_version,
                maximum_false_positive_rate=_decimal_text(run.maximum_false_positive_rate),
                seed=run.seed,
            )
        except TrainingBundleError:
            return False
        return (
            inspection.summary == run.result_summary
            and inspection.evidence_checksum == run.evidence_checksum
            and inspection.manifest_checksum == run.manifest_checksum
            and inspection.bundle_checksum == run.bundle_checksum
            and run.error_code is None
            and run.error_message is None
        )
    if status is TrainingRunStatus.FAILED:
        return (
            run.completed_at is not None
            and run.error_code is not None
            and run.error_message is not None
            and run.bundle_key is None
            and run.result_summary is None
        )
    return run.bundle_key is None and run.result_summary is None and run.completed_at is None


def inspect_completed_bundle(
    run: OperationalTrainingRun,
    *,
    dataset_display_id: str,
    dataset_feature_set_version: str,
    store: TrainingArtifactStore,
) -> TrainingBundleInspection:
    return store.inspect(
        run.id,
        candidate_version=run.candidate_version,
        configuration_checksum=run.configuration_checksum,
        dataset_checksum=run.dataset_checksum,
        dataset_display_id=dataset_display_id,
        dataset_feature_set_version=dataset_feature_set_version,
        maximum_false_positive_rate=_decimal_text(run.maximum_false_positive_rate),
        seed=run.seed,
    )


def _candidate_responses(
    run: OperationalTrainingRun,
) -> dict[CandidateKind, TrainingCandidateResponse]:
    assert run.result_summary is not None
    candidates: dict[CandidateKind, TrainingCandidateResponse] = {}
    for kind in CANDIDATE_KINDS:
        value = run.result_summary.get(kind)
        if not isinstance(value, dict):
            raise TrainingRunStateError("The candidate summary is malformed.")
        base = f"/api/v1/ml/training-runs/{run.id}/artifacts/{kind}"
        candidates[kind] = TrainingCandidateResponse.model_validate(
            {
                **value,
                "registration_download": f"{base}/registration",
                "model_card_download": f"{base}/model-card",
                "artifact_download": f"{base}/model",
            }
        )
    return candidates


def _transition_to_failed(
    db: Session,
    *,
    run: OperationalTrainingRun,
    error_code: str,
    error_message: str,
    actor_username: str,
    completed_at: datetime,
) -> None:
    previous = TrainingRunStatus(run.status)
    run.status = TrainingRunStatus.FAILED.value
    run.error_code = error_code[:120]
    run.error_message = error_message[:500]
    run.completed_at = completed_at
    run.lease_expires_at = None
    run.worker_id = None
    run.bundle_key = None
    run.result_summary = None
    run.evidence_checksum = None
    run.manifest_checksum = None
    run.bundle_checksum = None
    _append_event(
        db,
        run=run,
        from_status=previous,
        to_status=TrainingRunStatus.FAILED,
        detail=run.error_message,
        actor_username=actor_username,
        created_at=completed_at,
    )


def _require_worker_ownership(run: OperationalTrainingRun, worker_id: str) -> None:
    if run.status != TrainingRunStatus.RUNNING.value or run.worker_id != worker_id[:120]:
        raise TrainingRunStateError("The worker no longer owns this training run.")


def _events(db: Session, run_id: str) -> list[OperationalTrainingRunEvent]:
    return list(
        db.scalars(
            select(OperationalTrainingRunEvent)
            .where(OperationalTrainingRunEvent.training_run_id == run_id)
            .order_by(OperationalTrainingRunEvent.sequence_number)
        ).all()
    )


def _append_event(
    db: Session,
    *,
    run: OperationalTrainingRun,
    from_status: TrainingRunStatus | None,
    to_status: TrainingRunStatus,
    detail: str,
    actor_username: str,
    created_at: datetime,
) -> OperationalTrainingRunEvent:
    previous = db.scalar(
        select(OperationalTrainingRunEvent)
        .where(OperationalTrainingRunEvent.training_run_id == run.id)
        .order_by(OperationalTrainingRunEvent.sequence_number.desc())
        .limit(1)
    )
    sequence_number = previous.sequence_number + 1 if previous is not None else 1
    previous_checksum = previous.event_checksum if previous is not None else None
    facts = _event_facts(
        run_id=run.id,
        sequence_number=sequence_number,
        from_status=from_status.value if from_status is not None else None,
        to_status=to_status.value,
        detail=detail,
        actor_username=actor_username,
        previous_event_checksum=previous_checksum,
        created_at=created_at,
    )
    event = OperationalTrainingRunEvent(
        training_run_id=run.id,
        sequence_number=sequence_number,
        from_status=from_status.value if from_status is not None else None,
        to_status=to_status.value,
        detail=detail,
        actor_username=actor_username,
        previous_event_checksum=previous_checksum,
        event_checksum=canonical_json_checksum(facts),
        created_at=created_at,
    )
    db.add(event)
    return event


def _verify_event_chain(
    run: OperationalTrainingRun,
    events: list[OperationalTrainingRunEvent],
) -> bool:
    if not events or events[-1].to_status != run.status:
        return False
    previous_checksum: str | None = None
    previous_status: str | None = None
    allowed = {
        (None, TrainingRunStatus.QUEUED.value),
        (TrainingRunStatus.QUEUED.value, TrainingRunStatus.RUNNING.value),
        (TrainingRunStatus.RUNNING.value, TrainingRunStatus.SUCCEEDED.value),
        (TrainingRunStatus.RUNNING.value, TrainingRunStatus.FAILED.value),
        (TrainingRunStatus.FAILED.value, TrainingRunStatus.QUEUED.value),
    }
    for sequence, event in enumerate(events, start=1):
        if (
            event.sequence_number != sequence
            or event.previous_event_checksum != previous_checksum
            or event.from_status != previous_status
            or (event.from_status, event.to_status) not in allowed
            or event.event_checksum
            != canonical_json_checksum(
                _event_facts(
                    run_id=run.id,
                    sequence_number=event.sequence_number,
                    from_status=event.from_status,
                    to_status=event.to_status,
                    detail=event.detail,
                    actor_username=event.actor_username,
                    previous_event_checksum=event.previous_event_checksum,
                    created_at=event.created_at,
                )
            )
        ):
            return False
        previous_checksum = event.event_checksum
        previous_status = event.to_status
    return True


def _configuration_facts(
    *,
    dataset: OperationalDatasetSnapshot,
    candidate_version: str,
    seed: int,
    maximum_false_positive_rate: Decimal,
) -> dict[str, object]:
    return {
        "pipeline_version": PIPELINE_VERSION,
        "dataset_id": dataset.id,
        "dataset_display_id": dataset.display_id,
        "dataset_checksum": dataset.dataset_checksum,
        "candidate_version": candidate_version,
        "seed": seed,
        "maximum_false_positive_rate": _decimal_text(maximum_false_positive_rate),
        "candidate_only": True,
        "automatic_registration": False,
        "automatic_shadow_promotion": False,
    }


def _event_facts(
    *,
    run_id: str,
    sequence_number: int,
    from_status: str | None,
    to_status: str,
    detail: str,
    actor_username: str,
    previous_event_checksum: str | None,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "training_run_id": run_id,
        "sequence_number": sequence_number,
        "from_status": from_status,
        "to_status": to_status,
        "detail": detail,
        "actor_username": actor_username,
        "previous_event_checksum": previous_event_checksum,
        "created_at": _timestamp_text(created_at),
    }


def _quantized_fpr(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.000001"))


def _decimal_text(value: Decimal) -> str:
    return format(Decimal(value), "f").rstrip("0").rstrip(".")


def _timestamp_text(value: datetime) -> str:
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat()
