from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.core.security import hash_password
from fip_api.models import (
    AnalystCase,
    CaseEvent,
    TransactionFeatureSnapshot,
    User,
    UserRole,
)

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
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, user


def create_flagged_case(
    client: TestClient,
    headers: dict[str, str],
    *,
    suffix: str,
) -> dict[str, object]:
    current_time = datetime(2026, 8, 9, 3, 30, tzinfo=UTC)
    for index in range(5):
        occurred_at = current_time - timedelta(minutes=10 * (5 - index))
        response = client.post(
            "/api/v1/transactions",
            headers=headers,
            json=transaction_payload(
                external_id=f"TX-{suffix}-H{index}",
                occurred_at=occurred_at,
            ),
        )
        assert response.status_code == 201

    flagged = client.post(
        "/api/v1/transactions",
        headers=headers,
        json=transaction_payload(
            external_id=f"TX-{suffix}-FLAGGED",
            occurred_at=current_time,
            amount="600.00",
            merchant_reference="MER-NEW",
            merchant_category_code="6011",
            channel="card_not_present",
            destination_country="KE",
        ),
    )
    assert flagged.status_code == 201

    cases = client.get("/api/v1/cases", headers=headers)
    assert cases.status_code == 200
    assert len(cases.json()) == 1
    matching = [
        case
        for case in cases.json()
        if case["transaction"]["external_transaction_id"] == f"TX-{suffix}-FLAGGED"
    ]
    assert len(matching) == 1
    return matching[0]


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


def test_flagged_assessment_opens_one_explainable_case(
    client: TestClient,
    db_session: Session,
) -> None:
    analyst_headers, _ = auth_headers(
        client,
        db_session,
        username="case-analyst",
        role=UserRole.ANALYST,
    )

    case = create_flagged_case(client, analyst_headers, suffix="OPEN")
    detail = client.get(f"/api/v1/cases/{case['id']}", headers=analyst_headers)
    premature_outcome = client.post(
        f"/api/v1/cases/{case['id']}/outcomes",
        headers=analyst_headers,
        json={
            "classification": "legitimate",
            "rationale": "A final outcome cannot precede the documented review lifecycle.",
        },
    )

    assert case["display_id"].startswith("CASE-")
    assert case["status"] == "open"
    assert case["priority"] == "urgent"
    assert case["risk_score"] == 100
    assert case["risk_level"] == "high"
    assert case["triggered_rule_count"] == 6
    assert case["integrity_verified"] is True
    assert detail.status_code == 200
    assert detail.json()["hybrid_assessments"] == []
    assert detail.json()["case_briefs"] == []
    assert premature_outcome.status_code == 409
    assert "review must begin" in premature_outcome.json()["detail"]
    assert detail.json()["evidence"]["rule_score"] == 100
    assert detail.json()["events"][0]["actor_username"] == "fip-scoring"
    assert detail.json()["events"][0]["event_type"] == "opened"

    stored_cases = db_session.scalar(select(AnalystCase).where(AnalystCase.id == case["id"]))
    assert stored_cases is not None


def test_analyst_workflow_creates_immutable_outcome_and_governed_label(
    client: TestClient,
    db_session: Session,
) -> None:
    analyst_headers, analyst = auth_headers(
        client,
        db_session,
        username="decision-analyst",
        role=UserRole.ANALYST,
    )
    evaluator_headers, _ = auth_headers(
        client,
        db_session,
        username="label-evaluator",
        role=UserRole.EVALUATOR,
    )
    case = create_flagged_case(client, analyst_headers, suffix="DECISION")
    case_id = str(case["id"])

    started = client.post(
        f"/api/v1/cases/{case_id}/review",
        headers=analyst_headers,
        json={"reason": "Reviewing the deterministic evidence package."},
    )
    noted = client.post(
        f"/api/v1/cases/{case_id}/notes",
        headers=analyst_headers,
        json={"note": "Cross-border activity is inconsistent with the supplied history."},
    )
    classified = client.post(
        f"/api/v1/cases/{case_id}/outcomes",
        headers=analyst_headers,
        json={
            "classification": "confirmed_fraud",
            "rationale": "The reviewed evidence supports a confirmed-fraud determination.",
        },
    )
    outcome = classified.json()["outcome"]
    replayed = client.post(
        f"/api/v1/cases/{case_id}/outcomes",
        headers=analyst_headers,
        json={
            "classification": "legitimate",
            "rationale": "Attempting to replace the immutable final classification.",
        },
    )
    approved = client.post(
        f"/api/v1/cases/{case_id}/outcomes/{outcome['id']}/review",
        headers=evaluator_headers,
        json={
            "status": "approved",
            "reason": "Independent evidence review supports this supervised-learning label.",
        },
    )

    assert started.status_code == 200
    assert started.json()["status"] == "in_review"
    assert noted.status_code == 200
    assert classified.status_code == 200
    assert classified.json()["status"] == "classified"
    assert outcome["training_eligible"] is False
    assert replayed.status_code == 409
    assert approved.status_code == 200
    assert approved.json()["outcome"]["review"]["status"] == "approved"
    assert approved.json()["outcome"]["training_eligible"] is True
    assert approved.json()["integrity_verified"] is True

    analyst.role = UserRole.EVALUATOR.value
    db_session.commit()
    self_review = client.post(
        f"/api/v1/cases/{case_id}/outcomes/{outcome['id']}/review",
        headers=analyst_headers,
        json={
            "status": "rejected",
            "reason": "The original analyst cannot independently review the same label.",
        },
    )
    assert self_review.status_code == 409


def test_inconclusive_outcome_is_never_training_eligible(
    client: TestClient,
    db_session: Session,
) -> None:
    analyst_headers, _ = auth_headers(
        client,
        db_session,
        username="uncertain-analyst",
        role=UserRole.ANALYST,
    )
    evaluator_headers, _ = auth_headers(
        client,
        db_session,
        username="uncertain-evaluator",
        role=UserRole.EVALUATOR,
    )
    case = create_flagged_case(client, analyst_headers, suffix="UNCERTAIN")
    case_id = str(case["id"])
    started = client.post(
        f"/api/v1/cases/{case_id}/review",
        headers=analyst_headers,
        json={"reason": "Reviewing whether the evidence supports a reliable binary outcome."},
    )
    classified = client.post(
        f"/api/v1/cases/{case_id}/outcomes",
        headers=analyst_headers,
        json={
            "classification": "inconclusive",
            "rationale": "Available evidence is insufficient for a reliable binary outcome.",
        },
    )
    outcome = classified.json()["outcome"]
    reviewed = client.post(
        f"/api/v1/cases/{case_id}/outcomes/{outcome['id']}/review",
        headers=evaluator_headers,
        json={
            "status": "approved",
            "reason": "Attempting to approve an inconclusive outcome for model training.",
        },
    )

    assert started.status_code == 200
    assert classified.status_code == 200
    assert outcome["training_eligible"] is False
    assert reviewed.status_code == 409
    assert "cannot become supervised-learning labels" in reviewed.json()["detail"]


def test_tampered_case_event_is_visible_and_blocks_new_actions(
    client: TestClient,
    db_session: Session,
) -> None:
    analyst_headers, _ = auth_headers(
        client,
        db_session,
        username="integrity-analyst",
        role=UserRole.ANALYST,
    )
    case = create_flagged_case(client, analyst_headers, suffix="TAMPER")
    case_id = str(case["id"])
    event = db_session.scalar(
        select(CaseEvent).where(
            CaseEvent.case_id == case_id,
            CaseEvent.sequence_number == 1,
        )
    )
    assert event is not None
    event.payload = {"opening_reason": "tampered"}
    db_session.commit()

    detail = client.get(f"/api/v1/cases/{case_id}", headers=analyst_headers)
    blocked = client.post(
        f"/api/v1/cases/{case_id}/notes",
        headers=analyst_headers,
        json={"note": "This action must not extend a damaged audit chain."},
    )

    assert detail.status_code == 200
    assert detail.json()["integrity_verified"] is False
    assert blocked.status_code == 409
    assert "integrity verification failed" in blocked.json()["detail"]


def test_tampered_feature_evidence_invalidates_case_integrity(
    client: TestClient,
    db_session: Session,
) -> None:
    analyst_headers, _ = auth_headers(
        client,
        db_session,
        username="evidence-analyst",
        role=UserRole.ANALYST,
    )
    case = create_flagged_case(client, analyst_headers, suffix="EVIDENCE")
    stored_case = db_session.get(AnalystCase, str(case["id"]))
    assert stored_case is not None
    snapshot = db_session.get(TransactionFeatureSnapshot, stored_case.feature_snapshot_id)
    assert snapshot is not None
    snapshot.feature_values = {**snapshot.feature_values, "amount": "1.00"}
    db_session.commit()

    detail = client.get(f"/api/v1/cases/{case['id']}", headers=analyst_headers)
    blocked = client.post(
        f"/api/v1/cases/{case['id']}/review",
        headers=analyst_headers,
        json={"reason": "This action must not extend compromised evidence."},
    )

    assert detail.status_code == 200
    assert detail.json()["integrity_verified"] is False
    assert blocked.status_code == 409
