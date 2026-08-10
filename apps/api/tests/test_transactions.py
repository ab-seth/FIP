from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fip_api.core.security import hash_password
from fip_api.models import IngestionBatch, Transaction, User, UserRole

PASSWORD = "strong-password"
CSV_HEADER = (
    "external_transaction_id,occurred_at,amount,currency,account_reference,"
    "merchant_reference,merchant_category_code,channel,source_country,"
    "destination_country\n"
)


def create_user(db: Session, *, username: str, role: UserRole) -> User:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        role=role.value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_headers(client: TestClient, db: Session, *, role: UserRole) -> dict[str, str]:
    username = f"{role.value}-{db.scalar(select(func.count()).select_from(User))}"
    create_user(db, username=username, role=role)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def csv_headers(auth: dict[str, str], filename: str = "transactions.csv") -> dict[str, str]:
    return {
        **auth,
        "Content-Type": "text/csv",
        "X-FIP-Filename": filename,
    }


def transaction_payload(external_id: str = "TX-API-001") -> dict[str, object]:
    return {
        "external_transaction_id": external_id,
        "occurred_at": "2026-08-08T11:34:00+02:00",
        "amount": "320.45",
        "currency": "usd",
        "account_reference": "ACC-014",
        "merchant_reference": "Merchant-91",
        "merchant_category_code": "5734",
        "channel": "card_not_present",
        "source_country": "rw",
        "destination_country": "ke",
    }


def valid_csv(external_id: str = "TX-CSV-001") -> bytes:
    row = f"{external_id},2026-08-08T09:34:00Z,89.20,USD,ACC-22,MER-5,5411,card_present,RW,KE\n"
    return (CSV_HEADER + row).encode()


def test_rest_ingestion_is_replay_safe_and_retrievable(
    client: TestClient, db_session: Session
) -> None:
    headers = auth_headers(client, db_session, role=UserRole.ANALYST)

    created = client.post("/api/v1/transactions", json=transaction_payload(), headers=headers)
    replayed = client.post("/api/v1/transactions", json=transaction_payload(), headers=headers)

    assert created.status_code == 201
    assert created.json()["created"] is True
    assert created.json()["transaction"]["currency"] == "USD"
    assert created.json()["transaction"]["source_country"] == "RW"
    assert replayed.status_code == 200
    assert replayed.json()["created"] is False
    assert replayed.json()["batch"]["id"] == created.json()["batch"]["id"]

    transaction_id = created.json()["transaction"]["id"]
    retrieved = client.get(f"/api/v1/transactions/{transaction_id}", headers=headers)
    assert retrieved.status_code == 200
    assert retrieved.json()["external_transaction_id"] == "TX-API-001"
    assert db_session.scalar(select(func.count()).select_from(Transaction)) == 1
    assert db_session.scalar(select(func.count()).select_from(IngestionBatch)) == 1


def test_rest_ingestion_rejects_identifier_with_different_data(
    client: TestClient, db_session: Session
) -> None:
    headers = auth_headers(client, db_session, role=UserRole.ADMINISTRATOR)
    first = client.post("/api/v1/transactions", json=transaction_payload(), headers=headers)
    changed = transaction_payload()
    changed["amount"] = "999.00"

    conflict = client.post("/api/v1/transactions", json=changed, headers=headers)

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert db_session.scalar(select(func.count()).select_from(Transaction)) == 1


def test_csv_validation_is_read_only_then_imports_atomically(
    client: TestClient, db_session: Session
) -> None:
    auth = auth_headers(client, db_session, role=UserRole.ANALYST)
    headers = csv_headers(auth, "daily-settlement.csv")
    body = valid_csv()

    validation = client.post("/api/v1/transactions/upload/validate", content=body, headers=headers)

    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    assert validation.json()["row_count"] == 1
    assert validation.json()["preview"][0]["external_transaction_id"] == "TX-CSV-001"
    assert db_session.scalar(select(func.count()).select_from(Transaction)) == 0
    assert db_session.scalar(select(func.count()).select_from(IngestionBatch)) == 0

    imported = client.post("/api/v1/transactions/upload", content=body, headers=headers)
    replayed = client.post("/api/v1/transactions/upload", content=body, headers=headers)

    assert imported.status_code == 200
    assert imported.json()["created"] is True
    assert imported.json()["batch"]["display_id"].startswith("IMP-")
    assert imported.json()["batch"]["source_filename"] == "daily-settlement.csv"
    assert replayed.status_code == 200
    assert replayed.json()["created"] is False
    assert replayed.json()["batch"]["id"] == imported.json()["batch"]["id"]
    assert db_session.scalar(select(func.count()).select_from(Transaction)) == 1
    assert db_session.scalar(select(func.count()).select_from(IngestionBatch)) == 1


def test_invalid_csv_returns_row_errors_and_persists_nothing(
    client: TestClient, db_session: Session
) -> None:
    auth = auth_headers(client, db_session, role=UserRole.ANALYST)
    body = (
        CSV_HEADER
        + "TX-BAD-1,2026-08-08T09:34:00,not-money,US,ACC-1,,,,,\n"
        + "TX-BAD-1,2026-08-08T09:35:00Z,12.00,USD,ACC-2,,,,,\n"
    ).encode()

    response = client.post(
        "/api/v1/transactions/upload",
        content=body,
        headers=csv_headers(auth, "invalid.csv"),
    )

    assert response.status_code == 422
    assert response.json()["valid"] is False
    assert response.json()["rejected_rows"] == 1
    assert {error["field"] for error in response.json()["errors"]} >= {
        "occurred_at",
        "amount",
        "currency",
    }
    assert db_session.scalar(select(func.count()).select_from(Transaction)) == 0
    assert db_session.scalar(select(func.count()).select_from(IngestionBatch)) == 0


def test_validation_flags_ids_already_imported(client: TestClient, db_session: Session) -> None:
    auth = auth_headers(client, db_session, role=UserRole.ANALYST)
    created = client.post(
        "/api/v1/transactions",
        json=transaction_payload("TX-EXISTS"),
        headers=auth,
    )
    assert created.status_code == 201

    validation = client.post(
        "/api/v1/transactions/upload/validate",
        content=valid_csv("TX-EXISTS"),
        headers=csv_headers(auth),
    )

    assert validation.status_code == 200
    assert validation.json()["valid"] is False
    assert validation.json()["errors"][0]["code"] == "already_imported"
    assert db_session.scalar(select(func.count()).select_from(Transaction)) == 1


def test_upload_role_boundary_and_authenticated_read(
    client: TestClient, db_session: Session
) -> None:
    analyst = auth_headers(client, db_session, role=UserRole.ANALYST)
    evaluator = auth_headers(client, db_session, role=UserRole.EVALUATOR)
    created = client.post("/api/v1/transactions", json=transaction_payload(), headers=analyst)
    assert created.status_code == 201

    denied = client.post(
        "/api/v1/transactions/upload/validate",
        content=valid_csv(),
        headers=csv_headers(evaluator),
    )
    allowed_read = client.get(
        f"/api/v1/transactions/{created.json()['transaction']['id']}",
        headers=evaluator,
    )
    missing_auth = client.get(f"/api/v1/transactions/{created.json()['transaction']['id']}")

    assert denied.status_code == 403
    assert allowed_read.status_code == 200
    assert missing_auth.status_code == 401


def test_csv_filename_and_header_contract_are_enforced(
    client: TestClient, db_session: Session
) -> None:
    auth = auth_headers(client, db_session, role=UserRole.ANALYST)
    wrong_extension = client.post(
        "/api/v1/transactions/upload/validate",
        content=valid_csv(),
        headers=csv_headers(auth, "transactions.txt"),
    )
    missing_column = client.post(
        "/api/v1/transactions/upload/validate",
        content=b"external_transaction_id,amount\nTX-1,10.00\n",
        headers=csv_headers(auth),
    )

    assert wrong_extension.status_code == 200
    assert wrong_extension.json()["errors"][0]["code"] == "invalid_file_type"
    assert missing_column.status_code == 200
    assert missing_column.json()["errors"][0]["code"] == "missing_columns"
