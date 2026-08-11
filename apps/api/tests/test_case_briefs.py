from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.core.security import hash_password
from fip_api.explainability import (
    CaseBriefProviderResult,
    get_case_brief_provider,
)
from fip_api.main import app
from fip_api.models import CaseBrief, User, UserRole

PASSWORD = "strong-password"


class StubCaseBriefProvider:
    provider_name = "test-json-provider"
    model_name = "grounded-test-model-v1"

    def __init__(self, output: dict[str, object]) -> None:
        self.output = output
        self.calls = 0

    def generate(self, request_payload: dict[str, object]) -> CaseBriefProviderResult:
        assert request_payload["response_format"] == "json"
        self.calls += 1
        return CaseBriefProviderResult(
            output=self.output,
            raw_output=json.dumps(self.output, sort_keys=True),
            generation_milliseconds=23,
        )


def test_valid_grounded_brief_is_cited_audited_and_replay_safe(
    client: TestClient,
    db_session: Session,
) -> None:
    analyst_headers = _auth_headers(
        client,
        db_session,
        username="brief-analyst",
        role=UserRole.ANALYST,
    )
    evaluator_headers = _auth_headers(
        client,
        db_session,
        username="brief-evaluator",
        role=UserRole.EVALUATOR,
    )
    case = _create_flagged_case(client, analyst_headers, suffix="VALID")
    provider = StubCaseBriefProvider(_valid_output())
    app.dependency_overrides[get_case_brief_provider] = lambda: provider

    created = client.post(
        f"/api/v1/cases/{case['id']}/briefs",
        headers=analyst_headers,
        json={"hybrid_assessment_id": None},
    )
    replayed = client.post(
        f"/api/v1/cases/{case['id']}/briefs",
        headers=analyst_headers,
        json={"hybrid_assessment_id": None},
    )
    detail = client.get(f"/api/v1/cases/{case['id']}", headers=evaluator_headers)
    forbidden = client.post(
        f"/api/v1/cases/{case['id']}/briefs",
        headers=evaluator_headers,
        json={"hybrid_assessment_id": None},
    )

    assert created.status_code == 201
    assert created.json()["created"] is True
    brief = created.json()["brief"]
    assert brief["generation_mode"] == "llm"
    assert brief["validation"]["display_output"]["grounding_passed"] is True
    assert brief["validation"]["fallback_used"] is False
    assert brief["integrity_verified"] is True
    assert brief["generation_milliseconds"] == 23
    assert brief["llm_changed_score"] is False
    assert brief["llm_classified_case"] is False
    assert brief["financial_action_taken"] is False
    assert replayed.status_code == 200
    assert replayed.json()["created"] is False
    assert replayed.json()["brief"]["id"] == brief["id"]
    assert provider.calls == 1
    assert forbidden.status_code == 403

    assert detail.status_code == 200
    body = detail.json()
    assert body["risk_score"] == case["risk_score"]
    assert body["priority"] == case["priority"]
    assert body["status"] == "open"
    assert body["outcome"] is None
    assert len(body["case_briefs"]) == 1
    assert [event["event_type"] for event in body["events"]] == [
        "opened",
        "brief_generated",
    ]
    assert body["events"][1]["payload"]["explanation_checksum"] == brief["explanation_checksum"]

    evaluation = client.get("/api/v1/evaluation/record", headers=evaluator_headers)
    assert evaluation.status_code == 200
    explanation_evidence = evaluation.json()["explanations"]
    assert explanation_evidence["total_briefs"] == 1
    assert explanation_evidence["validated_llm_briefs"] == 1
    assert explanation_evidence["deterministic_fallbacks"] == 0
    assert explanation_evidence["displayed_grounding_failures"] == 0
    assert explanation_evidence["llm_latency"] == {
        "observation_count": 1,
        "mean_milliseconds": "23",
        "p95_milliseconds": "23",
        "maximum_milliseconds": 23,
        "target_milliseconds": 10000,
        "status": "passed",
    }


def test_unsupported_numbers_and_actions_trigger_safe_deterministic_fallback(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(
        client,
        db_session,
        username="fallback-analyst",
        role=UserRole.ANALYST,
    )
    case = _create_flagged_case(client, headers, suffix="FALLBACK")
    invalid_output = _valid_output()
    invalid_output["summary"] = (
        "Fraud is confirmed with a score of 97 out of 100; freeze the account now."
    )
    provider = StubCaseBriefProvider(invalid_output)
    app.dependency_overrides[get_case_brief_provider] = lambda: provider

    response = client.post(
        f"/api/v1/cases/{case['id']}/briefs",
        headers=headers,
        json={"hybrid_assessment_id": None},
    )

    assert response.status_code == 201
    brief = response.json()["brief"]
    assert brief["generation_mode"] == "deterministic_fallback"
    assert brief["validation"]["fallback_used"] is True
    assert brief["validation"]["fallback_reason"] == "grounding_validation_failed"
    assert brief["validation"]["provider_candidate"]["grounding_passed"] is False
    failure_codes = {
        failure["code"] for failure in brief["validation"]["provider_candidate"]["failures"]
    }
    assert "unsupported_numerical_claim" in failure_codes
    assert "prohibited_claim_or_action" in failure_codes
    assert brief["validation"]["display_output"]["grounding_passed"] is True
    assert "freeze" not in brief["output"]["summary"].lower()
    assert "fraud is confirmed" not in brief["output"]["summary"].lower()
    assert brief["integrity_verified"] is True

    evaluation = client.get("/api/v1/evaluation/record", headers=headers)
    assert evaluation.status_code == 200
    explanation_evidence = evaluation.json()["explanations"]
    assert explanation_evidence["validated_llm_briefs"] == 0
    assert explanation_evidence["deterministic_fallbacks"] == 1
    assert explanation_evidence["fallback_reasons"] == {"grounding_validation_failed": 1}
    assert explanation_evidence["provider_candidate_grounding_failures"] == 1
    assert explanation_evidence["displayed_grounding_failures"] == 0
    assert explanation_evidence["llm_latency"]["status"] == "not_observed"


def test_unknown_hybrid_evidence_is_rejected_before_provider_call(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(
        client,
        db_session,
        username="lineage-analyst",
        role=UserRole.ANALYST,
    )
    case = _create_flagged_case(client, headers, suffix="LINEAGE")
    provider = StubCaseBriefProvider(_valid_output())
    app.dependency_overrides[get_case_brief_provider] = lambda: provider

    response = client.post(
        f"/api/v1/cases/{case['id']}/briefs",
        headers=headers,
        json={"hybrid_assessment_id": "00000000-0000-0000-0000-000000000000"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Hybrid assessment not found."
    assert provider.calls == 0


def test_tampered_case_brief_is_visible_and_cannot_be_replayed(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(
        client,
        db_session,
        username="brief-integrity-analyst",
        role=UserRole.ANALYST,
    )
    case = _create_flagged_case(client, headers, suffix="TAMPER")
    provider = StubCaseBriefProvider(_valid_output())
    app.dependency_overrides[get_case_brief_provider] = lambda: provider
    created = client.post(
        f"/api/v1/cases/{case['id']}/briefs",
        headers=headers,
        json={"hybrid_assessment_id": None},
    )
    assert created.status_code == 201
    brief = db_session.scalar(select(CaseBrief).where(CaseBrief.case_id == case["id"]))
    assert brief is not None
    brief.display_output = {"summary": "Tampered explanation text."}
    db_session.commit()

    detail = client.get(f"/api/v1/cases/{case['id']}", headers=headers)
    replayed = client.post(
        f"/api/v1/cases/{case['id']}/briefs",
        headers=headers,
        json={"hybrid_assessment_id": None},
    )

    assert detail.status_code == 200
    assert detail.json()["integrity_verified"] is True
    assert detail.json()["case_briefs"][0]["integrity_verified"] is False
    assert detail.json()["case_briefs"][0]["output"] is None
    assert replayed.status_code == 409
    assert replayed.json()["detail"] == "Stored case brief integrity verification failed."


def _valid_output() -> dict[str, object]:
    return {
        "summary": (
            "The deterministic rules assessment recorded 100 out of 100 and human "
            "review remains required."
        ),
        "summary_evidence_refs": [
            "rule_assessment.score",
            "limitations.human_authority",
        ],
        "primary_risk_factors": [
            {
                "text": "The deterministic rules assessment recorded a high risk level.",
                "evidence_refs": ["rule_assessment.score"],
            }
        ],
        "supporting_evidence": [
            {
                "text": "The transaction amount was USD 600.",
                "evidence_refs": ["transaction.amount"],
            }
        ],
        "uncertainties": [
            {
                "text": "No verified hybrid model assessment was supplied for this brief.",
                "evidence_refs": ["limitations.no_hybrid"],
            }
        ],
        "recommended_review_steps": [
            {
                "text": "Keep final classification under human review.",
                "evidence_refs": ["limitations.human_authority"],
            }
        ],
    }


def _auth_headers(
    client: TestClient,
    db: Session,
    *,
    username: str,
    role: UserRole,
) -> dict[str, str]:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        role=role.value,
    )
    db.add(user)
    db.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_flagged_case(
    client: TestClient,
    headers: dict[str, str],
    *,
    suffix: str,
) -> dict[str, object]:
    current_time = datetime(2026, 8, 10, 3, 30, tzinfo=UTC)
    for index in range(5):
        occurred_at = current_time - timedelta(minutes=10 * (5 - index))
        response = client.post(
            "/api/v1/transactions",
            headers=headers,
            json=_transaction_payload(
                external_id=f"TX-{suffix}-H{index}",
                occurred_at=occurred_at,
            ),
        )
        assert response.status_code == 201
    flagged = client.post(
        "/api/v1/transactions",
        headers=headers,
        json=_transaction_payload(
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
    matching = [
        case
        for case in cases.json()
        if case["transaction"]["external_transaction_id"] == f"TX-{suffix}-FLAGGED"
    ]
    assert len(matching) == 1
    return matching[0]


def _transaction_payload(
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
