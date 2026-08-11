from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import perf_counter_ns

from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.core.checksums import canonical_json_checksum
from fip_api.features import (
    FEATURE_SET_VERSION,
    HISTORY_WINDOW_DAYS,
    build_semantic_features,
    history_checksum,
)
from fip_api.models import (
    ScoringRuntimeObservation,
    Transaction,
    TransactionFeatureSnapshot,
    TransactionRuleAssessment,
)
from fip_api.rules import RISK_BAND_VERSION, RULESET_VERSION, evaluate_rules

SCORING_RUNTIME_OBSERVATION_SCHEMA_VERSION = "semantic-rules-runtime-v1.0.0"


def assess_transaction(
    db: Session,
    transaction: Transaction,
) -> tuple[TransactionFeatureSnapshot, TransactionRuleAssessment]:
    existing = find_current_rule_assessment(db, transaction.id)
    if existing is not None:
        return existing

    started_at = perf_counter_ns()

    history_window_start = transaction.occurred_at - timedelta(days=HISTORY_WINDOW_DAYS)
    history = list(
        db.scalars(
            select(Transaction)
            .where(
                Transaction.account_reference == transaction.account_reference,
                Transaction.id != transaction.id,
                Transaction.occurred_at >= history_window_start,
                Transaction.occurred_at < transaction.occurred_at,
            )
            .order_by(Transaction.occurred_at, Transaction.external_transaction_id)
        ).all()
    )
    features = build_semantic_features(transaction, history)
    feature_values = features.as_dict()
    history_digest = history_checksum(history)
    snapshot_digest = canonical_json_checksum(
        {
            "feature_set_version": FEATURE_SET_VERSION,
            "feature_values": feature_values,
            "history_checksum": history_digest,
            "external_transaction_id": transaction.external_transaction_id,
        }
    )
    snapshot = TransactionFeatureSnapshot(
        transaction_id=transaction.id,
        feature_set_version=FEATURE_SET_VERSION,
        history_window_start=history_window_start,
        history_window_end=transaction.occurred_at,
        history_checksum=history_digest,
        feature_values=feature_values,
        snapshot_checksum=snapshot_digest,
    )
    db.add(snapshot)
    db.flush()

    evaluation = evaluate_rules(features)
    triggered_rules = [trigger.as_dict() for trigger in evaluation.triggered_rules]
    assessment_digest = canonical_json_checksum(
        {
            "feature_snapshot_checksum": snapshot.snapshot_checksum,
            "risk_band_version": RISK_BAND_VERSION,
            "risk_level": evaluation.risk_level.value,
            "rule_score": evaluation.rule_score,
            "ruleset_version": RULESET_VERSION,
            "external_transaction_id": transaction.external_transaction_id,
            "triggered_rules": triggered_rules,
        }
    )
    assessment = TransactionRuleAssessment(
        transaction_id=transaction.id,
        feature_snapshot_id=snapshot.id,
        ruleset_version=RULESET_VERSION,
        risk_band_version=RISK_BAND_VERSION,
        rule_score=evaluation.rule_score,
        risk_level=evaluation.risk_level.value,
        triggered_rules=triggered_rules,
        assessment_checksum=assessment_digest,
    )
    db.add(assessment)
    db.flush()
    runtime_milliseconds = max(0, (perf_counter_ns() - started_at) // 1_000_000)
    created_at = datetime.now(UTC)
    observation = ScoringRuntimeObservation(
        transaction_id=transaction.id,
        feature_snapshot_id=snapshot.id,
        rule_assessment_id=assessment.id,
        observation_schema_version=SCORING_RUNTIME_OBSERVATION_SCHEMA_VERSION,
        runtime_milliseconds=runtime_milliseconds,
        rule_assessment_checksum=assessment.assessment_checksum,
        observation_checksum=canonical_json_checksum(
            _runtime_observation_facts(
                external_transaction_id=transaction.external_transaction_id,
                feature_snapshot_checksum=snapshot.snapshot_checksum,
                rule_assessment_checksum=assessment.assessment_checksum,
                runtime_milliseconds=runtime_milliseconds,
                created_at=created_at,
            )
        ),
        created_at=created_at,
    )
    db.add(observation)
    db.flush()
    return snapshot, assessment


def find_current_rule_assessment(
    db: Session,
    transaction_id: str,
) -> tuple[TransactionFeatureSnapshot, TransactionRuleAssessment] | None:
    assessment = db.scalar(
        select(TransactionRuleAssessment)
        .where(
            TransactionRuleAssessment.transaction_id == transaction_id,
            TransactionRuleAssessment.ruleset_version == RULESET_VERSION,
            TransactionRuleAssessment.risk_band_version == RISK_BAND_VERSION,
        )
        .order_by(TransactionRuleAssessment.created_at.desc())
    )
    if assessment is None:
        return None
    snapshot = db.get(TransactionFeatureSnapshot, assessment.feature_snapshot_id)
    if snapshot is None:
        raise RuntimeError("Rule assessment references a missing feature snapshot")
    return snapshot, assessment


def verify_rule_assessment_integrity(
    snapshot: TransactionFeatureSnapshot,
    assessment: TransactionRuleAssessment,
    transaction: Transaction,
) -> bool:
    expected_checksum = canonical_json_checksum(
        {
            "feature_snapshot_checksum": snapshot.snapshot_checksum,
            "risk_band_version": assessment.risk_band_version,
            "risk_level": assessment.risk_level,
            "rule_score": assessment.rule_score,
            "ruleset_version": assessment.ruleset_version,
            "external_transaction_id": transaction.external_transaction_id,
            "triggered_rules": assessment.triggered_rules,
        }
    )
    return (
        assessment.transaction_id == transaction.id
        and assessment.feature_snapshot_id == snapshot.id
        and snapshot.transaction_id == transaction.id
        and expected_checksum == assessment.assessment_checksum
    )


def verify_scoring_runtime_observation(
    db: Session,
    observation: ScoringRuntimeObservation,
) -> bool:
    transaction = db.get(Transaction, observation.transaction_id)
    snapshot = db.get(TransactionFeatureSnapshot, observation.feature_snapshot_id)
    assessment = db.get(TransactionRuleAssessment, observation.rule_assessment_id)
    if transaction is None or snapshot is None or assessment is None:
        return False
    expected_checksum = canonical_json_checksum(
        _runtime_observation_facts(
            external_transaction_id=transaction.external_transaction_id,
            feature_snapshot_checksum=snapshot.snapshot_checksum,
            rule_assessment_checksum=assessment.assessment_checksum,
            runtime_milliseconds=observation.runtime_milliseconds,
            created_at=observation.created_at,
        )
    )
    return (
        observation.observation_schema_version == SCORING_RUNTIME_OBSERVATION_SCHEMA_VERSION
        and observation.transaction_id == transaction.id
        and observation.feature_snapshot_id == snapshot.id
        and observation.rule_assessment_id == assessment.id
        and observation.rule_assessment_checksum == assessment.assessment_checksum
        and verify_rule_assessment_integrity(snapshot, assessment, transaction)
        and observation.observation_checksum == expected_checksum
    )


def _runtime_observation_facts(
    *,
    external_transaction_id: str,
    feature_snapshot_checksum: str,
    rule_assessment_checksum: str,
    runtime_milliseconds: int,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "observation_schema_version": SCORING_RUNTIME_OBSERVATION_SCHEMA_VERSION,
        "external_transaction_id": external_transaction_id,
        "feature_snapshot_checksum": feature_snapshot_checksum,
        "rule_assessment_checksum": rule_assessment_checksum,
        "runtime_milliseconds": runtime_milliseconds,
        "created_at": _timestamp_text(created_at),
    }


def _timestamp_text(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat()


def backfill_rule_assessments(db: Session) -> int:
    created = 0
    transactions = db.scalars(
        select(Transaction).order_by(
            Transaction.occurred_at,
            Transaction.external_transaction_id,
        )
    ).all()
    for transaction in transactions:
        if find_current_rule_assessment(db, transaction.id) is None:
            assess_transaction(db, transaction)
            created += 1
    db.commit()
    return created
