from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fip_api.core.security import hash_password
from fip_api.model_registry import (
    GovernanceViolation,
    ShadowFactor,
    ShadowRuntimeMismatch,
    ShadowRuntimeOutput,
    score_shadow_transaction,
)
from fip_api.models import (
    ModelLifecycleEvent,
    ModelRuntimeContract,
    ShadowModelPrediction,
    TransactionRuleAssessment,
    User,
    UserRole,
)

PASSWORD = "strong-password"
ARTIFACT_CHECKSUM = "a" * 64
DATASET_CHECKSUM = "b" * 64
MODEL_CARD_CHECKSUM = "c" * 64


class StubShadowRuntime:
    artifact_sha256 = ARTIFACT_CHECKSUM
    feature_set_version = "semantic-transaction-v1.0.0"
    runtime_contract = ModelRuntimeContract.BINARY_PROBABILITY

    def __init__(self, output: ShadowRuntimeOutput) -> None:
        self.output = output

    def predict(self, feature_values: dict[str, object]) -> ShadowRuntimeOutput:
        assert feature_values["currency"] == "USD"
        return self.output


def auth_headers(
    client: TestClient,
    db: Session,
    *,
    username: str,
    role: UserRole,
) -> tuple[dict[str, str], User]:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        role=role.value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, user


def model_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "model_key": "canonical-fraud-risk",
        "version": "1.0.0",
        "kind": "supervised",
        "purpose": "operational",
        "runtime_contract": "binary-probability-v1",
        "artifact_sha256": ARTIFACT_CHECKSUM,
        "feature_set_version": "semantic-transaction-v1.0.0",
        "training_dataset_id": "partner-labels-2026-q3",
        "training_dataset_checksum": DATASET_CHECKSUM,
        "training_data_approved": True,
        "operational_feature_compatible": True,
        "decision_threshold": "0.70",
        "evaluation_metrics": {
            "average_precision": 0.71,
            "roc_auc": 0.94,
            "brier_score": 0.02,
            "recall": 0.82,
            "false_positive_rate": 0.008,
            "evaluated_row_count": 50000,
            "evaluated_positive_count": 420,
        },
        "model_card_reference": "docs/models/canonical-fraud-risk-1.0.0.md",
        "model_card_checksum": MODEL_CARD_CHECKSUM,
    }
    payload.update(overrides)
    return payload


def transaction_payload() -> dict[str, object]:
    return {
        "external_transaction_id": "TX-SHADOW-001",
        "occurred_at": "2026-08-09T08:15:00Z",
        "amount": "840.00",
        "currency": "USD",
        "account_reference": "ACC-SHADOW",
        "merchant_reference": "MER-SHADOW",
        "merchant_category_code": "5734",
        "channel": "card_not_present",
        "source_country": "US",
        "destination_country": "CA",
    }


def register_and_admit_shadow(
    client: TestClient,
    admin_headers: dict[str, str],
    evaluator_headers: dict[str, str],
) -> str:
    registered = client.post("/api/v1/models", json=model_payload(), headers=admin_headers)
    assert registered.status_code == 201
    model_id = registered.json()["model"]["id"]
    admitted = client.post(
        f"/api/v1/models/{model_id}/transitions",
        json={
            "target_status": "shadow",
            "reason": "Independent evaluator approved shadow-only comparison.",
        },
        headers=evaluator_headers,
    )
    assert admitted.status_code == 200
    return str(model_id)


def test_model_registration_is_replay_safe_and_shadow_requires_independent_evaluator(
    client: TestClient,
    db_session: Session,
) -> None:
    admin_headers, _ = auth_headers(
        client,
        db_session,
        username="registry-admin",
        role=UserRole.ADMINISTRATOR,
    )
    evaluator_headers, _ = auth_headers(
        client,
        db_session,
        username="model-evaluator",
        role=UserRole.EVALUATOR,
    )
    analyst_headers, _ = auth_headers(
        client,
        db_session,
        username="model-reader",
        role=UserRole.ANALYST,
    )

    registered = client.post("/api/v1/models", json=model_payload(), headers=admin_headers)
    replayed = client.post("/api/v1/models", json=model_payload(), headers=admin_headers)
    model_id = registered.json()["model"]["id"]
    denied_registration = client.post(
        "/api/v1/models",
        json={**model_payload(), "version": "1.0.1"},
        headers=analyst_headers,
    )
    denied_admission = client.post(
        f"/api/v1/models/{model_id}/transitions",
        json={
            "target_status": "shadow",
            "reason": "Registrant attempted to approve the same model.",
        },
        headers=admin_headers,
    )
    admitted = client.post(
        f"/api/v1/models/{model_id}/transitions",
        json={
            "target_status": "shadow",
            "reason": "Independent evaluator approved shadow-only comparison.",
        },
        headers=evaluator_headers,
    )
    listed = client.get("/api/v1/models", headers=analyst_headers)

    assert registered.status_code == 201
    assert registered.json()["created"] is True
    assert registered.json()["model"]["current_status"] == "candidate"
    assert replayed.status_code == 200
    assert replayed.json()["created"] is False
    assert replayed.json()["model"]["id"] == model_id
    assert denied_registration.status_code == 403
    assert denied_admission.status_code == 409
    assert "evaluator must authorize" in denied_admission.json()["detail"]
    assert admitted.status_code == 200
    assert admitted.json()["current_status"] == "shadow"
    assert admitted.json()["lineage_verified"] is True
    assert len(admitted.json()["lifecycle"]) == 2
    assert (
        admitted.json()["lifecycle"][1]["previous_event_checksum"]
        == (admitted.json()["lifecycle"][0]["event_checksum"])
    )
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == model_id

    shadow_event = db_session.scalar(
        select(ModelLifecycleEvent).where(ModelLifecycleEvent.sequence_number == 2)
    )
    assert shadow_event is not None
    shadow_event.reason = "Tampered lifecycle reason"
    db_session.commit()
    tampered = client.get(f"/api/v1/models/{model_id}", headers=analyst_headers)
    assert tampered.status_code == 200
    assert tampered.json()["lineage_verified"] is False


def test_research_and_incomplete_models_are_blocked_from_shadow(
    client: TestClient,
    db_session: Session,
) -> None:
    admin_headers, _ = auth_headers(
        client,
        db_session,
        username="gate-admin",
        role=UserRole.ADMINISTRATOR,
    )
    evaluator_headers, _ = auth_headers(
        client,
        db_session,
        username="gate-evaluator",
        role=UserRole.EVALUATOR,
    )
    research_payload = model_payload(
        model_key="ulb-research-benchmark",
        purpose="research",
        feature_set_version="ulb-pca-v1",
        training_data_approved=False,
        operational_feature_compatible=False,
    )
    registered = client.post("/api/v1/models", json=research_payload, headers=admin_headers)
    model_id = registered.json()["model"]["id"]

    blocked = client.post(
        f"/api/v1/models/{model_id}/transitions",
        json={
            "target_status": "shadow",
            "reason": "Evaluate whether research evidence can enter shadow.",
        },
        headers=evaluator_headers,
    )
    rejected = client.post(
        f"/api/v1/models/{model_id}/transitions",
        json={
            "target_status": "rejected",
            "reason": "Research PCA features cannot support canonical inference.",
        },
        headers=evaluator_headers,
    )
    invalid_contract = client.post(
        "/api/v1/models",
        json={
            **model_payload(model_key="wrong-runtime"),
            "runtime_contract": "anomaly-score-v1",
        },
        headers=admin_headers,
    )

    assert blocked.status_code == 409
    assert "research-purpose models" in blocked.json()["detail"]
    assert "feature compatibility" in blocked.json()["detail"]
    assert rejected.status_code == 200
    assert rejected.json()["current_status"] == "rejected"
    assert invalid_contract.status_code == 422
    assert "binary-probability-v1" in invalid_contract.json()["detail"]


def test_anomaly_model_uses_separate_evidence_contract(
    client: TestClient,
    db_session: Session,
) -> None:
    admin_headers, _ = auth_headers(
        client,
        db_session,
        username="anomaly-admin",
        role=UserRole.ADMINISTRATOR,
    )
    evaluator_headers, _ = auth_headers(
        client,
        db_session,
        username="anomaly-evaluator",
        role=UserRole.EVALUATOR,
    )
    anomaly_payload = model_payload(
        model_key="canonical-account-anomaly",
        kind="anomaly",
        runtime_contract="anomaly-score-v1",
        decision_threshold="0.97",
        evaluation_metrics={
            "training_row_count": 125000,
            "contamination": 0.002,
            "score_reference_checksum": "d" * 64,
        },
    )
    registered = client.post("/api/v1/models", json=anomaly_payload, headers=admin_headers)
    model_id = registered.json()["model"]["id"]
    admitted = client.post(
        f"/api/v1/models/{model_id}/transitions",
        json={
            "target_status": "shadow",
            "reason": "Evaluator approved anomaly score comparison in shadow.",
        },
        headers=evaluator_headers,
    )

    assert registered.status_code == 201
    assert registered.json()["model"]["kind"] == "anomaly"
    assert admitted.status_code == 200
    assert admitted.json()["current_status"] == "shadow"
    assert admitted.json()["lineage_verified"] is True


def test_shadow_prediction_is_immutable_explainable_and_does_not_change_rule_score(
    client: TestClient,
    db_session: Session,
) -> None:
    admin_headers, _ = auth_headers(
        client,
        db_session,
        username="prediction-admin",
        role=UserRole.ADMINISTRATOR,
    )
    evaluator_headers, _ = auth_headers(
        client,
        db_session,
        username="prediction-evaluator",
        role=UserRole.EVALUATOR,
    )
    analyst_headers, _ = auth_headers(
        client,
        db_session,
        username="prediction-analyst",
        role=UserRole.ANALYST,
    )
    created_transaction = client.post(
        "/api/v1/transactions",
        json=transaction_payload(),
        headers=analyst_headers,
    )
    transaction_id = created_transaction.json()["transaction"]["id"]
    before = client.get(
        f"/api/v1/transactions/{transaction_id}/rule-assessment",
        headers=analyst_headers,
    ).json()
    model_id = register_and_admit_shadow(client, admin_headers, evaluator_headers)
    runtime = StubShadowRuntime(
        ShadowRuntimeOutput(
            score=Decimal("0.82"),
            factors=(
                ShadowFactor("amount", Decimal("0.41"), "increases_risk"),
                ShadowFactor("is_cross_border", Decimal("0.18"), "increases_risk"),
            ),
        )
    )

    prediction, created = score_shadow_transaction(
        db_session,
        transaction_id=transaction_id,
        model_id=model_id,
        runtime=runtime,
    )
    db_session.commit()
    replayed, replay_created = score_shadow_transaction(
        db_session,
        transaction_id=transaction_id,
        model_id=model_id,
        runtime=runtime,
    )
    after = client.get(
        f"/api/v1/transactions/{transaction_id}/rule-assessment",
        headers=analyst_headers,
    ).json()
    response = client.get(
        f"/api/v1/transactions/{transaction_id}/shadow-predictions",
        headers=analyst_headers,
    )

    assert created_transaction.status_code == 201
    assert created is True
    assert replay_created is False
    assert replayed.id == prediction.id
    assert response.status_code == 200
    assert response.json()[0]["score"] == "0.82"
    assert response.json()[0]["threshold"] == "0.7"
    assert response.json()[0]["would_exceed_model_threshold"] is True
    assert response.json()[0]["integrity_verified"] is True
    assert response.json()[0]["shadow_only"] is True
    assert response.json()[0]["affects_operational_score"] is False
    assert [factor["feature"] for factor in response.json()[0]["factors"]] == [
        "amount",
        "is_cross_border",
    ]
    assert before["assessment_checksum"] == after["assessment_checksum"]
    assert before["rule_score"] == after["rule_score"]
    assert db_session.scalar(select(func.count()).select_from(ShadowModelPrediction)) == 1
    assert db_session.scalar(select(func.count()).select_from(TransactionRuleAssessment)) == 1


def test_shadow_runtime_and_status_mismatches_are_rejected(
    client: TestClient,
    db_session: Session,
) -> None:
    admin_headers, _ = auth_headers(
        client,
        db_session,
        username="runtime-admin",
        role=UserRole.ADMINISTRATOR,
    )
    evaluator_headers, _ = auth_headers(
        client,
        db_session,
        username="runtime-evaluator",
        role=UserRole.EVALUATOR,
    )
    analyst_headers, _ = auth_headers(
        client,
        db_session,
        username="runtime-analyst",
        role=UserRole.ANALYST,
    )
    transaction = client.post(
        "/api/v1/transactions",
        json=transaction_payload(),
        headers=analyst_headers,
    )
    transaction_id = transaction.json()["transaction"]["id"]
    registered = client.post("/api/v1/models", json=model_payload(), headers=admin_headers)
    model_id = registered.json()["model"]["id"]
    valid_output = ShadowRuntimeOutput(score=Decimal("0.40"))

    with pytest.raises(GovernanceViolation, match="shadow status"):
        score_shadow_transaction(
            db_session,
            transaction_id=transaction_id,
            model_id=model_id,
            runtime=StubShadowRuntime(valid_output),
        )

    transition = client.post(
        f"/api/v1/models/{model_id}/transitions",
        json={
            "target_status": "shadow",
            "reason": "Independent evaluator approved runtime validation.",
        },
        headers=evaluator_headers,
    )
    assert transition.status_code == 200
    mismatched = StubShadowRuntime(valid_output)
    mismatched.artifact_sha256 = "d" * 64
    with pytest.raises(ShadowRuntimeMismatch, match="artifact checksum"):
        score_shadow_transaction(
            db_session,
            transaction_id=transaction_id,
            model_id=model_id,
            runtime=mismatched,
        )
    with pytest.raises(ShadowRuntimeMismatch, match="between 0 and 1"):
        score_shadow_transaction(
            db_session,
            transaction_id=transaction_id,
            model_id=model_id,
            runtime=StubShadowRuntime(ShadowRuntimeOutput(score=Decimal("1.1"))),
        )
    with pytest.raises(ShadowRuntimeMismatch, match="not in the feature snapshot"):
        score_shadow_transaction(
            db_session,
            transaction_id=transaction_id,
            model_id=model_id,
            runtime=StubShadowRuntime(
                ShadowRuntimeOutput(
                    score=Decimal("0.5"),
                    factors=(ShadowFactor("ulb_v14", Decimal("0.2"), "increases_risk"),),
                )
            ),
        )
    assert db_session.scalar(select(func.count()).select_from(ShadowModelPrediction)) == 0


def test_prediction_checksum_detects_record_tampering(
    client: TestClient,
    db_session: Session,
) -> None:
    admin_headers, _ = auth_headers(
        client,
        db_session,
        username="integrity-admin",
        role=UserRole.ADMINISTRATOR,
    )
    evaluator_headers, _ = auth_headers(
        client,
        db_session,
        username="integrity-evaluator",
        role=UserRole.EVALUATOR,
    )
    analyst_headers, _ = auth_headers(
        client,
        db_session,
        username="integrity-analyst",
        role=UserRole.ANALYST,
    )
    transaction = client.post(
        "/api/v1/transactions",
        json=transaction_payload(),
        headers=analyst_headers,
    )
    transaction_id = transaction.json()["transaction"]["id"]
    model_id = register_and_admit_shadow(client, admin_headers, evaluator_headers)
    prediction, _ = score_shadow_transaction(
        db_session,
        transaction_id=transaction_id,
        model_id=model_id,
        runtime=StubShadowRuntime(ShadowRuntimeOutput(score=Decimal("0.63"))),
    )
    db_session.commit()
    prediction.score = Decimal("0.12")
    db_session.commit()

    response = client.get(
        f"/api/v1/transactions/{transaction_id}/shadow-predictions",
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert response.json()[0]["integrity_verified"] is False


def test_shadow_prediction_read_requires_authentication(client: TestClient) -> None:
    missing_auth = client.get("/api/v1/transactions/missing/shadow-predictions")

    assert missing_auth.status_code == 401
