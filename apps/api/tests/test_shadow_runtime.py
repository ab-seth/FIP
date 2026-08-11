from __future__ import annotations

import hashlib
import io
from pathlib import Path

import joblib
import numpy as np
from fastapi.testclient import TestClient
from sklearn.ensemble import IsolationForest  # type: ignore[import-untyped]
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fip_api.core.security import hash_password
from fip_api.features import FEATURE_SET_VERSION
from fip_api.main import app
from fip_api.model_runtime import ModelArtifactStore, get_model_artifact_store
from fip_api.models import (
    ShadowModelPrediction,
    TransactionFeatureSnapshot,
    TransactionRuleAssessment,
    User,
    UserRole,
)
from fip_api.operational_ml.models import AnomalyModelArtifact
from fip_api.operational_ml.preprocessing import OperationalPreprocessor
from fip_api.training_datasets.service import TRAINING_FEATURE_NAMES

PASSWORD = "strong-password"
DATASET_CHECKSUM = "b" * 64
MODEL_CARD_CHECKSUM = "c" * 64


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


def _transaction_payload(identifier: str, amount: str) -> dict[str, object]:
    return {
        "external_transaction_id": identifier,
        "occurred_at": "2026-08-09T08:15:00Z",
        "amount": amount,
        "currency": "USD",
        "account_reference": f"ACC-{identifier}",
        "merchant_reference": "MER-SHADOW",
        "merchant_category_code": "5734",
        "channel": "card_not_present",
        "source_country": "US",
        "destination_country": "CA",
    }


def _artifact_bytes(feature_values: dict[str, object], *, dataset_checksum: str) -> bytes:
    rows: list[dict[str, object]] = []
    for index in range(24):
        row = {name: feature_values[name] for name in TRAINING_FEATURE_NAMES}
        row["amount"] = float(str(feature_values["amount"])) + (index * 25)
        row["occurred_hour_utc"] = index % 24
        row["prior_transaction_count_24h"] = index
        rows.append(row)
    preprocessor = OperationalPreprocessor().fit(rows)
    encoded = preprocessor.transform(rows)
    estimator = IsolationForest(n_estimators=20, contamination=0.1, random_state=17, n_jobs=1)
    estimator.fit(encoded)
    reference_scores = np.sort(np.asarray(-estimator.score_samples(encoded), dtype=np.float64))
    artifact = AnomalyModelArtifact(
        feature_set_version=FEATURE_SET_VERSION,
        training_dataset_checksum=dataset_checksum,
        preprocessor=preprocessor,
        estimator=estimator,
        reference_scores=reference_scores,
        contamination=0.1,
        threshold=0.5,
    )
    output = io.BytesIO()
    joblib.dump(artifact, output, compress=0, protocol=4)
    return output.getvalue()


def _registration_payload(artifact: bytes) -> dict[str, object]:
    return {
        "model_key": "runtime-transaction-anomaly",
        "version": "2026.08.1",
        "kind": "anomaly",
        "purpose": "operational",
        "runtime_contract": "anomaly-score-v1",
        "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        "feature_set_version": FEATURE_SET_VERSION,
        "training_dataset_id": "ODS-RUNTIME-0001",
        "training_dataset_checksum": DATASET_CHECKSUM,
        "training_data_approved": True,
        "operational_feature_compatible": True,
        "decision_threshold": "0.5",
        "evaluation_metrics": {
            "training_row_count": 24,
            "contamination": 0.1,
            "score_reference_checksum": "d" * 64,
        },
        "model_card_reference": "anomaly/model-card.md",
        "model_card_checksum": MODEL_CARD_CHECKSUM,
    }


def test_verified_artifact_runs_shadow_inference_without_changing_rule_score(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    store = ModelArtifactStore(tmp_path / "artifacts", max_bytes=2 * 1024 * 1024)
    app.dependency_overrides[get_model_artifact_store] = lambda: store
    admin_headers = _auth_headers(
        client, db_session, username="runtime-admin", role=UserRole.ADMINISTRATOR
    )
    evaluator_headers = _auth_headers(
        client, db_session, username="runtime-evaluator", role=UserRole.EVALUATOR
    )
    analyst_headers = _auth_headers(
        client, db_session, username="runtime-analyst", role=UserRole.ANALYST
    )
    transaction = client.post(
        "/api/v1/transactions",
        json=_transaction_payload("TX-RUNTIME-001", "840.00"),
        headers=analyst_headers,
    )
    transaction_id = transaction.json()["transaction"]["id"]
    snapshot = db_session.scalar(
        select(TransactionFeatureSnapshot).where(
            TransactionFeatureSnapshot.transaction_id == transaction_id
        )
    )
    assert snapshot is not None
    artifact = _artifact_bytes(snapshot.feature_values, dataset_checksum=DATASET_CHECKSUM)
    registered = client.post(
        "/api/v1/models",
        json=_registration_payload(artifact),
        headers=admin_headers,
    )
    model_id = registered.json()["model"]["id"]
    rule_before = client.get(
        f"/api/v1/transactions/{transaction_id}/rule-assessment",
        headers=analyst_headers,
    ).json()

    denied_install = client.put(
        f"/api/v1/models/{model_id}/artifact",
        content=artifact,
        headers={**analyst_headers, "Content-Type": "application/octet-stream"},
    )
    mismatched_install = client.put(
        f"/api/v1/models/{model_id}/artifact",
        content=b"not-the-registered-artifact",
        headers={**admin_headers, "Content-Type": "application/octet-stream"},
    )
    installed = client.put(
        f"/api/v1/models/{model_id}/artifact",
        content=artifact,
        headers={**admin_headers, "Content-Type": "application/octet-stream"},
    )
    installed_replay = client.put(
        f"/api/v1/models/{model_id}/artifact",
        content=artifact,
        headers={**admin_headers, "Content-Type": "application/octet-stream"},
    )
    blocked_before_shadow = client.post(
        f"/api/v1/models/{model_id}/shadow-runs",
        json={"transaction_ids": [transaction_id]},
        headers=admin_headers,
    )
    admitted = client.post(
        f"/api/v1/models/{model_id}/transitions",
        json={
            "target_status": "shadow",
            "reason": "Independent evaluator approved the verified runtime artifact.",
        },
        headers=evaluator_headers,
    )
    run = client.post(
        f"/api/v1/models/{model_id}/shadow-runs",
        json={"transaction_ids": [transaction_id]},
        headers=evaluator_headers,
    )
    replay = client.post(
        f"/api/v1/models/{model_id}/shadow-runs",
        json={"transaction_ids": [transaction_id]},
        headers=evaluator_headers,
    )
    rule_after = client.get(
        f"/api/v1/transactions/{transaction_id}/rule-assessment",
        headers=analyst_headers,
    ).json()

    assert transaction.status_code == 201
    assert registered.status_code == 201
    assert denied_install.status_code == 403
    assert mismatched_install.status_code == 409
    assert installed.status_code == 201
    assert installed.json()["installed"] is True
    assert installed.json()["integrity_verified"] is True
    assert installed_replay.status_code == 200
    assert installed_replay.json()["installed"] is False
    assert blocked_before_shadow.status_code == 409
    assert "shadow status" in blocked_before_shadow.json()["detail"]
    assert admitted.status_code == 200
    assert run.status_code == 201
    assert run.json()["created_count"] == 1
    assert run.json()["replayed_count"] == 0
    assert run.json()["shadow_only"] is True
    assert run.json()["affects_operational_score"] is False
    assert run.json()["predictions"][0]["integrity_verified"] is True
    assert run.json()["predictions"][0]["factors"]
    assert replay.status_code == 200
    assert replay.json()["created_count"] == 0
    assert replay.json()["replayed_count"] == 1
    assert rule_before["assessment_checksum"] == rule_after["assessment_checksum"]
    assert rule_before["rule_score"] == rule_after["rule_score"]
    assert db_session.scalar(select(func.count()).select_from(ShadowModelPrediction)) == 1
    assert db_session.scalar(select(func.count()).select_from(TransactionRuleAssessment)) == 1


def test_batch_selects_unscored_transactions_and_rejects_tampered_artifact(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    store = ModelArtifactStore(tmp_path / "artifacts", max_bytes=2 * 1024 * 1024)
    app.dependency_overrides[get_model_artifact_store] = lambda: store
    admin_headers = _auth_headers(
        client, db_session, username="batch-admin", role=UserRole.ADMINISTRATOR
    )
    evaluator_headers = _auth_headers(
        client, db_session, username="batch-evaluator", role=UserRole.EVALUATOR
    )
    analyst_headers = _auth_headers(
        client, db_session, username="batch-analyst", role=UserRole.ANALYST
    )
    transaction_ids: list[str] = []
    for index in range(2):
        response = client.post(
            "/api/v1/transactions",
            json=_transaction_payload(f"TX-BATCH-00{index + 1}", str(700 + index * 50)),
            headers=analyst_headers,
        )
        transaction_ids.append(response.json()["transaction"]["id"])
    snapshot = db_session.scalar(
        select(TransactionFeatureSnapshot).where(
            TransactionFeatureSnapshot.transaction_id == transaction_ids[0]
        )
    )
    assert snapshot is not None
    artifact = _artifact_bytes(snapshot.feature_values, dataset_checksum=DATASET_CHECKSUM)
    registered = client.post(
        "/api/v1/models",
        json=_registration_payload(artifact),
        headers=admin_headers,
    )
    model_id = registered.json()["model"]["id"]
    client.put(
        f"/api/v1/models/{model_id}/artifact",
        content=artifact,
        headers={**admin_headers, "Content-Type": "application/octet-stream"},
    )
    client.post(
        f"/api/v1/models/{model_id}/transitions",
        json={
            "target_status": "shadow",
            "reason": "Independent evaluator approved automatic unscored selection.",
        },
        headers=evaluator_headers,
    )

    first_run = client.post(
        f"/api/v1/models/{model_id}/shadow-runs",
        json={"limit": 1},
        headers=evaluator_headers,
    )
    artifact_path = (
        store.root
        / hashlib.sha256(artifact).hexdigest()[:2]
        / f"{hashlib.sha256(artifact).hexdigest()}.joblib"
    )
    artifact_path.chmod(0o640)
    artifact_path.write_bytes(b"tampered")
    second_run = client.post(
        f"/api/v1/models/{model_id}/shadow-runs",
        json={"limit": 10},
        headers=evaluator_headers,
    )

    assert first_run.status_code == 201
    assert first_run.json()["selected_count"] == 1
    assert second_run.status_code == 409
    assert "no longer matches" in second_run.json()["detail"]
    assert db_session.scalar(select(func.count()).select_from(ShadowModelPrediction)) == 1


def test_runtime_rejects_artifact_metadata_that_differs_from_registration(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    store = ModelArtifactStore(tmp_path / "artifacts", max_bytes=2 * 1024 * 1024)
    app.dependency_overrides[get_model_artifact_store] = lambda: store
    admin_headers = _auth_headers(
        client, db_session, username="mismatch-admin", role=UserRole.ADMINISTRATOR
    )
    evaluator_headers = _auth_headers(
        client, db_session, username="mismatch-evaluator", role=UserRole.EVALUATOR
    )
    analyst_headers = _auth_headers(
        client, db_session, username="mismatch-analyst", role=UserRole.ANALYST
    )
    transaction = client.post(
        "/api/v1/transactions",
        json=_transaction_payload("TX-MISMATCH-001", "910.00"),
        headers=analyst_headers,
    )
    transaction_id = transaction.json()["transaction"]["id"]
    snapshot = db_session.scalar(
        select(TransactionFeatureSnapshot).where(
            TransactionFeatureSnapshot.transaction_id == transaction_id
        )
    )
    assert snapshot is not None
    artifact = _artifact_bytes(snapshot.feature_values, dataset_checksum="e" * 64)
    registered = client.post(
        "/api/v1/models",
        json=_registration_payload(artifact),
        headers=admin_headers,
    )
    model_id = registered.json()["model"]["id"]
    installed = client.put(
        f"/api/v1/models/{model_id}/artifact",
        content=artifact,
        headers={**admin_headers, "Content-Type": "application/octet-stream"},
    )
    admitted = client.post(
        f"/api/v1/models/{model_id}/transitions",
        json={
            "target_status": "shadow",
            "reason": "Evaluator approved registry evidence before runtime contract validation.",
        },
        headers=evaluator_headers,
    )
    run = client.post(
        f"/api/v1/models/{model_id}/shadow-runs",
        json={"transaction_ids": [transaction_id]},
        headers=evaluator_headers,
    )

    assert installed.status_code == 201
    assert admitted.status_code == 200
    assert run.status_code == 409
    assert "training dataset does not match" in run.json()["detail"]
    assert db_session.scalar(select(func.count()).select_from(ShadowModelPrediction)) == 0
