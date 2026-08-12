from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fip_api.core.security import hash_password
from fip_api.models import ScoringRuntimeObservation, Transaction, User, UserRole

PASSWORD = "strong-password"


def _auth_headers(
    client: TestClient,
    db: Session,
    *,
    username: str,
    role: UserRole,
) -> dict[str, str]:
    db.add(
        User(
            username=username,
            password_hash=hash_password(PASSWORD),
            role=role.value,
        )
    )
    db.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _transaction_payload() -> dict[str, object]:
    return {
        "external_transaction_id": "TX-EVALUATION-RECORD-001",
        "occurred_at": "2026-08-10T09:34:00Z",
        "amount": "89.20",
        "currency": "USD",
        "account_reference": "ACC-EVALUATION-001",
        "merchant_reference": "MER-5",
        "merchant_category_code": "5411",
        "channel": "card_present",
        "source_country": "RW",
        "destination_country": "RW",
    }


def _gate(record: dict[str, object], name: str) -> dict[str, object]:
    gates = record["gates"]
    assert isinstance(gates, list)
    matching = [gate for gate in gates if gate["gate"] == name]
    assert len(matching) == 1
    return matching[0]


def test_evaluation_record_is_authenticated_deterministic_and_read_only(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(
        client,
        db_session,
        username="system-evaluator",
        role=UserRole.EVALUATOR,
    )

    before_transactions = db_session.scalar(select(func.count()).select_from(Transaction))
    record_response = client.get("/api/v1/evaluation/record", headers=headers)
    metrics_response = client.get("/api/v1/metrics", headers=headers)
    unauthenticated = client.get("/api/v1/evaluation/record")
    after_transactions = db_session.scalar(select(func.count()).select_from(Transaction))

    assert record_response.status_code == 200
    assert metrics_response.status_code == 200
    assert unauthenticated.status_code == 401
    record = record_response.json()
    assert record == metrics_response.json()
    assert record["schema_version"] == "system-evaluation-record-v1.1.0"
    assert record["evidence_as_of"] is None
    assert record["overall_status"] == "evidence_pending"
    assert record["read_only"] is True
    assert record["changes_operational_state"] is False
    assert record["volume"]["transactions"] == 0
    assert record["scoring_latency"]["status"] == "not_observed"
    assert _gate(record, "transaction_benchmark_volume")["status"] == "not_demonstrated"
    assert _gate(record, "reproducible_candidate_training")["status"] == "not_demonstrated"
    assert _gate(record, "reproducible_model_evaluation")["status"] == "not_demonstrated"
    assert before_transactions == after_transactions == 0


def test_scoring_runtime_evidence_is_measured_and_integrity_protected(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(
        client,
        db_session,
        username="evaluation-analyst",
        role=UserRole.ANALYST,
    )
    created = client.post(
        "/api/v1/transactions",
        headers=headers,
        json=_transaction_payload(),
    )
    assert created.status_code == 201

    measured = client.get("/api/v1/evaluation/record", headers=headers)
    assert measured.status_code == 200
    record = measured.json()
    assert record["volume"]["transactions"] == 1
    assert record["volume"]["rule_assessments"] == 1
    assert record["volume"]["low_risk"] == 1
    assert record["scoring_latency"]["observation_count"] == 1
    assert record["scoring_latency"]["maximum_milliseconds"] >= 0
    assert record["scoring_latency"]["status"] == "passed"
    assert record["integrity"]["scoring_observation_records"] == 1
    assert record["integrity"]["scoring_observation_integrity_failures"] == 0
    assert _gate(record, "append_only_integrity")["status"] == "passed"

    observation = db_session.scalar(select(ScoringRuntimeObservation))
    assert observation is not None
    observation.runtime_milliseconds += 1
    db_session.commit()

    tampered = client.get("/api/v1/metrics", headers=headers)
    assert tampered.status_code == 200
    tampered_record = tampered.json()
    assert tampered_record["overall_status"] == "attention"
    assert tampered_record["scoring_latency"]["observation_count"] == 0
    assert tampered_record["scoring_latency"]["status"] == "not_observed"
    assert tampered_record["integrity"]["scoring_observation_integrity_failures"] == 1
    assert _gate(tampered_record, "append_only_integrity")["status"] == "failed"
