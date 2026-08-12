from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from fip_api.benchmarking import generate_synthetic_benchmark, get_benchmark_run
from fip_api.benchmarking.worker import process_next_benchmark_run
from fip_api.core.security import hash_password
from fip_api.models import (
    BenchmarkRunStatus,
    IngestionBatch,
    IngestionSourceType,
    Transaction,
    User,
    UserRole,
)

PASSWORD = "strong-password"


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


def _payload() -> dict[str, object]:
    return {
        "transaction_count": 100,
        "seed": 95,
        "reason": "Exercise deterministic validation, scoring, and case routing.",
    }


def test_generator_is_fixed_seed_reproducible_and_configuration_bound() -> None:
    first = generate_synthetic_benchmark(
        transaction_count=100,
        seed=95,
        configuration_checksum="a" * 64,
    )
    replay = generate_synthetic_benchmark(
        transaction_count=100,
        seed=95,
        configuration_checksum="a" * 64,
    )
    changed = generate_synthetic_benchmark(
        transaction_count=100,
        seed=96,
        configuration_checksum="b" * 64,
    )

    assert first.content == replay.content
    assert first.checksum == replay.checksum
    assert first.profile_distribution == replay.profile_distribution
    assert changed.checksum != first.checksum
    assert first.content.startswith(b"external_transaction_id,occurred_at,amount")
    assert b"SYN-ACC-" in first.content


def test_benchmark_worker_seals_report_audit_and_training_exclusion(
    client: TestClient,
    db_session: Session,
) -> None:
    analyst_headers, _ = _auth_headers(
        client,
        db_session,
        username="benchmark-analyst",
        role=UserRole.ANALYST,
    )
    evaluator_headers, _ = _auth_headers(
        client,
        db_session,
        username="benchmark-evaluator",
        role=UserRole.EVALUATOR,
    )
    admin_headers, _ = _auth_headers(
        client,
        db_session,
        username="benchmark-admin",
        role=UserRole.ADMINISTRATOR,
    )

    forbidden = client.post(
        "/api/v1/evaluation/benchmarks",
        headers=analyst_headers,
        json=_payload(),
    )
    created = client.post(
        "/api/v1/evaluation/benchmarks",
        headers=admin_headers,
        json=_payload(),
    )
    replay = client.post(
        "/api/v1/evaluation/benchmarks",
        headers=admin_headers,
        json=_payload(),
    )

    assert forbidden.status_code == 403
    assert created.status_code == 201
    assert replay.status_code == 200
    run_id = created.json()["run"]["id"]
    assert replay.json()["run"]["id"] == run_id
    assert created.json()["run"]["synthetic_only"] is True
    assert created.json()["run"]["eligible_for_operational_training"] is False

    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    assert (
        process_next_benchmark_run(
            session_factory=factory,
            worker_id="benchmark-test-worker",
            lease_minutes=60,
        )
        is True
    )
    db_session.expire_all()
    run = get_benchmark_run(db_session, run_id)
    assert run.status == BenchmarkRunStatus.SUCCEEDED.value
    batch = db_session.get(IngestionBatch, run.ingestion_batch_id)
    assert batch is not None
    assert batch.source_type == IngestionSourceType.SYNTHETIC.value
    assert batch.row_count == 100

    detail = client.get(
        f"/api/v1/evaluation/benchmarks/{run_id}",
        headers=analyst_headers,
    )
    report = client.get(
        f"/api/v1/evaluation/benchmarks/{run_id}/report",
        headers=analyst_headers,
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["integrity_verified"] is True
    assert body["result"]["pipeline_complete"] is True
    assert body["result"]["processed_transaction_count"] == 100
    assert body["result"]["volume_target_met"] is False
    assert body["result"]["acceptance_met"] is False
    assert report.status_code == 200
    assert report.json()["run"]["report_checksum"] == body["report_checksum"]
    assert report.json()["run"]["model_efficacy_claim"] is False

    audit = client.get(
        "/api/v1/audit/ledger",
        headers=analyst_headers,
        params={"category": "benchmark"},
    )
    assert audit.status_code == 200
    assert audit.json()["total"] == 3
    assert all(entry["integrity_verified"] for entry in audit.json()["entries"])

    cases = client.get("/api/v1/cases", headers=analyst_headers).json()
    assert cases
    case_id = cases[0]["id"]
    started = client.post(
        f"/api/v1/cases/{case_id}/review",
        headers=analyst_headers,
        json={"reason": "Review synthetic benchmark evidence for boundary verification."},
    )
    assert started.status_code == 200
    classified = client.post(
        f"/api/v1/cases/{case_id}/outcomes",
        headers=analyst_headers,
        json={
            "classification": "confirmed_fraud",
            "rationale": "Synthetic classification exists only to test exclusion controls.",
        },
    )
    assert classified.status_code == 200
    outcome_id = classified.json()["outcome"]["id"]
    approved = client.post(
        f"/api/v1/cases/{case_id}/outcomes/{outcome_id}/review",
        headers=evaluator_headers,
        json={
            "status": "approved",
            "reason": "Approve the review while verifying synthetic data remains excluded.",
        },
    )
    assert approved.status_code == 200

    readiness = client.get("/api/v1/ml/datasets/readiness", headers=admin_headers)
    assert readiness.status_code == 200
    assert readiness.json()["eligible_label_count"] == 0
    assert readiness.json()["excluded_synthetic_sources"] == 1

    transaction = db_session.scalar(
        select(Transaction).where(Transaction.ingestion_batch_id == batch.id).limit(1)
    )
    assert transaction is not None
    transaction.amount += Decimal("1.00")
    db_session.commit()
    damaged = client.get(
        f"/api/v1/evaluation/benchmarks/{run_id}",
        headers=analyst_headers,
    )
    assert damaged.status_code == 200
    assert damaged.json()["integrity_verified"] is False
    assert damaged.json()["result"] is None
