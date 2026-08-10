from __future__ import annotations

from datetime import timedelta

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
    Transaction,
    TransactionFeatureSnapshot,
    TransactionRuleAssessment,
)
from fip_api.rules import RISK_BAND_VERSION, RULESET_VERSION, evaluate_rules


def assess_transaction(
    db: Session,
    transaction: Transaction,
) -> tuple[TransactionFeatureSnapshot, TransactionRuleAssessment]:
    existing = find_current_rule_assessment(db, transaction.id)
    if existing is not None:
        return existing

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
