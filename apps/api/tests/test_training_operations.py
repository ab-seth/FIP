from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from fip_api.core.security import hash_password
from fip_api.features import FEATURE_SET_VERSION
from fip_api.main import app
from fip_api.models import (
    DatasetReadinessStatus,
    OperationalDatasetSnapshot,
    TrainingRunStatus,
    User,
    UserRole,
)
from fip_api.operational_ml import PIPELINE_VERSION
from fip_api.operational_ml.pipeline import OperationalTrainingConfig, sha256_file
from fip_api.schemas.training_run import TrainingRunCreate
from fip_api.training_datasets.service import (
    LABEL_CONTRACT_VERSION,
    SPLIT_CONTRACT_VERSION,
    TRAINING_FEATURE_NAMES,
)
from fip_api.training_operations import (
    TrainingArtifactStore,
    build_training_run_response,
    get_training_artifact_store,
    get_training_run,
    request_training_run,
    retry_training_run,
)
from fip_api.training_operations.worker import process_next_training_run

PASSWORD = "strong-password"
DATASET_ID = "10000000-0000-0000-0000-000000000001"
DATASET_DISPLAY_ID = "ODS-TRAINING-TEST"
DATASET_CHECKSUM = "d" * 64


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
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, user


def _ready_dataset(db: Session, actor: User) -> OperationalDatasetSnapshot:
    created_at = datetime(2026, 8, 11, 12, tzinfo=UTC)
    dataset = OperationalDatasetSnapshot(
        id=DATASET_ID,
        display_id=DATASET_DISPLAY_ID,
        feature_set_version=FEATURE_SET_VERSION,
        label_contract_version=LABEL_CONTRACT_VERSION,
        split_contract_version=SPLIT_CONTRACT_VERSION,
        feature_names=list(TRAINING_FEATURE_NAMES),
        row_count=100,
        positive_count=20,
        negative_count=80,
        train_count=70,
        validation_count=15,
        test_count=15,
        readiness_status=DatasetReadinessStatus.READY.value,
        readiness_gates=[],
        creation_reason="Freeze verified training-operation test evidence.",
        cutoff_at=created_at,
        created_by_id=actor.id,
        source_manifest_checksum="c" * 64,
        dataset_checksum=DATASET_CHECKSUM,
        created_at=created_at,
    )
    db.add(dataset)
    db.commit()
    return dataset


def _payload(*, seed: int = 42) -> dict[str, object]:
    return {
        "dataset_id": DATASET_ID,
        "candidate_version": "2026.08.training-1",
        "seed": seed,
        "maximum_false_positive_rate": "0.05",
        "reason": "Train governed candidates from the approved immutable snapshot.",
    }


def test_training_run_api_is_role_governed_idempotent_and_tamper_evident(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    analyst_headers, _ = _auth_headers(
        client,
        db_session,
        username="training-analyst",
        role=UserRole.ANALYST,
    )
    admin_headers, admin = _auth_headers(
        client,
        db_session,
        username="training-admin",
        role=UserRole.ADMINISTRATOR,
    )
    _ready_dataset(db_session, admin)
    monkeypatch.setattr(
        "fip_api.training_operations.service.verify_dataset_integrity",
        lambda db, dataset: True,
    )

    forbidden = client.post(
        "/api/v1/ml/training-runs",
        headers=analyst_headers,
        json=_payload(),
    )
    created = client.post(
        "/api/v1/ml/training-runs",
        headers=admin_headers,
        json=_payload(),
    )
    replayed = client.post(
        "/api/v1/ml/training-runs",
        headers=admin_headers,
        json=_payload(),
    )
    conflict = client.post(
        "/api/v1/ml/training-runs",
        headers=admin_headers,
        json=_payload(seed=17),
    )
    listed = client.get("/api/v1/ml/training-runs", headers=analyst_headers)

    assert forbidden.status_code == 403
    assert created.status_code == 201
    assert created.json()["created"] is True
    run = created.json()["run"]
    assert run["status"] == "queued"
    assert run["candidate_only"] is True
    assert run["automatic_registration"] is False
    assert run["automatic_shadow_promotion"] is False
    assert run["affects_operational_score"] is False
    assert run["integrity_verified"] is True
    assert len(run["configuration_checksum"]) == 64
    assert run["events"][0]["to_status"] == "queued"
    assert replayed.status_code == 200
    assert replayed.json()["created"] is False
    assert replayed.json()["run"]["id"] == run["id"]
    assert conflict.status_code == 409
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [run["id"]]

    event = get_training_run(db_session, run["id"])
    response = build_training_run_response(
        db_session,
        event,
        get_training_artifact_store(),
    )
    assert response.integrity_verified is True
    stored_event = event_sequence(db_session, run["id"], 1)
    stored_event.detail = "tampered training request"
    db_session.commit()
    damaged = client.get(
        f"/api/v1/ml/training-runs/{run['id']}",
        headers=analyst_headers,
    )
    assert damaged.status_code == 200
    assert damaged.json()["integrity_verified"] is False


def test_worker_seals_downloadable_candidate_handoffs(
    client: TestClient,
    db_session: Session,
    monkeypatch,
    tmp_path: Path,
) -> None:
    analyst_headers, _ = _auth_headers(
        client,
        db_session,
        username="worker-analyst",
        role=UserRole.ANALYST,
    )
    admin_headers, admin = _auth_headers(
        client,
        db_session,
        username="worker-admin",
        role=UserRole.ADMINISTRATOR,
    )
    _ready_dataset(db_session, admin)
    monkeypatch.setattr(
        "fip_api.training_operations.service.verify_dataset_integrity",
        lambda db, dataset: True,
    )
    payload = TrainingRunCreate.model_validate(_payload())
    run, _ = request_training_run(db_session, payload=payload, actor=admin)
    db_session.commit()

    store = TrainingArtifactStore(tmp_path / "training-artifacts", max_artifact_bytes=1_000_000)
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )

    def fake_runner(
        db: Session,
        dataset_id: str,
        config: OperationalTrainingConfig,
    ) -> dict[str, object]:
        del db
        assert dataset_id == DATASET_ID
        return _write_fake_bundle(config.output_directory, config)

    processed = process_next_training_run(
        session_factory=session_factory,
        store=store,
        worker_id="test-worker",
        lease_minutes=60,
        runner=fake_runner,
    )
    db_session.expire_all()
    completed = get_training_run(db_session, run.id)

    assert processed is True
    assert completed.status == TrainingRunStatus.SUCCEEDED.value
    assert completed.attempt_count == 1
    assert completed.bundle_checksum is not None
    assert completed.result_summary is not None
    assert set(completed.result_summary) == {"supervised", "anomaly"}

    app.dependency_overrides[get_training_artifact_store] = lambda: store
    try:
        detail = client.get(
            f"/api/v1/ml/training-runs/{run.id}",
            headers=analyst_headers,
        )
        registration = client.get(
            f"/api/v1/ml/training-runs/{run.id}/artifacts/supervised/registration",
            headers=analyst_headers,
        )
        denied_model = client.get(
            f"/api/v1/ml/training-runs/{run.id}/artifacts/supervised/model",
            headers=analyst_headers,
        )
        model = client.get(
            f"/api/v1/ml/training-runs/{run.id}/artifacts/supervised/model",
            headers=admin_headers,
        )
        evidence = client.get(
            f"/api/v1/ml/training-runs/{run.id}/evidence/training-evidence",
            headers=analyst_headers,
        )
        artifact_path = store.artifact_path(
            run.id,
            model_kind="supervised",
            artifact_name="model",
        )
        artifact_path.chmod(0o640)
        artifact_path.write_bytes(b"tampered-candidate-artifact")
        damaged = client.get(
            f"/api/v1/ml/training-runs/{run.id}",
            headers=analyst_headers,
        )
        blocked_download = client.get(
            f"/api/v1/ml/training-runs/{run.id}/artifacts/supervised/registration",
            headers=analyst_headers,
        )
    finally:
        app.dependency_overrides.pop(get_training_artifact_store, None)

    assert detail.status_code == 200
    assert detail.json()["integrity_verified"] is True
    assert detail.json()["candidates"]["supervised"]["model_key"] == ("canonical-fraud-classifier")
    assert registration.status_code == 200
    assert registration.json()["kind"] == "supervised"
    assert denied_model.status_code == 403
    assert model.status_code == 200
    assert model.content == b"supervised-candidate-artifact"
    assert evidence.status_code == 200
    assert evidence.json()["candidate_only"] is True
    assert damaged.status_code == 200
    assert damaged.json()["integrity_verified"] is False
    assert damaged.json()["candidates"] is None
    assert blocked_download.status_code == 409


def test_failed_worker_attempt_can_be_explicitly_requeued(
    db_session: Session,
    monkeypatch,
    tmp_path: Path,
) -> None:
    admin = User(
        username="retry-admin",
        password_hash=hash_password(PASSWORD),
        role=UserRole.ADMINISTRATOR.value,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    _ready_dataset(db_session, admin)
    monkeypatch.setattr(
        "fip_api.training_operations.service.verify_dataset_integrity",
        lambda db, dataset: True,
    )
    run, _ = request_training_run(
        db_session,
        payload=TrainingRunCreate.model_validate(_payload()),
        actor=admin,
    )
    db_session.commit()
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )

    def failing_runner(
        db: Session,
        dataset_id: str,
        config: OperationalTrainingConfig,
    ) -> dict[str, object]:
        del db, dataset_id, config
        raise RuntimeError("private worker detail must not escape")

    assert process_next_training_run(
        session_factory=session_factory,
        store=TrainingArtifactStore(tmp_path, max_artifact_bytes=1_000_000),
        worker_id="failed-worker",
        lease_minutes=60,
        runner=failing_runner,
    )
    db_session.expire_all()
    failed = get_training_run(db_session, run.id)
    assert failed.status == TrainingRunStatus.FAILED.value
    assert failed.error_code == "training_execution_failed"
    assert "private worker detail" not in str(failed.error_message)

    retried = retry_training_run(db_session, run_id=run.id, actor=admin)
    db_session.commit()
    assert retried.status == TrainingRunStatus.QUEUED.value
    assert retried.error_code is None
    assert [event_sequence(db_session, run.id, sequence).to_status for sequence in range(1, 5)] == [
        "queued",
        "running",
        "failed",
        "queued",
    ]


def event_sequence(db: Session, run_id: str, sequence_number: int):
    from sqlalchemy import select

    from fip_api.models import OperationalTrainingRunEvent

    event = db.scalar(
        select(OperationalTrainingRunEvent).where(
            OperationalTrainingRunEvent.training_run_id == run_id,
            OperationalTrainingRunEvent.sequence_number == sequence_number,
        )
    )
    assert event is not None
    return event


def _write_fake_bundle(
    output: Path,
    config: OperationalTrainingConfig,
) -> dict[str, object]:
    (output / "supervised").mkdir(parents=True)
    (output / "anomaly").mkdir()
    evidence: dict[str, object] = {
        "pipeline_version": PIPELINE_VERSION,
        "candidate_only": True,
        "automatic_registration": False,
        "automatic_shadow_promotion": False,
        "live_scoring": False,
        "dataset": {
            "id": DATASET_DISPLAY_ID,
            "checksum": DATASET_CHECKSUM,
            "integrity_verified": True,
            "readiness_status": "ready",
            "feature_set_version": FEATURE_SET_VERSION,
        },
        "configuration": {
            "version": config.version,
            "seed": config.seed,
            "maximum_false_positive_rate": config.maximum_false_positive_rate,
        },
        "supervised": {
            "selected_model": "balanced-logistic-regression",
            "artifact_sha256": "pending",
            "threshold": 0.5,
        },
        "anomaly": {
            "model": "isolation-forest",
            "artifact_sha256": "pending",
            "threshold": 0.5,
        },
    }
    for kind in ("supervised", "anomaly"):
        artifact = f"{kind}-candidate-artifact".encode()
        artifact_path = output / kind / "model.joblib"
        artifact_path.write_bytes(artifact)
        candidate_evidence = evidence[kind]
        assert isinstance(candidate_evidence, dict)
        candidate_evidence["artifact_sha256"] = sha256_file(artifact_path)
        card_path = output / kind / "model-card.md"
        card_path.write_text(f"# {kind.title()} candidate\n", encoding="utf-8")
        supervised = kind == "supervised"
        registration = {
            "model_key": (
                "canonical-fraud-classifier" if supervised else "canonical-transaction-anomaly"
            ),
            "version": config.version,
            "kind": kind,
            "purpose": "operational",
            "runtime_contract": ("binary-probability-v1" if supervised else "anomaly-score-v1"),
            "artifact_sha256": sha256_file(artifact_path),
            "feature_set_version": FEATURE_SET_VERSION,
            "training_dataset_id": DATASET_DISPLAY_ID,
            "training_dataset_checksum": DATASET_CHECKSUM,
            "training_data_approved": True,
            "operational_feature_compatible": True,
            "decision_threshold": "0.5",
            "evaluation_metrics": (
                {
                    "average_precision": 0.7,
                    "roc_auc": 0.9,
                    "brier_score": 0.1,
                    "recall": 0.8,
                    "false_positive_rate": 0.05,
                    "evaluated_row_count": 15,
                    "evaluated_positive_count": 3,
                }
                if supervised
                else {
                    "training_row_count": 70,
                    "contamination": 0.05,
                    "score_reference_checksum": "e" * 64,
                }
            ),
            "model_card_reference": f"{kind}/model-card.md",
            "model_card_checksum": sha256_file(card_path),
        }
        _write_json(output / kind / "registration-payload.json", registration)
    _write_json(output / "training-evidence.json", evidence)
    files = {
        str(path.relative_to(output)): sha256_file(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    _write_json(
        output / "run-manifest.json",
        {
            "pipeline_version": PIPELINE_VERSION,
            "candidate_only": True,
            "automatic_registration": False,
            "automatic_shadow_promotion": False,
            "live_scoring": False,
            "files": files,
        },
    )
    return evidence


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
