from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from time import perf_counter_ns
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.core.checksums import canonical_json_checksum
from fip_api.model_registry.service import (
    GovernanceViolation,
    ModelNotFound,
    current_lifecycle_event,
    verify_model_lineage,
)
from fip_api.models import (
    ModelLifecycleEvent,
    ModelLifecycleStatus,
    ModelRuntimeContract,
    RegisteredModel,
    ShadowModelPrediction,
    Transaction,
    TransactionFeatureSnapshot,
)
from fip_api.schemas.model_registry import ShadowFactorResponse, ShadowPredictionResponse

SHADOW_OUTPUT_SCHEMA_VERSION = "shadow-model-output-v1.0.0"
FACTOR_DIRECTIONS = {"increases_risk", "decreases_risk", "neutral"}
SCORE_QUANTUM = Decimal("0.0000000001")


class ShadowRuntimeMismatch(ValueError):
    pass


@dataclass(frozen=True)
class ShadowFactor:
    feature: str
    contribution: Decimal
    direction: str


@dataclass(frozen=True)
class ShadowRuntimeOutput:
    score: Decimal
    factors: tuple[ShadowFactor, ...] = ()


class ShadowRuntime(Protocol):
    @property
    def artifact_sha256(self) -> str: ...

    @property
    def feature_set_version(self) -> str: ...

    @property
    def runtime_contract(self) -> ModelRuntimeContract: ...

    def predict(self, feature_values: dict[str, object]) -> ShadowRuntimeOutput: ...


def score_shadow_transaction(
    db: Session,
    *,
    transaction_id: str,
    model_id: str,
    runtime: ShadowRuntime,
) -> tuple[ShadowModelPrediction, bool]:
    model = db.get(RegisteredModel, model_id)
    if model is None:
        raise ModelNotFound("Model version not found.")
    if not verify_model_lineage(db, model):
        raise GovernanceViolation("Model lifecycle integrity verification failed.")
    authorization_event = current_lifecycle_event(db, model.id)
    if authorization_event.to_status != ModelLifecycleStatus.SHADOW.value:
        raise GovernanceViolation("Only a model in shadow status may emit shadow predictions.")
    _verify_runtime_contract(model, runtime)

    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise ModelNotFound("Transaction not found.")
    feature_snapshot = db.scalar(
        select(TransactionFeatureSnapshot).where(
            TransactionFeatureSnapshot.transaction_id == transaction.id,
            TransactionFeatureSnapshot.feature_set_version == model.feature_set_version,
        )
    )
    if feature_snapshot is None:
        raise GovernanceViolation("A compatible immutable feature snapshot is not available.")
    if not verify_feature_snapshot_integrity(feature_snapshot, transaction):
        raise GovernanceViolation("Feature snapshot integrity verification failed.")

    existing = db.scalar(
        select(ShadowModelPrediction).where(
            ShadowModelPrediction.feature_snapshot_id == feature_snapshot.id,
            ShadowModelPrediction.model_id == model.id,
        )
    )
    if existing is not None:
        return existing, False

    started_at = perf_counter_ns()
    output = runtime.predict(feature_snapshot.feature_values)
    runtime_milliseconds = max(0, (perf_counter_ns() - started_at) // 1_000_000)
    score = _bounded_decimal(output.score, field_name="score")
    if model.decision_threshold is None:
        raise GovernanceViolation("The registered model does not have a shadow threshold.")
    threshold = _bounded_decimal(model.decision_threshold, field_name="threshold")
    factors = _normalize_factors(output.factors, feature_snapshot.feature_values)
    would_exceed_threshold = score >= threshold
    created_at = datetime.now(UTC)
    prediction_checksum = canonical_json_checksum(
        _prediction_facts(
            output_schema_version=SHADOW_OUTPUT_SCHEMA_VERSION,
            external_transaction_id=transaction.external_transaction_id,
            feature_snapshot_checksum=feature_snapshot.snapshot_checksum,
            registration_checksum=model.registration_checksum,
            authorization_event_checksum=authorization_event.event_checksum,
            score=score,
            threshold=threshold,
            would_exceed_threshold=would_exceed_threshold,
            factors=factors,
            runtime_milliseconds=runtime_milliseconds,
            created_at=created_at,
        )
    )
    prediction = ShadowModelPrediction(
        transaction_id=transaction.id,
        feature_snapshot_id=feature_snapshot.id,
        model_id=model.id,
        authorization_event_id=authorization_event.id,
        output_schema_version=SHADOW_OUTPUT_SCHEMA_VERSION,
        score=score,
        threshold=threshold,
        would_exceed_threshold=would_exceed_threshold,
        factor_contributions=factors,
        runtime_milliseconds=runtime_milliseconds,
        prediction_checksum=prediction_checksum,
        created_at=created_at,
    )
    db.add(prediction)
    db.flush()
    return prediction, True


def list_shadow_predictions(db: Session, transaction_id: str) -> list[ShadowModelPrediction]:
    return list(
        db.scalars(
            select(ShadowModelPrediction)
            .where(ShadowModelPrediction.transaction_id == transaction_id)
            .order_by(ShadowModelPrediction.created_at, ShadowModelPrediction.model_id)
        ).all()
    )


def build_shadow_prediction_response(
    db: Session,
    prediction: ShadowModelPrediction,
) -> ShadowPredictionResponse:
    model = db.get(RegisteredModel, prediction.model_id)
    snapshot = db.get(TransactionFeatureSnapshot, prediction.feature_snapshot_id)
    authorization_event = db.get(ModelLifecycleEvent, prediction.authorization_event_id)
    transaction = db.get(Transaction, prediction.transaction_id)
    integrity_verified = verify_shadow_prediction_integrity(db, prediction)

    if model is None or snapshot is None or authorization_event is None or transaction is None:
        raise GovernanceViolation("Shadow prediction references missing lineage records.")
    return ShadowPredictionResponse(
        id=prediction.id,
        transaction_id=prediction.transaction_id,
        model_id=model.id,
        model_key=model.model_key,
        model_version=model.version,
        feature_set_version=snapshot.feature_set_version,
        feature_snapshot_checksum=snapshot.snapshot_checksum,
        authorization_event_checksum=authorization_event.event_checksum,
        output_schema_version=prediction.output_schema_version,
        score=_decimal_text(prediction.score),
        threshold=_decimal_text(prediction.threshold),
        would_exceed_model_threshold=prediction.would_exceed_threshold,
        factors=[
            ShadowFactorResponse.model_validate(factor)
            for factor in prediction.factor_contributions
        ],
        runtime_milliseconds=prediction.runtime_milliseconds,
        prediction_checksum=prediction.prediction_checksum,
        integrity_verified=integrity_verified,
        created_at=prediction.created_at,
    )


def _verify_runtime_contract(model: RegisteredModel, runtime: ShadowRuntime) -> None:
    failures: list[str] = []
    if runtime.artifact_sha256 != model.artifact_sha256:
        failures.append("artifact checksum")
    if runtime.feature_set_version != model.feature_set_version:
        failures.append("feature set version")
    if runtime.runtime_contract.value != model.runtime_contract:
        failures.append("runtime contract")
    if failures:
        raise ShadowRuntimeMismatch(
            "Runtime does not match registered " + ", ".join(failures) + "."
        )


def verify_shadow_prediction_integrity(
    db: Session,
    prediction: ShadowModelPrediction,
) -> bool:
    model = db.get(RegisteredModel, prediction.model_id)
    snapshot = db.get(TransactionFeatureSnapshot, prediction.feature_snapshot_id)
    authorization_event = db.get(ModelLifecycleEvent, prediction.authorization_event_id)
    transaction = db.get(Transaction, prediction.transaction_id)
    if None in (model, snapshot, authorization_event, transaction):
        return False
    assert model is not None
    assert snapshot is not None
    assert authorization_event is not None
    assert transaction is not None
    expected_checksum = canonical_json_checksum(
        _prediction_facts(
            output_schema_version=prediction.output_schema_version,
            external_transaction_id=transaction.external_transaction_id,
            feature_snapshot_checksum=snapshot.snapshot_checksum,
            registration_checksum=model.registration_checksum,
            authorization_event_checksum=authorization_event.event_checksum,
            score=prediction.score,
            threshold=prediction.threshold,
            would_exceed_threshold=prediction.would_exceed_threshold,
            factors=prediction.factor_contributions,
            runtime_milliseconds=prediction.runtime_milliseconds,
            created_at=prediction.created_at,
        )
    )
    return (
        expected_checksum == prediction.prediction_checksum
        and prediction.output_schema_version == SHADOW_OUTPUT_SCHEMA_VERSION
        and prediction.transaction_id == transaction.id
        and prediction.feature_snapshot_id == snapshot.id
        and prediction.authorization_event_id == authorization_event.id
        and snapshot.transaction_id == transaction.id
        and snapshot.feature_set_version == model.feature_set_version
        and authorization_event.model_id == model.id
        and authorization_event.to_status == ModelLifecycleStatus.SHADOW.value
        and model.decision_threshold is not None
        and prediction.threshold == model.decision_threshold
        and verify_model_lineage(db, model)
        and verify_feature_snapshot_integrity(snapshot, transaction)
    )


def verify_feature_snapshot_integrity(
    snapshot: TransactionFeatureSnapshot,
    transaction: Transaction,
) -> bool:
    expected_checksum = canonical_json_checksum(
        {
            "feature_set_version": snapshot.feature_set_version,
            "feature_values": snapshot.feature_values,
            "history_checksum": snapshot.history_checksum,
            "external_transaction_id": transaction.external_transaction_id,
        }
    )
    return expected_checksum == snapshot.snapshot_checksum


def _normalize_factors(
    factors: tuple[ShadowFactor, ...],
    feature_values: dict[str, object],
) -> list[dict[str, object]]:
    if len(factors) > 20:
        raise ShadowRuntimeMismatch("A shadow prediction may expose at most 20 factors.")
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for factor in factors:
        if factor.feature in seen:
            raise ShadowRuntimeMismatch("Shadow factor names must be unique.")
        if factor.feature not in feature_values:
            raise ShadowRuntimeMismatch(
                f"Shadow factor {factor.feature!r} is not in the feature snapshot."
            )
        if factor.direction not in FACTOR_DIRECTIONS:
            raise ShadowRuntimeMismatch(f"Unsupported shadow factor direction: {factor.direction}.")
        contribution = _finite_decimal(factor.contribution, field_name="factor contribution")
        normalized.append(
            {
                "feature": factor.feature,
                "contribution": _decimal_text(contribution),
                "direction": factor.direction,
            }
        )
        seen.add(factor.feature)
    return sorted(normalized, key=lambda factor: str(factor["feature"]))


def _prediction_facts(
    *,
    output_schema_version: str,
    external_transaction_id: str,
    feature_snapshot_checksum: str,
    registration_checksum: str,
    authorization_event_checksum: str,
    score: Decimal,
    threshold: Decimal,
    would_exceed_threshold: bool,
    factors: list[dict[str, object]],
    runtime_milliseconds: int,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "output_schema_version": output_schema_version,
        "external_transaction_id": external_transaction_id,
        "feature_snapshot_checksum": feature_snapshot_checksum,
        "registration_checksum": registration_checksum,
        "authorization_event_checksum": authorization_event_checksum,
        "score": _decimal_text(score),
        "threshold": _decimal_text(threshold),
        "would_exceed_threshold": would_exceed_threshold,
        "factors": factors,
        "runtime_milliseconds": runtime_milliseconds,
        "created_at": _timestamp_text(created_at),
        "shadow_only": True,
        "affects_operational_score": False,
    }


def _bounded_decimal(value: Decimal, *, field_name: str) -> Decimal:
    numeric = _finite_decimal(value, field_name=field_name)
    if not 0 <= numeric <= 1:
        raise ShadowRuntimeMismatch(f"Shadow {field_name} must be between 0 and 1.")
    return numeric.quantize(SCORE_QUANTUM)


def _finite_decimal(value: Decimal, *, field_name: str) -> Decimal:
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ShadowRuntimeMismatch(f"Shadow {field_name} must be numeric.") from exc
    if not numeric.is_finite():
        raise ShadowRuntimeMismatch(f"Shadow {field_name} must be finite.")
    return numeric


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _timestamp_text(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat()
