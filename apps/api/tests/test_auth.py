from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fip_api.core.security import hash_password
from fip_api.models import User, UserRole


def create_user(db: Session, *, username: str, password: str, role: UserRole) -> User:
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role.value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def test_login_and_current_user(client: TestClient, db_session: Session) -> None:
    create_user(
        db_session,
        username="analyst",
        password="strong-password",
        role=UserRole.ANALYST,
    )

    token = login(client, "analyst", "strong-password")
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["username"] == "analyst"
    assert response.json()["role"] == "analyst"


def test_invalid_password_is_rejected(client: TestClient, db_session: Session) -> None:
    create_user(
        db_session,
        username="analyst",
        password="strong-password",
        role=UserRole.ANALYST,
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "analyst", "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_inactive_user_is_rejected(client: TestClient, db_session: Session) -> None:
    user = create_user(
        db_session,
        username="inactive-analyst",
        password="strong-password",
        role=UserRole.ANALYST,
    )
    user.is_active = False
    db_session.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "inactive-analyst", "password": "strong-password"},
    )

    assert response.status_code == 401


def test_missing_token_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_role_boundary(client: TestClient, db_session: Session) -> None:
    create_user(
        db_session,
        username="analyst",
        password="strong-password",
        role=UserRole.ANALYST,
    )
    create_user(
        db_session,
        username="admin",
        password="strong-password",
        role=UserRole.ADMINISTRATOR,
    )

    analyst_token = login(client, "analyst", "strong-password")
    admin_token = login(client, "admin", "strong-password")

    denied = client.get(
        "/api/v1/admin/status",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    allowed = client.get(
        "/api/v1/admin/status",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["role"] == "administrator"
