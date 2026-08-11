from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fip_api.core.security import hash_password
from fip_api.features import FEATURE_SET_VERSION
from fip_api.hybrid_scoring import DEFAULT_HYBRID_POLICY
from fip_api.model_registry import ShadowRuntimeOutput, score_shadow_transaction
from fip_api.models import (
    AnalystCase,
    HybridRiskAssessment,
    ModelRuntimeContract,
    ShadowModelPrediction,
    TransactionRuleAssessment,
    User,
    UserRole,
)

PASSWORD = "strong-password"
DATASET_CHECKSUM = "b" * 64
MODEL_CARD_CHECKSUM = "c" * 64


class FixedShadowRuntime:
    def __init__(
        self,
        *,
        artifact_sha256: str,
        runtime_contract: ModelRuntimeContract,
        score: Decimal,
    ) -> None:
        self.artifact_sha256 = artifact_sha256
        self.feature_set_version = FEATURE_SET_VERSION
        self.runtime_contract = runtime_contract
        self.score = score

    def predict(self, feature_values: dict[str, object]) -> ShadowRuntimeOutput:
        assert feature_values["currency"] == "USD"
        return ShadowRuntimeOutput(score=self.score)


def _auth_headers(
    client: TestClient,
    db: Session,
    *,
    username: str,
    role: UserRole,
) -> tuple[dict[str, str], User]:
    user = User(username=username, password_hash=hash_password(PASSWORD), role=role.value)
    db.add(user)
    db.commit()
    db.refresh(user)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, user


def _transaction_payload(identifier: str) -> dict[str, object]:
    return {
        "external_transaction_id": identifier,
        "occurred_at": "2026-08-09T08:15:00Z",
        "amount": "840.00",
        "currency": "USD",
        "account_reference": f"ACC-{identifier}",
        "merchant_reference": "MER-HYBRID",
        "merchant_category_code": "6011",
        "channel": "card_not_present",
        "source_country": "US",
        "destination_country": "CA",
    }


def _model_payload(*, kind: str, artifact_sha256: str) -> dict[str, object]:
    supervised = kind == "supervised"
    return {
        "model_key": f"hybrid-{kind}-risk",
        "version": "1.0.0",
        "kind": kind,
        "purpose": "operational",
        "runtime_contract": ("binary-probability-v1" if supervised else "anomaly-score-v1"),
        "artifact_sha256": artifact_sha256,
        "feature_set_version": FEATURE_SET_VERSION,
        "training_dataset_id": f"ODS-HYBRID-{kind.upper()}-0001",
        "training_dataset_checksum": DATASET_CHECKSUM,
        "training_data_approved": True,
        "operational_feature_compatible": True,
        "decision_threshold": "0.5",
        "evaluation_metrics": (
            {
                "average_precision": 0.71,
                "roc_auc": 0.94,
                "brier_score": 0.02,
                "recall": 0.82,
                "false_positive_rate": 0.008,
                "evaluated_row_count": 50000,
                "evaluated_positive_count": 420,
            }
            if supervised
            else {
                "training_row_count": 50000,
                "contamination": 0.01,
                "score_reference_checksum": "d" * 64,
            }
        ),
        "model_card_reference": f"docs/models/hybrid-{kind}-1.0.0.md",
        "model_card_checksum": MODEL_CARD_CHECKSUM,
    }


def _register_shadow_pair(
    client: TestClient,
    *,
    admin_headers: dict[str, str],
    evaluator_headers: dict[str, str],
) -> tuple[str, str]:
    model_ids: list[str] = []
    for kind, checksum in (("supervised", "a" * 64), ("anomaly", "e" * 64)):
        registered = client.post(
            "/api/v1/models",
            json=_model_payload(kind=kind, artifact_sha256=checksum),
            headers=admin_headers,
        )
        assert registered.status_code == 201
        model_id = str(registered.json()["model"]["id"])
        admitted = client.post(
            f"/api/v1/models/{model_id}/transitions",
            json={
                "target_status": "shadow",
                "reason": f"Independent evaluator approved {kind} hybrid evidence.",
            },
            headers=evaluator_headers,
        )
        assert admitted.status_code == 200
        model_ids.append(model_id)
    return model_ids[0], model_ids[1]


def _score_pair(
    db: Session,
    *,
    transaction_id: str,
    supervised_model_id: str,
    anomaly_model_id: str,
    supervised_score: str = "0.8",
    anomaly_score: str = "0.5",
) -> tuple[ShadowModelPrediction, ShadowModelPrediction]:
    supervised, _ = score_shadow_transaction(
        db,
        transaction_id=transaction_id,
        model_id=supervised_model_id,
        runtime=FixedShadowRuntime(
            artifact_sha256="a" * 64,
            runtime_contract=ModelRuntimeContract.BINARY_PROBABILITY,
            score=Decimal(supervised_score),
        ),
    )
    anomaly, _ = score_shadow_transaction(
        db,
        transaction_id=transaction_id,
        model_id=anomaly_model_id,
        runtime=FixedShadowRuntime(
            artifact_sha256="e" * 64,
            runtime_contract=ModelRuntimeContract.ANOMALY_SCORE,
            score=Decimal(anomaly_score),
        ),
    )
    db.commit()
    return supervised, anomaly


def _create_flagged_transaction_and_case(
    client: TestClient,
    *,
    analyst_headers: dict[str, str],
    suffix: str,
) -> tuple[str, str]:
    current_time = datetime(2026, 8, 9, 3, 30, tzinfo=UTC)
    account_reference = f"ACC-{suffix}"
    for index in range(5):
        payload = _transaction_payload(f"TX-{suffix}-H{index}")
        payload.update(
            {
                "occurred_at": (current_time - timedelta(minutes=10 * (5 - index))).isoformat(),
                "amount": "100.00",
                "account_reference": account_reference,
                "merchant_reference": "MER-BASE",
                "merchant_category_code": "5411",
                "channel": "card_present",
                "destination_country": "US",
            }
        )
        response = client.post(
            "/api/v1/transactions",
            json=payload,
            headers=analyst_headers,
        )
        assert response.status_code == 201

    target_payload = _transaction_payload(f"TX-{suffix}-FLAGGED")
    target_payload.update(
        {
            "occurred_at": current_time.isoformat(),
            "amount": "600.00",
            "account_reference": account_reference,
            "merchant_reference": "MER-NEW",
        }
    )
    target = client.post(
        "/api/v1/transactions",
        json=target_payload,
        headers=analyst_headers,
    )
    assert target.status_code == 201
    transaction_id = str(target.json()["transaction"]["id"])
    cases = client.get("/api/v1/cases", headers=analyst_headers)
    matching = [case for case in cases.json() if case["transaction"]["id"] == transaction_id]
    assert len(matching) == 1
    return transaction_id, str(matching[0]["id"])


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        ("0", "low"),
        ("39.9999", "low"),
        ("40", "medium"),
        ("69.9999", "medium"),
        ("70", "high"),
        ("100", "high"),
    ],
)
def test_hybrid_policy_band_boundaries(score: str, expected: str) -> None:
    assert DEFAULT_HYBRID_POLICY.risk_level(Decimal(score)).value == expected


def test_hybrid_score_is_versioned_replay_safe_and_non_interventional(
    client: TestClient,
    db_session: Session,
) -> None:
    admin_headers, _ = _auth_headers(
        client, db_session, username="hybrid-admin", role=UserRole.ADMINISTRATOR
    )
    evaluator_headers, _ = _auth_headers(
        client, db_session, username="hybrid-evaluator", role=UserRole.EVALUATOR
    )
    analyst_headers, _ = _auth_headers(
        client, db_session, username="hybrid-analyst", role=UserRole.ANALYST
    )
    transaction = client.post(
        "/api/v1/transactions",
        json=_transaction_payload("TX-HYBRID-001"),
        headers=analyst_headers,
    )
    transaction_id = str(transaction.json()["transaction"]["id"])
    supervised_model_id, anomaly_model_id = _register_shadow_pair(
        client,
        admin_headers=admin_headers,
        evaluator_headers=evaluator_headers,
    )
    supervised, anomaly = _score_pair(
        db_session,
        transaction_id=transaction_id,
        supervised_model_id=supervised_model_id,
        anomaly_model_id=anomaly_model_id,
    )
    rule_before = db_session.scalar(
        select(TransactionRuleAssessment).where(
            TransactionRuleAssessment.transaction_id == transaction_id
        )
    )
    assert rule_before is not None
    rule_checksum_before = rule_before.assessment_checksum
    case_count_before = db_session.scalar(select(func.count()).select_from(AnalystCase))
    payload = {
        "supervised_prediction_id": supervised.id,
        "anomaly_prediction_id": anomaly.id,
    }

    denied = client.post(
        f"/api/v1/transactions/{transaction_id}/hybrid-assessments",
        json=payload,
        headers=analyst_headers,
    )
    created = client.post(
        f"/api/v1/transactions/{transaction_id}/hybrid-assessments",
        json=payload,
        headers=evaluator_headers,
    )
    replayed = client.post(
        f"/api/v1/transactions/{transaction_id}/hybrid-assessments",
        json=payload,
        headers=admin_headers,
    )
    listed = client.get(
        f"/api/v1/transactions/{transaction_id}/hybrid-assessments",
        headers=analyst_headers,
    )

    assert denied.status_code == 403
    assert created.status_code == 201
    body = created.json()
    assert body["created"] is True
    assert body["assessment"]["policy_version"] == "hybrid-risk-v1.0.0"
    assert body["assessment"]["weights"] == {
        "rules": "0.2",
        "supervised": "0.6",
        "anomaly": "0.2",
    }
    assert body["assessment"]["combined_score"] == "63"
    assert body["assessment"]["risk_level"] == "medium"
    assert body["assessment"]["components"]["rules"]["contribution_points"] == "5"
    assert body["assessment"]["components"]["supervised"]["contribution_points"] == "48"
    assert body["assessment"]["components"]["anomaly"]["contribution_points"] == "10"
    assert body["assessment"]["integrity_verified"] is True
    assert body["assessment"]["decision_support_only"] is True
    assert body["assessment"]["shadow_inputs_only"] is True
    assert body["assessment"]["affects_case_priority"] is False
    assert body["assessment"]["affects_transaction_action"] is False
    assert body["assessment"]["llm_influenced_score"] is False
    assert body["assessment"]["evidence"]["limitations"]["missing_input_behavior"] == (
        "fail_closed"
    )
    assert body["assessment"]["evidence"]["lineage"]["supervised"]["model_kind"] == ("supervised")
    assert (
        body["assessment"]["evidence"]["lineage"]["supervised"]["prediction_checksum"]
        == supervised.prediction_checksum
    )
    assert body["assessment"]["evidence"]["lineage"]["anomaly"]["model_kind"] == ("anomaly")
    assert body["assessment"]["created_by"] == "hybrid-evaluator"
    assert replayed.status_code == 200
    assert replayed.json()["created"] is False
    assert replayed.json()["assessment"]["id"] == body["assessment"]["id"]
    assert listed.status_code == 200
    assert listed.json() == [body["assessment"]]
    assert db_session.scalar(select(func.count()).select_from(HybridRiskAssessment)) == 1
    assert db_session.scalar(select(func.count()).select_from(ShadowModelPrediction)) == 2
    assert db_session.scalar(select(func.count()).select_from(TransactionRuleAssessment)) == 1
    assert case_count_before == 0
    assert db_session.scalar(select(func.count()).select_from(AnalystCase)) == case_count_before
    rule_after = db_session.get(TransactionRuleAssessment, rule_before.id)
    assert rule_after is not None
    assert rule_after.assessment_checksum == rule_checksum_before


def test_hybrid_score_fails_closed_for_missing_mismatched_and_tampered_evidence(
    client: TestClient,
    db_session: Session,
) -> None:
    admin_headers, _ = _auth_headers(
        client, db_session, username="closed-admin", role=UserRole.ADMINISTRATOR
    )
    evaluator_headers, _ = _auth_headers(
        client, db_session, username="closed-evaluator", role=UserRole.EVALUATOR
    )
    analyst_headers, _ = _auth_headers(
        client, db_session, username="closed-analyst", role=UserRole.ANALYST
    )
    transaction_ids: list[str] = []
    for suffix in ("001", "002"):
        transaction = client.post(
            "/api/v1/transactions",
            json=_transaction_payload(f"TX-CLOSED-{suffix}"),
            headers=analyst_headers,
        )
        transaction_ids.append(str(transaction.json()["transaction"]["id"]))
    supervised_model_id, anomaly_model_id = _register_shadow_pair(
        client,
        admin_headers=admin_headers,
        evaluator_headers=evaluator_headers,
    )
    supervised_one, _ = _score_pair(
        db_session,
        transaction_id=transaction_ids[0],
        supervised_model_id=supervised_model_id,
        anomaly_model_id=anomaly_model_id,
    )
    _, anomaly_two = _score_pair(
        db_session,
        transaction_id=transaction_ids[1],
        supervised_model_id=supervised_model_id,
        anomaly_model_id=anomaly_model_id,
    )

    missing = client.post(
        f"/api/v1/transactions/{transaction_ids[0]}/hybrid-assessments",
        json={
            "supervised_prediction_id": "missing",
            "anomaly_prediction_id": anomaly_two.id,
        },
        headers=evaluator_headers,
    )
    wrong_kind = client.post(
        f"/api/v1/transactions/{transaction_ids[0]}/hybrid-assessments",
        json={
            "supervised_prediction_id": anomaly_two.id,
            "anomaly_prediction_id": supervised_one.id,
        },
        headers=evaluator_headers,
    )
    mismatched = client.post(
        f"/api/v1/transactions/{transaction_ids[0]}/hybrid-assessments",
        json={
            "supervised_prediction_id": supervised_one.id,
            "anomaly_prediction_id": anomaly_two.id,
        },
        headers=evaluator_headers,
    )
    supervised_one.score = Decimal("0.1")
    db_session.commit()
    tampered = client.post(
        f"/api/v1/transactions/{transaction_ids[0]}/hybrid-assessments",
        json={
            "supervised_prediction_id": supervised_one.id,
            "anomaly_prediction_id": anomaly_two.id,
        },
        headers=evaluator_headers,
    )

    assert missing.status_code == 404
    assert "Supervised prediction not found" in missing.json()["detail"]
    assert wrong_kind.status_code == 409
    assert "not from a supervised model" in wrong_kind.json()["detail"]
    assert mismatched.status_code == 409
    assert "another transaction" in mismatched.json()["detail"]
    assert tampered.status_code == 409
    assert "integrity verification failed" in tampered.json()["detail"]
    assert db_session.scalar(select(func.count()).select_from(HybridRiskAssessment)) == 0


def test_hybrid_assessment_checksum_detects_record_tampering(
    client: TestClient,
    db_session: Session,
) -> None:
    admin_headers, _ = _auth_headers(
        client, db_session, username="integrity-hybrid-admin", role=UserRole.ADMINISTRATOR
    )
    evaluator_headers, _ = _auth_headers(
        client, db_session, username="integrity-hybrid-eval", role=UserRole.EVALUATOR
    )
    analyst_headers, _ = _auth_headers(
        client, db_session, username="integrity-hybrid-reader", role=UserRole.ANALYST
    )
    transaction = client.post(
        "/api/v1/transactions",
        json=_transaction_payload("TX-HYBRID-INTEGRITY"),
        headers=analyst_headers,
    )
    transaction_id = str(transaction.json()["transaction"]["id"])
    supervised_model_id, anomaly_model_id = _register_shadow_pair(
        client,
        admin_headers=admin_headers,
        evaluator_headers=evaluator_headers,
    )
    supervised, anomaly = _score_pair(
        db_session,
        transaction_id=transaction_id,
        supervised_model_id=supervised_model_id,
        anomaly_model_id=anomaly_model_id,
    )
    created = client.post(
        f"/api/v1/transactions/{transaction_id}/hybrid-assessments",
        json={
            "supervised_prediction_id": supervised.id,
            "anomaly_prediction_id": anomaly.id,
        },
        headers=evaluator_headers,
    )
    assessment = db_session.get(HybridRiskAssessment, created.json()["assessment"]["id"])
    assert assessment is not None
    assessment.combined_score = Decimal("12.3456")
    db_session.commit()

    listed = client.get(
        f"/api/v1/transactions/{transaction_id}/hybrid-assessments",
        headers=analyst_headers,
    )
    unauthenticated = client.get(f"/api/v1/transactions/{transaction_id}/hybrid-assessments")

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()[0]["integrity_verified"] is False
    assert unauthenticated.status_code == 401


def test_case_detail_reads_hybrid_evidence_without_mutating_case(
    client: TestClient,
    db_session: Session,
) -> None:
    admin_headers, _ = _auth_headers(
        client, db_session, username="case-hybrid-admin", role=UserRole.ADMINISTRATOR
    )
    evaluator_headers, _ = _auth_headers(
        client, db_session, username="case-hybrid-evaluator", role=UserRole.EVALUATOR
    )
    analyst_headers, _ = _auth_headers(
        client, db_session, username="case-hybrid-analyst", role=UserRole.ANALYST
    )
    supervised_model_id, anomaly_model_id = _register_shadow_pair(
        client,
        admin_headers=admin_headers,
        evaluator_headers=evaluator_headers,
    )
    transaction_id, case_id = _create_flagged_transaction_and_case(
        client,
        analyst_headers=analyst_headers,
        suffix="HYBRID-CASE",
    )
    supervised, anomaly = _score_pair(
        db_session,
        transaction_id=transaction_id,
        supervised_model_id=supervised_model_id,
        anomaly_model_id=anomaly_model_id,
    )
    before = client.get(f"/api/v1/cases/{case_id}", headers=analyst_headers)
    created = client.post(
        f"/api/v1/transactions/{transaction_id}/hybrid-assessments",
        json={
            "supervised_prediction_id": supervised.id,
            "anomaly_prediction_id": anomaly.id,
        },
        headers=evaluator_headers,
    )
    after = client.get(f"/api/v1/cases/{case_id}", headers=analyst_headers)

    assert before.status_code == 200
    assert before.json()["hybrid_assessments"] == []
    assert created.status_code == 201
    assert created.json()["assessment"]["combined_score"] == "78"
    assert created.json()["assessment"]["risk_level"] == "high"
    assert after.status_code == 200
    assert len(after.json()["hybrid_assessments"]) == 1
    assert after.json()["hybrid_assessments"][0]["id"] == created.json()["assessment"]["id"]
    assert after.json()["priority"] == before.json()["priority"] == "urgent"
    assert after.json()["status"] == before.json()["status"] == "open"
    assert after.json()["opening_checksum"] == before.json()["opening_checksum"]
    assert after.json()["events"] == before.json()["events"]
    assert db_session.scalar(select(func.count()).select_from(AnalystCase)) == 1
