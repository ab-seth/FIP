from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fip_api.core.security import hash_password
from fip_api.models import CaseEvent, ScoringRuntimeObservation, User, UserRole

PASSWORD = "strong-password"


def _auth_headers(client: TestClient, db: Session) -> dict[str, str]:
    db.add(
        User(
            username="ledger-analyst",
            password_hash=hash_password(PASSWORD),
            role=UserRole.ANALYST.value,
        )
    )
    db.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "ledger-analyst", "password": PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _transaction_payload(
    *,
    external_id: str,
    occurred_at: datetime,
    flagged: bool = False,
) -> dict[str, object]:
    return {
        "external_transaction_id": external_id,
        "occurred_at": occurred_at.isoformat(),
        "amount": "600.00" if flagged else "100.00",
        "currency": "USD",
        "account_reference": "ACC-AUDIT-001",
        "merchant_reference": "MER-NEW" if flagged else "MER-BASE",
        "merchant_category_code": "6011" if flagged else "5411",
        "channel": "card_not_present" if flagged else "card_present",
        "source_country": "RW",
        "destination_country": "KE" if flagged else "RW",
    }


def _create_case(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    current_time = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    for index in range(5):
        response = client.post(
            "/api/v1/transactions",
            headers=headers,
            json=_transaction_payload(
                external_id=f"TX-AUDIT-H{index}",
                occurred_at=current_time - timedelta(minutes=10 * (5 - index)),
            ),
        )
        assert response.status_code == 201
    flagged = client.post(
        "/api/v1/transactions",
        headers=headers,
        json=_transaction_payload(
            external_id="TX-AUDIT-FLAGGED",
            occurred_at=current_time,
            flagged=True,
        ),
    )
    assert flagged.status_code == 201
    cases = client.get("/api/v1/cases", headers=headers)
    assert cases.status_code == 200
    assert len(cases.json()) == 1
    return cases.json()[0]


def test_audit_ledger_is_authenticated_filterable_paginated_and_read_only(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(client, db_session)
    case = _create_case(client, headers)
    observation_count = db_session.scalar(
        select(func.count()).select_from(ScoringRuntimeObservation)
    )

    unauthenticated = client.get("/api/v1/audit/ledger")
    first_page = client.get(
        "/api/v1/audit/ledger",
        headers=headers,
        params={"page_size": 2},
    )
    case_records = client.get(
        "/api/v1/audit/ledger",
        headers=headers,
        params={"category": "case", "q": case["display_id"]},
    )
    after_count = db_session.scalar(select(func.count()).select_from(ScoringRuntimeObservation))

    assert unauthenticated.status_code == 401
    assert first_page.status_code == 200
    ledger = first_page.json()
    assert ledger["schema_version"] == "audit-ledger-v1.0.0"
    assert ledger["read_only"] is True
    assert ledger["changes_operational_state"] is False
    assert ledger["summary"]["total_records"] == 7
    assert ledger["summary"]["verified_records"] == 7
    assert ledger["summary"]["failed_records"] == 0
    assert ledger["summary"]["chained_records"] == 1
    assert ledger["summary"]["category_counts"] == {"case": 1, "scoring": 6}
    assert ledger["total"] == 7
    assert ledger["page_count"] == 4
    assert len(ledger["entries"]) == 2
    assert case_records.status_code == 200
    assert case_records.json()["total"] == 1
    assert case_records.json()["entries"][0]["subject_label"] == case["display_id"]
    assert observation_count == after_count == 6


def test_audit_ledger_surfaces_damaged_source_chains(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(client, db_session)
    case = _create_case(client, headers)
    event = db_session.scalar(select(CaseEvent))
    assert event is not None
    event.actor_username = "tampered-actor"
    db_session.commit()

    failures = client.get(
        "/api/v1/audit/ledger",
        headers=headers,
        params={"category": "case", "integrity": "failed"},
    )
    verified_cases = client.get(
        "/api/v1/audit/ledger",
        headers=headers,
        params={"category": "case", "integrity": "verified"},
    )

    assert failures.status_code == 200
    ledger = failures.json()
    assert ledger["total"] == 1
    assert ledger["entries"][0]["subject_label"] == case["display_id"]
    assert ledger["entries"][0]["integrity_verified"] is False
    assert ledger["summary"]["failed_records"] == 1
    assert verified_cases.status_code == 200
    assert verified_cases.json()["total"] == 0


def test_audit_ledger_rejects_invalid_filter_and_pagination_values(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(client, db_session)

    invalid_category = client.get(
        "/api/v1/audit/ledger",
        headers=headers,
        params={"category": "unknown"},
    )
    invalid_page = client.get(
        "/api/v1/audit/ledger",
        headers=headers,
        params={"page": 0},
    )

    assert invalid_category.status_code == 422
    assert invalid_page.status_code == 422
