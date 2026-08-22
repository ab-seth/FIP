from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fip_api.core.checksums import canonical_json_checksum
from fip_api.core.security import hash_password
from fip_api.models import User, UserRole

PASSWORD = "strong-password"


def _auth_headers(client: TestClient, db: Session) -> dict[str, str]:
    db.add(
        User(
            username="research-evidence-reviewer",
            password_hash=hash_password(PASSWORD),
            role=UserRole.EVALUATOR.value,
        )
    )
    db.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "research-evidence-reviewer", "password": PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_research_evidence_is_authenticated_sealed_and_read_only(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(client, db_session)

    unauthenticated = client.get("/api/v1/ml/research-evidence")
    response = client.get("/api/v1/ml/research-evidence", headers=headers)

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    evidence = response.json()
    checksum = evidence.pop("evidence_checksum")
    integrity_verified = evidence.pop("integrity_verified")

    assert checksum == canonical_json_checksum(evidence)
    assert integrity_verified is True
    assert evidence["read_only"] is True
    assert evidence["changes_operational_state"] is False
    assert evidence["dataset"]["row_count"] == 284_807
    assert evidence["dataset"]["positive_count"] == 492
    assert evidence["selected_model"] == "hist-gradient-boosting"
    assert evidence["held_out_test"]["average_precision"] == "0.737251"
    assert evidence["held_out_test"]["recall"] == "0.807692"
    assert evidence["claims"]["real_public_transactions"] is True
    assert evidence["claims"]["eligible_for_operational_promotion"] is False
    assert evidence["claims"]["affects_operational_score"] is False


def test_research_evidence_preserves_temporal_and_selection_boundaries(
    client: TestClient,
    db_session: Session,
) -> None:
    headers = _auth_headers(client, db_session)
    evidence = client.get("/api/v1/ml/research-evidence", headers=headers).json()

    partitions = evidence["partitions"]
    assert [partition["name"] for partition in partitions] == [
        "train",
        "calibration",
        "validation",
        "test",
    ]
    assert sum(partition["row_count"] for partition in partitions) == 284_807
    for earlier, later in zip(partitions, partitions[1:], strict=False):
        assert earlier["maximum_event_time"] < later["minimum_event_time"]

    selected = [candidate for candidate in evidence["candidates"] if candidate["selected"]]
    assert len(selected) == 1
    assert selected[0]["model_key"] == evidence["selected_model"]
    assert evidence["explainability"]["features"][0]["feature"] == "V14"
