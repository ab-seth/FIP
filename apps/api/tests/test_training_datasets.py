from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.core.security import hash_password
from fip_api.models import (
    AnalystCase,
    CaseEvent,
    OperationalDatasetRow,
    TransactionFeatureSnapshot,
    User,
    UserRole,
)
from fip_api.training_datasets import service as dataset_service

PASSWORD = "strong-password"


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
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, user


def create_approved_label(
    client: TestClient,
    analyst_headers: dict[str, str],
    evaluator_headers: dict[str, str],
    *,
    suffix: str,
    classification: str = "confirmed_fraud",
) -> dict[str, object]:
    current_time = datetime(2026, 8, 9, 3, 30, tzinfo=UTC)
    for index in range(5):
        response = client.post(
            "/api/v1/transactions",
            headers=analyst_headers,
            json=transaction_payload(
                external_id=f"TX-{suffix}-H{index}",
                occurred_at=current_time - timedelta(minutes=10 * (5 - index)),
            ),
        )
        assert response.status_code == 201
    flagged = client.post(
        "/api/v1/transactions",
        headers=analyst_headers,
        json=transaction_payload(
            external_id=f"TX-{suffix}-FLAGGED",
            occurred_at=current_time,
            amount="600.00",
            merchant_reference="MER-PRIVATE-STABLE-ID",
            merchant_category_code="6011",
            channel="card_not_present",
            destination_country="KE",
        ),
    )
    assert flagged.status_code == 201
    cases = client.get("/api/v1/cases", headers=analyst_headers).json()
    case = next(
        item
        for item in cases
        if item["transaction"]["external_transaction_id"] == f"TX-{suffix}-FLAGGED"
    )
    case_id = str(case["id"])
    started = client.post(
        f"/api/v1/cases/{case_id}/review",
        headers=analyst_headers,
        json={"reason": "Reviewing the complete deterministic evidence package."},
    )
    assert started.status_code == 200
    classified = client.post(
        f"/api/v1/cases/{case_id}/outcomes",
        headers=analyst_headers,
        json={
            "classification": classification,
            "rationale": "Independent review established a reliable binary case outcome.",
        },
    )
    assert classified.status_code == 200
    outcome_id = str(classified.json()["outcome"]["id"])
    approved = client.post(
        f"/api/v1/cases/{case_id}/outcomes/{outcome_id}/review",
        headers=evaluator_headers,
        json={
            "status": "approved",
            "reason": "Independent quality review supports inclusion in a governed dataset.",
        },
    )
    assert approved.status_code == 200
    return approved.json()


def transaction_payload(
    *,
    external_id: str,
    occurred_at: datetime,
    amount: str = "100.00",
    merchant_reference: str = "MER-BASE",
    merchant_category_code: str = "5411",
    channel: str = "card_present",
    destination_country: str = "RW",
) -> dict[str, object]:
    return {
        "external_transaction_id": external_id,
        "occurred_at": occurred_at.isoformat(),
        "amount": amount,
        "currency": "USD",
        "account_reference": f"ACC-{external_id.split('-')[1]}",
        "merchant_reference": merchant_reference,
        "merchant_category_code": merchant_category_code,
        "channel": channel,
        "source_country": "RW",
        "destination_country": destination_country,
    }


def test_readiness_and_snapshot_creation_require_governed_sources_and_admin(
    client: TestClient,
    db_session: Session,
) -> None:
    analyst_headers, _ = auth_headers(
        client,
        db_session,
        username="dataset-analyst",
        role=UserRole.ANALYST,
    )
    admin_headers, _ = auth_headers(
        client,
        db_session,
        username="dataset-admin",
        role=UserRole.ADMINISTRATOR,
    )

    readiness = client.get("/api/v1/ml/datasets/readiness", headers=analyst_headers)
    forbidden = client.post(
        "/api/v1/ml/datasets/snapshots",
        headers=analyst_headers,
        json={"reason": "Attempting dataset curation without administrator authority."},
    )
    empty = client.post(
        "/api/v1/ml/datasets/snapshots",
        headers=admin_headers,
        json={"reason": "Capture the currently approved operational label evidence."},
    )

    assert readiness.status_code == 200
    assert readiness.json()["eligible_label_count"] == 0
    assert readiness.json()["readiness_status"] == "blocked"
    assert forbidden.status_code == 403
    assert empty.status_code == 409
    assert "No independently approved" in empty.json()["detail"]


def test_snapshot_is_idempotent_deidentified_and_tamper_evident(
    client: TestClient,
    db_session: Session,
) -> None:
    analyst_headers, _ = auth_headers(
        client,
        db_session,
        username="source-analyst",
        role=UserRole.ANALYST,
    )
    evaluator_headers, _ = auth_headers(
        client,
        db_session,
        username="source-evaluator",
        role=UserRole.EVALUATOR,
    )
    admin_headers, _ = auth_headers(
        client,
        db_session,
        username="source-admin",
        role=UserRole.ADMINISTRATOR,
    )
    create_approved_label(
        client,
        analyst_headers,
        evaluator_headers,
        suffix="DATASET",
    )

    readiness = client.get("/api/v1/ml/datasets/readiness", headers=admin_headers)
    created = client.post(
        "/api/v1/ml/datasets/snapshots",
        headers=admin_headers,
        json={"reason": "Freeze the first independently reviewed operational label set."},
    )
    replayed = client.post(
        "/api/v1/ml/datasets/snapshots",
        headers=admin_headers,
        json={"reason": "Verify exact source-manifest replay remains idempotent."},
    )

    assert readiness.status_code == 200
    assert readiness.json()["eligible_label_count"] == 1
    assert readiness.json()["positive_label_count"] == 1
    assert readiness.json()["readiness_status"] == "blocked"
    assert created.status_code == 200
    assert created.json()["created"] is True
    dataset = created.json()["dataset"]
    assert dataset["display_id"].startswith("ODS-")
    assert dataset["row_count"] == 1
    assert dataset["readiness_status"] == "blocked"
    assert dataset["integrity_verified"] is True
    assert replayed.status_code == 200
    assert replayed.json()["created"] is False
    assert replayed.json()["dataset"]["id"] == dataset["id"]

    exported_row = dataset["rows"][0]
    assert exported_row["label"] == 1
    assert "merchant_reference" not in exported_row["feature_values"]
    assert "account_reference" not in exported_row["feature_values"]
    assert "external_transaction_id" not in exported_row["feature_values"]
    assert len(dataset["dataset_checksum"]) == 64
    assert len(exported_row["row_checksum"]) == 64

    stored_row = db_session.scalar(
        select(OperationalDatasetRow).where(OperationalDatasetRow.dataset_id == dataset["id"])
    )
    assert stored_row is not None
    stored_row.feature_values = {**stored_row.feature_values, "amount": "0.01"}
    db_session.commit()
    damaged = client.get(
        f"/api/v1/ml/datasets/{dataset['id']}",
        headers=admin_headers,
    )
    assert damaged.status_code == 200
    assert damaged.json()["integrity_verified"] is False


def test_readiness_excludes_tampered_and_post_decision_sources(
    client: TestClient,
    db_session: Session,
) -> None:
    analyst_headers, _ = auth_headers(
        client,
        db_session,
        username="gate-analyst",
        role=UserRole.ANALYST,
    )
    evaluator_headers, _ = auth_headers(
        client,
        db_session,
        username="gate-evaluator",
        role=UserRole.EVALUATOR,
    )
    approved = create_approved_label(
        client,
        analyst_headers,
        evaluator_headers,
        suffix="TAMPERED",
    )
    case_id = str(approved["id"])
    case = db_session.get(AnalystCase, case_id)
    assert case is not None
    event = db_session.scalar(
        select(CaseEvent).where(CaseEvent.case_id == case.id, CaseEvent.sequence_number == 1)
    )
    assert event is not None
    event.payload = {"opening_reason": "tampered"}
    db_session.commit()

    tampered = client.get("/api/v1/ml/datasets/readiness", headers=analyst_headers)
    assert tampered.status_code == 200
    assert tampered.json()["eligible_label_count"] == 0
    assert tampered.json()["excluded_integrity_failures"] == 1

    # Restore the event by creating another independent source, then make only its feature timing
    # post-date the outcome. The checksum remains intact, but the temporal leakage gate excludes it.
    second = create_approved_label(
        client,
        analyst_headers,
        evaluator_headers,
        suffix="LEAKAGE",
        classification="legitimate",
    )
    second_case = db_session.get(AnalystCase, str(second["id"]))
    assert second_case is not None
    snapshot = db_session.get(TransactionFeatureSnapshot, second_case.feature_snapshot_id)
    assert snapshot is not None
    snapshot.created_at = datetime.now(UTC) + timedelta(days=1)
    db_session.commit()

    gated = client.get("/api/v1/ml/datasets/readiness", headers=analyst_headers)
    assert gated.status_code == 200
    assert gated.json()["eligible_label_count"] == 0
    assert gated.json()["excluded_integrity_failures"] == 1
    assert gated.json()["excluded_temporal_leakage"] == 1


def test_readiness_requires_both_labels_in_every_temporal_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dataset_service, "MINIMUM_ROWS", 14)
    monkeypatch.setattr(dataset_service, "MINIMUM_POSITIVE_LABELS", 7)
    monkeypatch.setattr(dataset_service, "MINIMUM_NEGATIVE_LABELS", 7)
    sources = [
        SimpleNamespace(
            label=index % 2,
            transaction=SimpleNamespace(
                occurred_at=datetime(2026, 7, 1, tzinfo=UTC) + timedelta(days=index)
            ),
        )
        for index in range(14)
    ]

    gates = dataset_service._readiness_gates(
        cast(Any, sources),
        integrity_failures=0,
        feature_contract_mismatches=0,
        temporal_leakage=0,
        synthetic_exclusions=0,
    )

    assert all(gate["passed"] for gate in gates)
    holdout = next(gate for gate in gates if gate["gate"] == "temporal_holdout_class_coverage")
    assert holdout["observed"] == {
        "train": {"legitimate": 5, "fraud": 4},
        "validation": {"legitimate": 1, "fraud": 1},
        "test": {"legitimate": 1, "fraud": 2},
    }
