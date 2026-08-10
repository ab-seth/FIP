from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.core.checksums import canonical_json_checksum
from fip_api.features import FEATURE_SET_VERSION
from fip_api.models import (
    ModelKind,
    ModelLifecycleEvent,
    ModelLifecycleStatus,
    ModelPurpose,
    ModelRuntimeContract,
    RegisteredModel,
    User,
    UserRole,
)
from fip_api.schemas.model_registry import (
    ModelLifecycleEventResponse,
    ModelRegistrationCreate,
    RegisteredModelResponse,
)

INITIAL_EVENT_REASON = "Model version registered as a candidate."
ALLOWED_TRANSITIONS = {
    ModelLifecycleStatus.CANDIDATE: {
        ModelLifecycleStatus.SHADOW,
        ModelLifecycleStatus.REJECTED,
    },
    ModelLifecycleStatus.SHADOW: {
        ModelLifecycleStatus.RETIRED,
        ModelLifecycleStatus.REJECTED,
    },
    ModelLifecycleStatus.RETIRED: set(),
    ModelLifecycleStatus.REJECTED: set(),
}
SUPERVISED_METRICS = {
    "average_precision",
    "roc_auc",
    "brier_score",
    "recall",
    "false_positive_rate",
    "evaluated_row_count",
    "evaluated_positive_count",
}
ANOMALY_METRICS = {
    "training_row_count",
    "contamination",
    "score_reference_checksum",
}


class ModelNotFound(LookupError):
    pass


class ModelConflict(ValueError):
    pass


class GovernanceViolation(ValueError):
    pass


def register_model(
    db: Session,
    payload: ModelRegistrationCreate,
    actor: User,
) -> tuple[RegisteredModel, bool]:
    _validate_kind_contract(payload.kind, payload.runtime_contract)
    registration_checksum = canonical_json_checksum(_registration_facts(payload, actor.username))
    existing = db.scalar(
        select(RegisteredModel).where(
            RegisteredModel.model_key == payload.model_key,
            RegisteredModel.version == payload.version,
        )
    )
    if existing is not None:
        if existing.registration_checksum == registration_checksum:
            return existing, False
        raise ModelConflict("The model key and version already exist with different metadata.")

    model = RegisteredModel(
        model_key=payload.model_key,
        version=payload.version,
        kind=payload.kind.value,
        purpose=payload.purpose.value,
        runtime_contract=payload.runtime_contract.value,
        artifact_sha256=payload.artifact_sha256,
        feature_set_version=payload.feature_set_version,
        training_dataset_id=payload.training_dataset_id,
        training_dataset_checksum=payload.training_dataset_checksum,
        training_data_approved=payload.training_data_approved,
        operational_feature_compatible=payload.operational_feature_compatible,
        decision_threshold=payload.decision_threshold,
        evaluation_metrics=payload.evaluation_metrics,
        model_card_reference=payload.model_card_reference,
        model_card_checksum=payload.model_card_checksum,
        registered_by_id=actor.id,
        registration_checksum=registration_checksum,
    )
    db.add(model)
    db.flush()
    event = _new_lifecycle_event(
        model=model,
        sequence_number=1,
        from_status=None,
        to_status=ModelLifecycleStatus.CANDIDATE,
        reason=INITIAL_EVENT_REASON,
        actor=actor,
        previous_event_checksum=None,
    )
    db.add(event)
    db.flush()
    return model, True


def transition_model(
    db: Session,
    model_id: str,
    target_status: ModelLifecycleStatus,
    reason: str,
    actor: User,
) -> RegisteredModel:
    model = db.scalar(
        select(RegisteredModel).where(RegisteredModel.id == model_id).with_for_update()
    )
    if model is None:
        raise ModelNotFound("Model version not found.")
    if not verify_model_lineage(db, model):
        raise GovernanceViolation("Model lifecycle integrity verification failed.")
    current_event = _current_event(db, model.id)
    current_status = ModelLifecycleStatus(current_event.to_status)
    if target_status not in ALLOWED_TRANSITIONS[current_status]:
        raise GovernanceViolation(
            f"Model status cannot transition from {current_status.value} to {target_status.value}."
        )
    if target_status is ModelLifecycleStatus.SHADOW:
        _validate_shadow_admission(model, actor)

    event = _new_lifecycle_event(
        model=model,
        sequence_number=current_event.sequence_number + 1,
        from_status=current_status,
        to_status=target_status,
        reason=reason.strip(),
        actor=actor,
        previous_event_checksum=current_event.event_checksum,
    )
    db.add(event)
    db.flush()
    return model


def list_registered_models(db: Session) -> list[RegisteredModel]:
    return list(
        db.scalars(
            select(RegisteredModel).order_by(
                RegisteredModel.model_key,
                RegisteredModel.created_at.desc(),
            )
        ).all()
    )


def build_model_response(db: Session, model: RegisteredModel) -> RegisteredModelResponse:
    registered_by = db.get(User, model.registered_by_id)
    events = _events(db, model.id)
    actor_ids = {event.actor_user_id for event in events}
    actors = {
        actor.id: actor for actor in db.scalars(select(User).where(User.id.in_(actor_ids))).all()
    }
    lifecycle = [
        ModelLifecycleEventResponse(
            sequence_number=event.sequence_number,
            from_status=(
                ModelLifecycleStatus(event.from_status) if event.from_status is not None else None
            ),
            to_status=ModelLifecycleStatus(event.to_status),
            reason=event.reason,
            actor_username=actors[event.actor_user_id].username,
            previous_event_checksum=event.previous_event_checksum,
            event_checksum=event.event_checksum,
            created_at=event.created_at,
        )
        for event in events
        if event.actor_user_id in actors
    ]
    current_status = (
        ModelLifecycleStatus(events[-1].to_status) if events else ModelLifecycleStatus.CANDIDATE
    )
    return RegisteredModelResponse(
        id=model.id,
        model_key=model.model_key,
        version=model.version,
        kind=ModelKind(model.kind),
        purpose=ModelPurpose(model.purpose),
        runtime_contract=ModelRuntimeContract(model.runtime_contract),
        artifact_sha256=model.artifact_sha256,
        feature_set_version=model.feature_set_version,
        training_dataset_id=model.training_dataset_id,
        training_dataset_checksum=model.training_dataset_checksum,
        training_data_approved=model.training_data_approved,
        operational_feature_compatible=model.operational_feature_compatible,
        decision_threshold=(
            _decimal_text(model.decision_threshold)
            if model.decision_threshold is not None
            else None
        ),
        evaluation_metrics=model.evaluation_metrics,
        model_card_reference=model.model_card_reference,
        model_card_checksum=model.model_card_checksum,
        registered_by=registered_by.username if registered_by is not None else "unknown",
        registration_checksum=model.registration_checksum,
        current_status=current_status,
        lineage_verified=_verify_lineage(db, model, events),
        lifecycle=lifecycle,
        created_at=model.created_at,
    )


def current_lifecycle_event(db: Session, model_id: str) -> ModelLifecycleEvent:
    return _current_event(db, model_id)


def verify_model_lineage(db: Session, model: RegisteredModel) -> bool:
    return _verify_lineage(db, model, _events(db, model.id))


def _validate_kind_contract(
    kind: ModelKind,
    runtime_contract: ModelRuntimeContract,
) -> None:
    expected = {
        ModelKind.SUPERVISED: ModelRuntimeContract.BINARY_PROBABILITY,
        ModelKind.ANOMALY: ModelRuntimeContract.ANOMALY_SCORE,
    }[kind]
    if runtime_contract is not expected:
        raise GovernanceViolation(
            f"{kind.value} models require the {expected.value} runtime contract."
        )


def _validate_shadow_admission(model: RegisteredModel, actor: User) -> None:
    failures: list[str] = []
    if actor.role != UserRole.EVALUATOR.value:
        failures.append("an evaluator must authorize shadow admission")
    if actor.id == model.registered_by_id:
        failures.append("the evaluator must be independent from the registrant")
    if model.purpose != ModelPurpose.OPERATIONAL.value:
        failures.append("research-purpose models cannot enter shadow scoring")
    if not model.operational_feature_compatible:
        failures.append("operational feature compatibility has not been established")
    if not model.training_data_approved:
        failures.append("training data has not been approved")
    if model.feature_set_version != FEATURE_SET_VERSION:
        failures.append(f"feature set must be {FEATURE_SET_VERSION}")
    if model.decision_threshold is None:
        failures.append("a shadow comparison threshold is required")

    metrics = model.evaluation_metrics
    required_metrics = (
        SUPERVISED_METRICS if model.kind == ModelKind.SUPERVISED.value else ANOMALY_METRICS
    )
    missing_metrics = sorted(required_metrics.difference(metrics))
    if missing_metrics:
        failures.append(f"evaluation metrics are missing: {', '.join(missing_metrics)}")
    else:
        failures.extend(_invalid_metric_ranges(model))

    if failures:
        raise GovernanceViolation("Shadow admission blocked: " + "; ".join(failures) + ".")


def _invalid_metric_ranges(model: RegisteredModel) -> list[str]:
    metrics = model.evaluation_metrics
    failures: list[str] = []
    if model.kind == ModelKind.SUPERVISED.value:
        for key in (
            "average_precision",
            "roc_auc",
            "brier_score",
            "recall",
            "false_positive_rate",
        ):
            if not _metric_between_zero_and_one(metrics.get(key)):
                failures.append(f"{key} must be numeric between 0 and 1")
        for key in ("evaluated_row_count", "evaluated_positive_count"):
            if not _positive_integer(metrics.get(key)):
                failures.append(f"{key} must be a positive integer")
    else:
        if not _positive_integer(metrics.get("training_row_count")):
            failures.append("training_row_count must be a positive integer")
        if not _metric_between_zero_and_one(metrics.get("contamination"), inclusive=False):
            failures.append("contamination must be numeric between 0 and 1, exclusive")
        checksum = metrics.get("score_reference_checksum")
        if not isinstance(checksum, str) or not _is_sha256(checksum):
            failures.append("score_reference_checksum must be a SHA-256 value")
    return failures


def _metric_between_zero_and_one(value: object, *, inclusive: bool = True) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    numeric = float(value)
    return 0 <= numeric <= 1 if inclusive else 0 < numeric < 1


def _positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


def _registration_facts(
    payload: ModelRegistrationCreate,
    registered_by_username: str,
) -> dict[str, object]:
    return {
        "model_key": payload.model_key,
        "version": payload.version,
        "kind": payload.kind.value,
        "purpose": payload.purpose.value,
        "runtime_contract": payload.runtime_contract.value,
        "artifact_sha256": payload.artifact_sha256,
        "feature_set_version": payload.feature_set_version,
        "training_dataset_id": payload.training_dataset_id,
        "training_dataset_checksum": payload.training_dataset_checksum,
        "training_data_approved": payload.training_data_approved,
        "operational_feature_compatible": payload.operational_feature_compatible,
        "decision_threshold": (
            _decimal_text(payload.decision_threshold)
            if payload.decision_threshold is not None
            else None
        ),
        "evaluation_metrics": payload.evaluation_metrics,
        "model_card_reference": payload.model_card_reference,
        "model_card_checksum": payload.model_card_checksum,
        "registered_by": registered_by_username,
    }


def _stored_registration_facts(model: RegisteredModel, actor_username: str) -> dict[str, object]:
    return {
        "model_key": model.model_key,
        "version": model.version,
        "kind": model.kind,
        "purpose": model.purpose,
        "runtime_contract": model.runtime_contract,
        "artifact_sha256": model.artifact_sha256,
        "feature_set_version": model.feature_set_version,
        "training_dataset_id": model.training_dataset_id,
        "training_dataset_checksum": model.training_dataset_checksum,
        "training_data_approved": model.training_data_approved,
        "operational_feature_compatible": model.operational_feature_compatible,
        "decision_threshold": (
            _decimal_text(model.decision_threshold)
            if model.decision_threshold is not None
            else None
        ),
        "evaluation_metrics": model.evaluation_metrics,
        "model_card_reference": model.model_card_reference,
        "model_card_checksum": model.model_card_checksum,
        "registered_by": actor_username,
    }


def _new_lifecycle_event(
    *,
    model: RegisteredModel,
    sequence_number: int,
    from_status: ModelLifecycleStatus | None,
    to_status: ModelLifecycleStatus,
    reason: str,
    actor: User,
    previous_event_checksum: str | None,
) -> ModelLifecycleEvent:
    created_at = datetime.now(UTC)
    event_checksum = canonical_json_checksum(
        _event_facts(
            registration_checksum=model.registration_checksum,
            sequence_number=sequence_number,
            from_status=from_status.value if from_status is not None else None,
            to_status=to_status.value,
            reason=reason,
            actor_username=actor.username,
            previous_event_checksum=previous_event_checksum,
            created_at=created_at,
        )
    )
    return ModelLifecycleEvent(
        model_id=model.id,
        sequence_number=sequence_number,
        from_status=from_status.value if from_status is not None else None,
        to_status=to_status.value,
        reason=reason,
        actor_user_id=actor.id,
        previous_event_checksum=previous_event_checksum,
        event_checksum=event_checksum,
        created_at=created_at,
    )


def _event_facts(
    *,
    registration_checksum: str,
    sequence_number: int,
    from_status: str | None,
    to_status: str,
    reason: str,
    actor_username: str,
    previous_event_checksum: str | None,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "registration_checksum": registration_checksum,
        "sequence_number": sequence_number,
        "from_status": from_status,
        "to_status": to_status,
        "reason": reason,
        "actor_username": actor_username,
        "previous_event_checksum": previous_event_checksum,
        "created_at": _timestamp_text(created_at),
    }


def _verify_lineage(
    db: Session,
    model: RegisteredModel,
    events: list[ModelLifecycleEvent],
) -> bool:
    registrant = db.get(User, model.registered_by_id)
    if registrant is None:
        return False
    expected_registration_checksum = canonical_json_checksum(
        _stored_registration_facts(model, registrant.username)
    )
    if expected_registration_checksum != model.registration_checksum or not events:
        return False

    expected_status: str | None = None
    previous_checksum: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        actor = db.get(User, event.actor_user_id)
        if actor is None:
            return False
        if (
            event.sequence_number != expected_sequence
            or event.from_status != expected_status
            or event.previous_event_checksum != previous_checksum
        ):
            return False
        expected_checksum = canonical_json_checksum(
            _event_facts(
                registration_checksum=model.registration_checksum,
                sequence_number=event.sequence_number,
                from_status=event.from_status,
                to_status=event.to_status,
                reason=event.reason,
                actor_username=actor.username,
                previous_event_checksum=event.previous_event_checksum,
                created_at=event.created_at,
            )
        )
        if expected_checksum != event.event_checksum:
            return False
        expected_status = event.to_status
        previous_checksum = event.event_checksum
    return (
        events[0].from_status is None
        and events[0].to_status == ModelLifecycleStatus.CANDIDATE.value
    )


def _events(db: Session, model_id: str) -> list[ModelLifecycleEvent]:
    return list(
        db.scalars(
            select(ModelLifecycleEvent)
            .where(ModelLifecycleEvent.model_id == model_id)
            .order_by(ModelLifecycleEvent.sequence_number)
        ).all()
    )


def _current_event(db: Session, model_id: str) -> ModelLifecycleEvent:
    event = db.scalar(
        select(ModelLifecycleEvent)
        .where(ModelLifecycleEvent.model_id == model_id)
        .order_by(ModelLifecycleEvent.sequence_number.desc())
    )
    if event is None:
        raise GovernanceViolation("Model lifecycle history is missing.")
    return event


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _timestamp_text(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat()
