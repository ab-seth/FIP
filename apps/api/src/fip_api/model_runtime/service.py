from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import joblib
import numpy as np
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from fip_api.features import FEATURE_SET_VERSION
from fip_api.model_registry import (
    GovernanceViolation,
    ModelNotFound,
    ShadowFactor,
    ShadowRuntimeMismatch,
    ShadowRuntimeOutput,
    score_shadow_transaction,
    verify_model_lineage,
)
from fip_api.models import (
    ModelKind,
    ModelLifecycleStatus,
    ModelPurpose,
    ModelRuntimeContract,
    RegisteredModel,
    ShadowModelPrediction,
    Transaction,
    TransactionFeatureSnapshot,
)
from fip_api.operational_ml.models import AnomalyModelArtifact, SupervisedModelArtifact
from fip_api.operational_ml.preprocessing import (
    CATEGORICAL_FEATURE_NAMES,
    NUMERIC_FEATURE_NAMES,
    UNKNOWN_CATEGORY,
)
from fip_api.training_datasets.service import TRAINING_FEATURE_NAMES

from .artifacts import ArtifactInstallation, ArtifactStoreError, ModelArtifactStore

FACTOR_LIMIT = 10
FACTOR_EPSILON = 1e-12
THRESHOLD_QUANTUM = Decimal("0.0000000001")


class OperationalArtifactMismatch(ArtifactStoreError):
    pass


@dataclass(frozen=True)
class ShadowBatchResult:
    predictions: tuple[ShadowModelPrediction, ...]
    created_count: int


@dataclass(frozen=True)
class VerifiedOperationalRuntime:
    artifact_sha256: str
    feature_set_version: str
    runtime_contract: ModelRuntimeContract
    artifact: SupervisedModelArtifact | AnomalyModelArtifact

    def predict(self, feature_values: dict[str, object]) -> ShadowRuntimeOutput:
        if not set(TRAINING_FEATURE_NAMES).issubset(feature_values):
            raise ShadowRuntimeMismatch(
                "The immutable feature snapshot is missing required operational features."
            )

        operational_values = {
            feature_name: feature_values[feature_name] for feature_name in TRAINING_FEATURE_NAMES
        }
        variants = [operational_values]
        feature_order: list[str] = []
        for feature_name in TRAINING_FEATURE_NAMES:
            reference_value = _reference_value(self.artifact, feature_name)
            if operational_values[feature_name] == reference_value:
                continue
            variant = dict(operational_values)
            variant[feature_name] = reference_value
            variants.append(variant)
            feature_order.append(feature_name)

        try:
            scores = np.asarray(self.artifact.predict_scores(variants), dtype=np.float64)
        except (KeyError, TypeError, ValueError) as exc:
            raise ShadowRuntimeMismatch(
                "The operational artifact rejected the immutable feature snapshot."
            ) from exc
        if scores.shape != (len(variants),) or not np.all(np.isfinite(scores)):
            raise ShadowRuntimeMismatch("The operational artifact returned invalid scores.")
        if np.any(scores < 0) or np.any(scores > 1):
            raise ShadowRuntimeMismatch("The operational artifact returned an out-of-range score.")

        score = float(scores[0])
        contributions = [
            (feature_name, score - float(reference_score))
            for feature_name, reference_score in zip(feature_order, scores[1:], strict=True)
            if abs(score - float(reference_score)) > FACTOR_EPSILON
        ]
        strongest = sorted(contributions, key=lambda item: (-abs(item[1]), item[0]))[:FACTOR_LIMIT]
        factors = tuple(
            ShadowFactor(
                feature=feature_name,
                contribution=Decimal(str(contribution)),
                direction="increases_risk" if contribution > 0 else "decreases_risk",
            )
            for feature_name, contribution in strongest
        )
        return ShadowRuntimeOutput(score=Decimal(str(score)), factors=factors)


def install_registered_artifact(
    db: Session,
    *,
    model_id: str,
    content: bytes,
    store: ModelArtifactStore,
) -> ArtifactInstallation:
    model = _registered_operational_model(db, model_id)
    status = ModelLifecycleStatus(_current_status(db, model.id))
    if status in {ModelLifecycleStatus.REJECTED, ModelLifecycleStatus.RETIRED}:
        raise GovernanceViolation("Artifacts cannot be installed for a terminal model version.")
    return store.install(model.artifact_sha256, content)


def load_verified_runtime(
    model: RegisteredModel,
    store: ModelArtifactStore,
) -> VerifiedOperationalRuntime:
    _validate_registered_model(model)
    try:
        with store.open_verified(model.artifact_sha256) as artifact_stream:
            artifact: Any = joblib.load(artifact_stream)
    except ArtifactStoreError:
        raise
    except Exception as exc:
        raise OperationalArtifactMismatch(
            "The checksum-verified model artifact could not be deserialized."
        ) from exc

    expected_type: type[SupervisedModelArtifact] | type[AnomalyModelArtifact]
    expected_contract: ModelRuntimeContract
    if model.kind == ModelKind.SUPERVISED.value:
        expected_type = SupervisedModelArtifact
        expected_contract = ModelRuntimeContract.BINARY_PROBABILITY
    else:
        expected_type = AnomalyModelArtifact
        expected_contract = ModelRuntimeContract.ANOMALY_SCORE
    if type(artifact) is not expected_type:
        raise OperationalArtifactMismatch(
            "The artifact class does not match the registered model kind."
        )
    if model.runtime_contract != expected_contract.value:
        raise OperationalArtifactMismatch(
            "The artifact class does not match the registered runtime contract."
        )
    if artifact.feature_set_version != model.feature_set_version:
        raise OperationalArtifactMismatch(
            "The artifact feature version does not match the model registry."
        )
    if artifact.training_dataset_checksum != model.training_dataset_checksum:
        raise OperationalArtifactMismatch(
            "The artifact training dataset does not match the model registry."
        )
    if model.decision_threshold is None or _threshold(artifact.threshold) != _threshold(
        model.decision_threshold
    ):
        raise OperationalArtifactMismatch(
            "The artifact decision threshold does not match the model registry."
        )
    return VerifiedOperationalRuntime(
        artifact_sha256=model.artifact_sha256,
        feature_set_version=model.feature_set_version,
        runtime_contract=expected_contract,
        artifact=artifact,
    )


def run_shadow_batch(
    db: Session,
    *,
    model_id: str,
    transaction_ids: tuple[str, ...] | None,
    limit: int,
    store: ModelArtifactStore,
) -> ShadowBatchResult:
    model = _registered_operational_model(db, model_id)
    if _current_status(db, model.id) != ModelLifecycleStatus.SHADOW.value:
        raise GovernanceViolation(
            "Only a model in shadow status may load and execute its registered artifact."
        )
    runtime = load_verified_runtime(model, store)
    selected_ids = (
        transaction_ids
        if transaction_ids is not None
        else _unscored_transaction_ids(db, model, limit)
    )
    predictions: list[ShadowModelPrediction] = []
    created_count = 0
    for transaction_id in selected_ids:
        prediction, created = score_shadow_transaction(
            db,
            transaction_id=transaction_id,
            model_id=model.id,
            runtime=runtime,
        )
        predictions.append(prediction)
        created_count += int(created)
    return ShadowBatchResult(predictions=tuple(predictions), created_count=created_count)


def _registered_operational_model(db: Session, model_id: str) -> RegisteredModel:
    model = db.get(RegisteredModel, model_id)
    if model is None:
        raise ModelNotFound("Model version not found.")
    if not verify_model_lineage(db, model):
        raise GovernanceViolation("Model lifecycle integrity verification failed.")
    _validate_registered_model(model)
    return model


def _validate_registered_model(model: RegisteredModel) -> None:
    if model.purpose != ModelPurpose.OPERATIONAL.value:
        raise GovernanceViolation("Only operational models may use the trusted artifact runtime.")
    if not model.training_data_approved or not model.operational_feature_compatible:
        raise GovernanceViolation("The model is not approved for operational semantic features.")
    if model.feature_set_version != FEATURE_SET_VERSION:
        raise GovernanceViolation("The model does not use the active operational feature contract.")


def _current_status(db: Session, model_id: str) -> str:
    from fip_api.model_registry.service import current_lifecycle_event

    return current_lifecycle_event(db, model_id).to_status


def _unscored_transaction_ids(
    db: Session,
    model: RegisteredModel,
    limit: int,
) -> tuple[str, ...]:
    already_scored = exists(
        select(ShadowModelPrediction.id).where(
            ShadowModelPrediction.feature_snapshot_id == TransactionFeatureSnapshot.id,
            ShadowModelPrediction.model_id == model.id,
        )
    )
    return tuple(
        db.scalars(
            select(Transaction.id)
            .join(
                TransactionFeatureSnapshot,
                TransactionFeatureSnapshot.transaction_id == Transaction.id,
            )
            .where(
                TransactionFeatureSnapshot.feature_set_version == model.feature_set_version,
                ~already_scored,
            )
            .order_by(Transaction.occurred_at, Transaction.id)
            .limit(limit)
        ).all()
    )


def _reference_value(
    artifact: SupervisedModelArtifact | AnomalyModelArtifact,
    feature_name: str,
) -> object:
    if feature_name in NUMERIC_FEATURE_NAMES:
        return artifact.preprocessor.numeric_medians[feature_name]
    if feature_name in CATEGORICAL_FEATURE_NAMES:
        return UNKNOWN_CATEGORY
    raise ShadowRuntimeMismatch(f"Unsupported operational feature: {feature_name}.")


def _threshold(value: object) -> Decimal:
    try:
        return Decimal(str(value)).quantize(THRESHOLD_QUANTUM)
    except (InvalidOperation, ValueError) as exc:
        raise OperationalArtifactMismatch("The artifact threshold is invalid.") from exc
