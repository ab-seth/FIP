from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fip_api.core.security import hash_password
from fip_api.model_registry import ShadowRuntimeOutput, score_shadow_transaction
from fip_api.models import (
    ModelRuntimeContract,
    ShadowModelEvaluationReport,
    ShadowModelPrediction,
    User,
    UserRole,
)

PASSWORD = "strong-password"
ARTIFACT_CHECKSUM = "e" * 64
DATASET_CHECKSUM = "f" * 64
MODEL_CARD_CHECKSUM = "1" * 64


class EvaluationRuntime:
    artifact_sha256 = ARTIFACT_CHECKSUM
    feature_set_version = "semantic-transaction-v1.0.0"
    runtime_contract = ModelRuntimeContract.BINARY_PROBABILITY

    def __init__(self, score: Decimal) -> None:
        self.score = score

    def predict(self, feature_values: dict[str, object]) -> ShadowRuntimeOutput:
        assert "amount" in feature_values
        return ShadowRuntimeOutput(score=self.score)


def _auth_headers(
    client: TestClient,
    db: Session,
    *,
    username: str,
    role: UserRole,
) -> dict[str, str]:
    user = User(username=username, password_hash=hash_password(PASSWORD), role=role.value)
    db.add(user)
    db.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _model_payload() -> dict[str, object]:
    return {
        "model_key": "shadow-evaluation-model",
        "version": "1.0.0",
        "kind": "supervised",
        "purpose": "operational",
        "runtime_contract": "binary-probability-v1",
        "artifact_sha256": ARTIFACT_CHECKSUM,
        "feature_set_version": "semantic-transaction-v1.0.0",
        "training_dataset_id": "approved-partner-labels",
        "training_dataset_checksum": DATASET_CHECKSUM,
        "training_data_approved": True,
        "operational_feature_compatible": True,
        "decision_threshold": "0.70",
        "evaluation_metrics": {
            "average_precision": 0.72,
            "roc_auc": 0.93,
            "brier_score": 0.03,
            "recall": 0.81,
            "false_positive_rate": 0.009,
            "evaluated_row_count": 60000,
            "evaluated_positive_count": 480,
        },
        "model_card_reference": "docs/models/shadow-evaluation-model-1.0.0.md",
        "model_card_checksum": MODEL_CARD_CHECKSUM,
    }


def _register_shadow_model(
    client: TestClient,
    admin_headers: dict[str, str],
    evaluator_headers: dict[str, str],
) -> str:
    registered = client.post("/api/v1/models", json=_model_payload(), headers=admin_headers)
    assert registered.status_code == 201
    model_id = str(registered.json()["model"]["id"])
    admitted = client.post(
        f"/api/v1/models/{model_id}/transitions",
        json={
            "target_status": "shadow",
            "reason": "Independent evaluator approved monitoring-only shadow execution.",
        },
        headers=evaluator_headers,
    )
    assert admitted.status_code == 200
    return model_id


def _transaction_payload(
    *,
    external_id: str,
    occurred_at: datetime,
    account_reference: str,
    elevated: bool,
) -> dict[str, object]:
    return {
        "external_transaction_id": external_id,
        "occurred_at": occurred_at.isoformat(),
        "amount": "850.00" if elevated else "45.00",
        "currency": "USD",
        "account_reference": account_reference,
        "merchant_reference": f"MER-{external_id}",
        "merchant_category_code": "6011" if elevated else "5411",
        "channel": "card_not_present" if elevated else "card_present",
        "source_country": "US",
        "destination_country": "CA" if elevated else "US",
    }


def _create_prediction(
    client: TestClient,
    db: Session,
    *,
    analyst_headers: dict[str, str],
    model_id: str,
    transaction_payload: dict[str, object],
    score: Decimal,
) -> None:
    created = client.post(
        "/api/v1/transactions",
        json=transaction_payload,
        headers=analyst_headers,
    )
    assert created.status_code == 201
    prediction, prediction_created = score_shadow_transaction(
        db,
        transaction_id=str(created.json()["transaction"]["id"]),
        model_id=model_id,
        runtime=EvaluationRuntime(score),
    )
    assert prediction_created is True
    assert prediction.id is not None
    db.commit()


def _evaluation_payload() -> dict[str, str]:
    return {
        "baseline_window_start": "2026-07-01T00:00:00Z",
        "baseline_window_end": "2026-07-22T00:00:00Z",
        "evaluation_window_start": "2026-08-01T00:00:00Z",
        "evaluation_window_end": "2026-08-02T00:00:00Z",
    }


def test_shadow_evaluation_is_replay_safe_and_detects_drift_and_tampering(
    client: TestClient,
    db_session: Session,
) -> None:
    admin_headers = _auth_headers(
        client,
        db_session,
        username="evaluation-admin",
        role=UserRole.ADMINISTRATOR,
    )
    evaluator_headers = _auth_headers(
        client,
        db_session,
        username="evaluation-evaluator",
        role=UserRole.EVALUATOR,
    )
    analyst_headers = _auth_headers(
        client,
        db_session,
        username="evaluation-analyst",
        role=UserRole.ANALYST,
    )
    model_id = _register_shadow_model(client, admin_headers, evaluator_headers)

    baseline_start = datetime(2026, 7, 1, 12, tzinfo=UTC)
    for index in range(20):
        _create_prediction(
            client,
            db_session,
            analyst_headers=analyst_headers,
            model_id=model_id,
            transaction_payload=_transaction_payload(
                external_id=f"TX-BASELINE-{index:02d}",
                occurred_at=baseline_start + timedelta(days=index),
                account_reference=f"ACC-BASELINE-{index:02d}",
                elevated=False,
            ),
            score=Decimal("0.10") + Decimal(index) / Decimal("200"),
        )

    evaluation_start = datetime(2026, 8, 1, 2, tzinfo=UTC)
    for index in range(20):
        _create_prediction(
            client,
            db_session,
            analyst_headers=analyst_headers,
            model_id=model_id,
            transaction_payload=_transaction_payload(
                external_id=f"TX-EVALUATION-{index:02d}",
                occurred_at=evaluation_start + timedelta(minutes=index),
                account_reference="ACC-EVALUATION-SHARED",
                elevated=True,
            ),
            score=Decimal("0.80") + Decimal(index) / Decimal("200"),
        )

    denied = client.post(
        f"/api/v1/models/{model_id}/evaluations",
        json=_evaluation_payload(),
        headers=analyst_headers,
    )
    created = client.post(
        f"/api/v1/models/{model_id}/evaluations",
        json=_evaluation_payload(),
        headers=evaluator_headers,
    )
    replayed = client.post(
        f"/api/v1/models/{model_id}/evaluations",
        json=_evaluation_payload(),
        headers=evaluator_headers,
    )
    listed = client.get(
        f"/api/v1/models/{model_id}/evaluations",
        headers=analyst_headers,
    )

    assert denied.status_code == 403
    assert created.status_code == 201
    assert created.json()["created"] is True
    report = created.json()["report"]
    assert report["baseline_prediction_count"] == 20
    assert report["evaluation_prediction_count"] == 20
    assert report["integrity_verified"] is True
    assert report["monitoring_only"] is True
    assert report["affects_operational_score"] is False
    assert report["triggers_automatic_action"] is False
    assert report["metrics"]["baseline"]["model_threshold_exceedance_rate"] == "0"
    assert report["metrics"]["evaluation"]["model_threshold_exceedance_rate"] == "1"
    assert report["metrics"]["score_drift"]["status"] == "material"
    assert report["metrics"]["interpretation"] == {
        "comparison_only": True,
        "deterministic_rules_are_not_ground_truth_labels": True,
        "monitoring_result_changes_model_lifecycle": False,
        "monitoring_result_triggers_automatic_action": False,
    }
    assert replayed.status_code == 200
    assert replayed.json()["created"] is False
    assert replayed.json()["report"]["id"] == report["id"]
    assert listed.status_code == 200
    assert listed.json()[0]["report_checksum"] == report["report_checksum"]
    assert db_session.scalar(select(func.count()).select_from(ShadowModelEvaluationReport)) == 1

    prediction = db_session.scalar(
        select(ShadowModelPrediction).order_by(ShadowModelPrediction.created_at)
    )
    assert prediction is not None
    prediction.score = Decimal("0.99")
    db_session.commit()
    tampered = client.get(
        f"/api/v1/models/{model_id}/evaluations",
        headers=analyst_headers,
    )
    assert tampered.status_code == 200
    assert tampered.json()[0]["integrity_verified"] is False


def test_shadow_evaluation_requires_valid_windows_and_minimum_evidence(
    client: TestClient,
    db_session: Session,
) -> None:
    admin_headers = _auth_headers(
        client,
        db_session,
        username="minimum-admin",
        role=UserRole.ADMINISTRATOR,
    )
    evaluator_headers = _auth_headers(
        client,
        db_session,
        username="minimum-evaluator",
        role=UserRole.EVALUATOR,
    )
    model_id = _register_shadow_model(client, admin_headers, evaluator_headers)

    insufficient = client.post(
        f"/api/v1/models/{model_id}/evaluations",
        json=_evaluation_payload(),
        headers=evaluator_headers,
    )
    overlapping = client.post(
        f"/api/v1/models/{model_id}/evaluations",
        json={
            **_evaluation_payload(),
            "baseline_window_end": "2026-08-01T12:00:00Z",
        },
        headers=evaluator_headers,
    )

    assert insufficient.status_code == 409
    assert "at least 20 verified predictions" in insufficient.json()["detail"]
    assert overlapping.status_code == 422


def test_shadow_evaluation_reads_require_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/models/missing/evaluations")

    assert response.status_code == 401
