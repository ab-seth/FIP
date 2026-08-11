from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.core.checksums import canonical_json_checksum
from fip_api.hybrid_scoring.policy import (
    DEFAULT_HYBRID_POLICY,
    EVIDENCE_SCHEMA_VERSION,
    SCORE_QUANTUM,
    HybridRiskPolicy,
    decimal_text,
)
from fip_api.model_registry import verify_feature_snapshot_integrity
from fip_api.model_registry.shadow import verify_shadow_prediction_integrity
from fip_api.models import (
    HybridRiskAssessment,
    ModelKind,
    ModelLifecycleEvent,
    ModelPurpose,
    RegisteredModel,
    RuleRiskLevel,
    ShadowModelPrediction,
    Transaction,
    TransactionFeatureSnapshot,
    TransactionRuleAssessment,
    User,
)
from fip_api.schemas.hybrid_risk import (
    HybridComponentResponse,
    HybridComponentsResponse,
    HybridRiskAssessmentResponse,
    HybridWeightsResponse,
)
from fip_api.scoring import find_current_rule_assessment, verify_rule_assessment_integrity


class HybridEvidenceNotFound(LookupError):
    pass


class HybridEvidenceViolation(ValueError):
    pass


def create_hybrid_assessment(
    db: Session,
    *,
    transaction_id: str,
    supervised_prediction_id: str,
    anomaly_prediction_id: str,
    actor: User,
    policy: HybridRiskPolicy = DEFAULT_HYBRID_POLICY,
) -> tuple[HybridRiskAssessment, bool]:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HybridEvidenceNotFound("Transaction not found.")

    rule_result = find_current_rule_assessment(db, transaction.id)
    if rule_result is None:
        raise HybridEvidenceNotFound("Current rule assessment not found.")
    snapshot, rule_assessment = rule_result
    if not verify_feature_snapshot_integrity(snapshot, transaction):
        raise HybridEvidenceViolation("Feature snapshot integrity verification failed.")
    if not verify_rule_assessment_integrity(snapshot, rule_assessment, transaction):
        raise HybridEvidenceViolation("Rule assessment integrity verification failed.")

    supervised_prediction, supervised_model, supervised_event = _verified_prediction(
        db,
        prediction_id=supervised_prediction_id,
        expected_kind=ModelKind.SUPERVISED,
    )
    anomaly_prediction, anomaly_model, anomaly_event = _verified_prediction(
        db,
        prediction_id=anomaly_prediction_id,
        expected_kind=ModelKind.ANOMALY,
    )
    _verify_shared_lineage(
        transaction=transaction,
        snapshot=snapshot,
        rule_assessment=rule_assessment,
        supervised_prediction=supervised_prediction,
        supervised_model=supervised_model,
        anomaly_prediction=anomaly_prediction,
        anomaly_model=anomaly_model,
    )

    existing = db.scalar(
        select(HybridRiskAssessment).where(
            HybridRiskAssessment.feature_snapshot_id == snapshot.id,
            HybridRiskAssessment.rule_assessment_id == rule_assessment.id,
            HybridRiskAssessment.policy_version == policy.version,
            HybridRiskAssessment.supervised_prediction_id == supervised_prediction.id,
            HybridRiskAssessment.anomaly_prediction_id == anomaly_prediction.id,
        )
    )
    if existing is not None:
        if not verify_hybrid_assessment_integrity(db, existing):
            raise HybridEvidenceViolation("Stored hybrid assessment integrity verification failed.")
        return existing, False

    rule_normalized = Decimal(rule_assessment.rule_score) / Decimal("100")
    contributions = {
        "rules": _contribution(rule_normalized, policy.rules_weight),
        "supervised": _contribution(supervised_prediction.score, policy.supervised_weight),
        "anomaly": _contribution(anomaly_prediction.score, policy.anomaly_weight),
    }
    combined_score = sum(contributions.values(), start=Decimal("0")).quantize(SCORE_QUANTUM)
    risk_level = policy.risk_level(combined_score)
    evidence = _evidence_package(
        policy=policy,
        snapshot=snapshot,
        rule_assessment=rule_assessment,
        rule_normalized=rule_normalized,
        supervised_prediction=supervised_prediction,
        supervised_model=supervised_model,
        supervised_event=supervised_event,
        anomaly_prediction=anomaly_prediction,
        anomaly_model=anomaly_model,
        anomaly_event=anomaly_event,
        contributions=contributions,
    )
    created_at = datetime.now(UTC)
    assessment_checksum = canonical_json_checksum(
        _assessment_facts(
            external_transaction_id=transaction.external_transaction_id,
            policy_version=policy.version,
            evidence_schema_version=EVIDENCE_SCHEMA_VERSION,
            weights=(
                policy.rules_weight,
                policy.supervised_weight,
                policy.anomaly_weight,
            ),
            rule_score=rule_assessment.rule_score,
            supervised_score=supervised_prediction.score,
            anomaly_score=anomaly_prediction.score,
            combined_score=combined_score,
            risk_level=risk_level.value,
            evidence=evidence,
            created_by=actor.username,
            created_at=created_at,
        )
    )
    assessment = HybridRiskAssessment(
        transaction_id=transaction.id,
        feature_snapshot_id=snapshot.id,
        rule_assessment_id=rule_assessment.id,
        supervised_prediction_id=supervised_prediction.id,
        anomaly_prediction_id=anomaly_prediction.id,
        policy_version=policy.version,
        evidence_schema_version=EVIDENCE_SCHEMA_VERSION,
        rules_weight=policy.rules_weight,
        supervised_weight=policy.supervised_weight,
        anomaly_weight=policy.anomaly_weight,
        rule_score=rule_assessment.rule_score,
        supervised_score=supervised_prediction.score,
        anomaly_score=anomaly_prediction.score,
        combined_score=combined_score,
        risk_level=risk_level.value,
        evidence_package=evidence,
        created_by_id=actor.id,
        assessment_checksum=assessment_checksum,
        created_at=created_at,
    )
    db.add(assessment)
    db.flush()
    return assessment, True


def list_hybrid_assessments(db: Session, transaction_id: str) -> list[HybridRiskAssessment]:
    return list(
        db.scalars(
            select(HybridRiskAssessment)
            .where(HybridRiskAssessment.transaction_id == transaction_id)
            .order_by(HybridRiskAssessment.created_at, HybridRiskAssessment.id)
        ).all()
    )


def build_hybrid_assessment_response(
    db: Session,
    assessment: HybridRiskAssessment,
) -> HybridRiskAssessmentResponse:
    creator = db.get(User, assessment.created_by_id)
    if creator is None:
        raise HybridEvidenceViolation("Hybrid assessment references a missing creator.")
    rule_normalized = Decimal(assessment.rule_score) / Decimal("100")
    return HybridRiskAssessmentResponse(
        id=assessment.id,
        transaction_id=assessment.transaction_id,
        feature_snapshot_id=assessment.feature_snapshot_id,
        rule_assessment_id=assessment.rule_assessment_id,
        supervised_prediction_id=assessment.supervised_prediction_id,
        anomaly_prediction_id=assessment.anomaly_prediction_id,
        policy_version=assessment.policy_version,
        evidence_schema_version=assessment.evidence_schema_version,
        weights=HybridWeightsResponse(
            rules=decimal_text(assessment.rules_weight),
            supervised=decimal_text(assessment.supervised_weight),
            anomaly=decimal_text(assessment.anomaly_weight),
        ),
        components=HybridComponentsResponse(
            rules=_component_response(
                source_score=str(assessment.rule_score),
                normalized_score=rule_normalized,
                weight=assessment.rules_weight,
            ),
            supervised=_component_response(
                source_score=decimal_text(assessment.supervised_score),
                normalized_score=assessment.supervised_score,
                weight=assessment.supervised_weight,
            ),
            anomaly=_component_response(
                source_score=decimal_text(assessment.anomaly_score),
                normalized_score=assessment.anomaly_score,
                weight=assessment.anomaly_weight,
            ),
        ),
        combined_score=decimal_text(assessment.combined_score),
        risk_level=RuleRiskLevel(assessment.risk_level),
        evidence=assessment.evidence_package,
        created_by=creator.username,
        assessment_checksum=assessment.assessment_checksum,
        integrity_verified=verify_hybrid_assessment_integrity(db, assessment),
        created_at=assessment.created_at,
    )


def verify_hybrid_assessment_integrity(
    db: Session,
    assessment: HybridRiskAssessment,
) -> bool:
    transaction = db.get(Transaction, assessment.transaction_id)
    snapshot = db.get(TransactionFeatureSnapshot, assessment.feature_snapshot_id)
    rule_assessment = db.get(TransactionRuleAssessment, assessment.rule_assessment_id)
    supervised_prediction = db.get(ShadowModelPrediction, assessment.supervised_prediction_id)
    anomaly_prediction = db.get(ShadowModelPrediction, assessment.anomaly_prediction_id)
    creator = db.get(User, assessment.created_by_id)
    if None in (
        transaction,
        snapshot,
        rule_assessment,
        supervised_prediction,
        anomaly_prediction,
        creator,
    ):
        return False
    assert transaction is not None
    assert snapshot is not None
    assert rule_assessment is not None
    assert supervised_prediction is not None
    assert anomaly_prediction is not None
    assert creator is not None
    supervised_model = db.get(RegisteredModel, supervised_prediction.model_id)
    anomaly_model = db.get(RegisteredModel, anomaly_prediction.model_id)
    supervised_event = db.get(ModelLifecycleEvent, supervised_prediction.authorization_event_id)
    anomaly_event = db.get(ModelLifecycleEvent, anomaly_prediction.authorization_event_id)
    if (
        supervised_model is None
        or anomaly_model is None
        or supervised_event is None
        or anomaly_event is None
    ):
        return False

    contributions = {
        "rules": _contribution(
            Decimal(assessment.rule_score) / Decimal("100"),
            assessment.rules_weight,
        ),
        "supervised": _contribution(
            assessment.supervised_score,
            assessment.supervised_weight,
        ),
        "anomaly": _contribution(
            assessment.anomaly_score,
            assessment.anomaly_weight,
        ),
    }
    expected_evidence = _evidence_package(
        policy=DEFAULT_HYBRID_POLICY,
        snapshot=snapshot,
        rule_assessment=rule_assessment,
        rule_normalized=Decimal(rule_assessment.rule_score) / Decimal("100"),
        supervised_prediction=supervised_prediction,
        supervised_model=supervised_model,
        supervised_event=supervised_event,
        anomaly_prediction=anomaly_prediction,
        anomaly_model=anomaly_model,
        anomaly_event=anomaly_event,
        contributions=contributions,
    )

    expected_checksum = canonical_json_checksum(
        _assessment_facts(
            external_transaction_id=transaction.external_transaction_id,
            policy_version=assessment.policy_version,
            evidence_schema_version=assessment.evidence_schema_version,
            weights=(
                assessment.rules_weight,
                assessment.supervised_weight,
                assessment.anomaly_weight,
            ),
            rule_score=assessment.rule_score,
            supervised_score=assessment.supervised_score,
            anomaly_score=assessment.anomaly_score,
            combined_score=assessment.combined_score,
            risk_level=assessment.risk_level,
            evidence=assessment.evidence_package,
            created_by=creator.username,
            created_at=assessment.created_at,
        )
    )
    return (
        expected_checksum == assessment.assessment_checksum
        and assessment.policy_version == DEFAULT_HYBRID_POLICY.version
        and assessment.evidence_schema_version == EVIDENCE_SCHEMA_VERSION
        and assessment.evidence_package == expected_evidence
        and assessment.transaction_id == transaction.id
        and assessment.feature_snapshot_id == snapshot.id
        and assessment.rule_assessment_id == rule_assessment.id
        and assessment.supervised_prediction_id == supervised_prediction.id
        and assessment.anomaly_prediction_id == anomaly_prediction.id
        and assessment.rule_score == rule_assessment.rule_score
        and assessment.supervised_score == supervised_prediction.score
        and assessment.anomaly_score == anomaly_prediction.score
        and assessment.risk_level
        == DEFAULT_HYBRID_POLICY.risk_level(assessment.combined_score).value
        and assessment.combined_score
        == _recalculate_score(
            rule_score=assessment.rule_score,
            supervised_score=assessment.supervised_score,
            anomaly_score=assessment.anomaly_score,
            policy=DEFAULT_HYBRID_POLICY,
        )
        and assessment.rules_weight == DEFAULT_HYBRID_POLICY.rules_weight
        and assessment.supervised_weight == DEFAULT_HYBRID_POLICY.supervised_weight
        and assessment.anomaly_weight == DEFAULT_HYBRID_POLICY.anomaly_weight
        and rule_assessment.transaction_id == transaction.id
        and rule_assessment.feature_snapshot_id == snapshot.id
        and verify_feature_snapshot_integrity(snapshot, transaction)
        and verify_rule_assessment_integrity(snapshot, rule_assessment, transaction)
        and supervised_model.kind == ModelKind.SUPERVISED.value
        and anomaly_model.kind == ModelKind.ANOMALY.value
        and supervised_model.purpose == ModelPurpose.OPERATIONAL.value
        and anomaly_model.purpose == ModelPurpose.OPERATIONAL.value
        and verify_shadow_prediction_integrity(db, supervised_prediction)
        and verify_shadow_prediction_integrity(db, anomaly_prediction)
        and supervised_prediction.transaction_id == transaction.id
        and anomaly_prediction.transaction_id == transaction.id
        and supervised_prediction.feature_snapshot_id == snapshot.id
        and anomaly_prediction.feature_snapshot_id == snapshot.id
    )


def _verified_prediction(
    db: Session,
    *,
    prediction_id: str,
    expected_kind: ModelKind,
) -> tuple[ShadowModelPrediction, RegisteredModel, ModelLifecycleEvent]:
    prediction = db.get(ShadowModelPrediction, prediction_id)
    if prediction is None:
        raise HybridEvidenceNotFound(f"{expected_kind.value.title()} prediction not found.")
    model = db.get(RegisteredModel, prediction.model_id)
    event = db.get(ModelLifecycleEvent, prediction.authorization_event_id)
    if model is None or event is None:
        raise HybridEvidenceViolation(
            f"{expected_kind.value.title()} prediction references missing model lineage."
        )
    if model.kind != expected_kind.value:
        raise HybridEvidenceViolation(
            f"Prediction {prediction.id} is not from a {expected_kind.value} model."
        )
    if model.purpose != ModelPurpose.OPERATIONAL.value:
        raise HybridEvidenceViolation("Only operational-purpose model evidence may be combined.")
    if not verify_shadow_prediction_integrity(db, prediction):
        raise HybridEvidenceViolation(
            f"{expected_kind.value.title()} prediction integrity verification failed."
        )
    return prediction, model, event


def _verify_shared_lineage(
    *,
    transaction: Transaction,
    snapshot: TransactionFeatureSnapshot,
    rule_assessment: TransactionRuleAssessment,
    supervised_prediction: ShadowModelPrediction,
    supervised_model: RegisteredModel,
    anomaly_prediction: ShadowModelPrediction,
    anomaly_model: RegisteredModel,
) -> None:
    if rule_assessment.feature_snapshot_id != snapshot.id:
        raise HybridEvidenceViolation("Rule evidence does not match the selected feature snapshot.")
    for label, prediction in (
        ("Supervised", supervised_prediction),
        ("Anomaly", anomaly_prediction),
    ):
        if prediction.transaction_id != transaction.id:
            raise HybridEvidenceViolation(f"{label} prediction belongs to another transaction.")
        if prediction.feature_snapshot_id != snapshot.id:
            raise HybridEvidenceViolation(
                f"{label} prediction does not share the rule feature snapshot."
            )
    if supervised_model.feature_set_version != snapshot.feature_set_version:
        raise HybridEvidenceViolation(
            "Supervised model feature version does not match the snapshot."
        )
    if anomaly_model.feature_set_version != snapshot.feature_set_version:
        raise HybridEvidenceViolation("Anomaly model feature version does not match the snapshot.")


def _evidence_package(
    *,
    policy: HybridRiskPolicy,
    snapshot: TransactionFeatureSnapshot,
    rule_assessment: TransactionRuleAssessment,
    rule_normalized: Decimal,
    supervised_prediction: ShadowModelPrediction,
    supervised_model: RegisteredModel,
    supervised_event: ModelLifecycleEvent,
    anomaly_prediction: ShadowModelPrediction,
    anomaly_model: RegisteredModel,
    anomaly_event: ModelLifecycleEvent,
    contributions: dict[str, Decimal],
) -> dict[str, object]:
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "policy": policy.evidence_facts(),
        "feature_snapshot": {
            "feature_set_version": snapshot.feature_set_version,
            "snapshot_checksum": snapshot.snapshot_checksum,
            "history_checksum": snapshot.history_checksum,
        },
        "components": {
            "rules": {
                "source_score": str(rule_assessment.rule_score),
                "normalized_score": decimal_text(rule_normalized),
                "weight": decimal_text(policy.rules_weight),
                "contribution_points": decimal_text(contributions["rules"]),
            },
            "supervised": {
                "source_score": decimal_text(supervised_prediction.score),
                "normalized_score": decimal_text(supervised_prediction.score),
                "weight": decimal_text(policy.supervised_weight),
                "contribution_points": decimal_text(contributions["supervised"]),
            },
            "anomaly": {
                "source_score": decimal_text(anomaly_prediction.score),
                "normalized_score": decimal_text(anomaly_prediction.score),
                "weight": decimal_text(policy.anomaly_weight),
                "contribution_points": decimal_text(contributions["anomaly"]),
            },
        },
        "lineage": {
            "rules": {
                "ruleset_version": rule_assessment.ruleset_version,
                "risk_band_version": rule_assessment.risk_band_version,
                "assessment_checksum": rule_assessment.assessment_checksum,
                "triggered_rules": rule_assessment.triggered_rules,
            },
            "supervised": _prediction_lineage(
                supervised_prediction, supervised_model, supervised_event
            ),
            "anomaly": _prediction_lineage(anomaly_prediction, anomaly_model, anomaly_event),
        },
        "limitations": {
            "decision_support_only": True,
            "shadow_inputs_only": True,
            "affects_case_priority": False,
            "affects_transaction_action": False,
            "llm_influenced_score": False,
            "missing_input_behavior": "fail_closed",
        },
    }


def _prediction_lineage(
    prediction: ShadowModelPrediction,
    model: RegisteredModel,
    event: ModelLifecycleEvent,
) -> dict[str, object]:
    return {
        "model_key": model.model_key,
        "model_version": model.version,
        "model_kind": model.kind,
        "runtime_contract": model.runtime_contract,
        "artifact_sha256": model.artifact_sha256,
        "training_dataset_id": model.training_dataset_id,
        "training_dataset_checksum": model.training_dataset_checksum,
        "registration_checksum": model.registration_checksum,
        "authorization_event_checksum": event.event_checksum,
        "output_schema_version": prediction.output_schema_version,
        "prediction_checksum": prediction.prediction_checksum,
        "factor_contributions": prediction.factor_contributions,
    }


def _assessment_facts(
    *,
    external_transaction_id: str,
    policy_version: str,
    evidence_schema_version: str,
    weights: tuple[Decimal, Decimal, Decimal],
    rule_score: int,
    supervised_score: Decimal,
    anomaly_score: Decimal,
    combined_score: Decimal,
    risk_level: str,
    evidence: dict[str, object],
    created_by: str,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "external_transaction_id": external_transaction_id,
        "policy_version": policy_version,
        "evidence_schema_version": evidence_schema_version,
        "weights": {
            "rules": decimal_text(weights[0]),
            "supervised": decimal_text(weights[1]),
            "anomaly": decimal_text(weights[2]),
        },
        "rule_score": rule_score,
        "supervised_score": decimal_text(supervised_score),
        "anomaly_score": decimal_text(anomaly_score),
        "combined_score": decimal_text(combined_score),
        "risk_level": risk_level,
        "evidence": evidence,
        "created_by": created_by,
        "created_at": _timestamp_text(created_at),
        "decision_support_only": True,
    }


def _component_response(
    *,
    source_score: str,
    normalized_score: Decimal,
    weight: Decimal,
) -> HybridComponentResponse:
    return HybridComponentResponse(
        source_score=source_score,
        normalized_score=decimal_text(normalized_score),
        weight=decimal_text(weight),
        contribution_points=decimal_text(_contribution(normalized_score, weight)),
    )


def _contribution(normalized_score: Decimal, weight: Decimal) -> Decimal:
    return (Decimal(normalized_score) * weight * Decimal("100")).quantize(SCORE_QUANTUM)


def _recalculate_score(
    *,
    rule_score: int,
    supervised_score: Decimal,
    anomaly_score: Decimal,
    policy: HybridRiskPolicy,
) -> Decimal:
    return sum(
        (
            _contribution(Decimal(rule_score) / Decimal("100"), policy.rules_weight),
            _contribution(supervised_score, policy.supervised_weight),
            _contribution(anomaly_score, policy.anomaly_weight),
        ),
        start=Decimal("0"),
    ).quantize(SCORE_QUANTUM)


def _timestamp_text(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat()
