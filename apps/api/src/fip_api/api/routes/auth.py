from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.api.dependencies import get_current_user
from fip_api.core.config import get_settings
from fip_api.core.security import create_access_token, hash_password, verify_password
from fip_api.db.session import get_db
from fip_api.models import User
from fip_api.schemas.auth import LoginRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["authentication"])
DUMMY_PASSWORD_HASH = hash_password("not-a-real-user-password")


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive datetimes while preserving aware production values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _locked_response(locked_until: datetime, now: datetime) -> HTTPException:
    retry_after = max(1, ceil((_as_utc(locked_until) - now).total_seconds()))
    return HTTPException(
        status_code=423,
        detail="Entry temporarily paused. Try again later or use access support.",
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    settings = get_settings()
    now = datetime.now(UTC)
    user = db.scalar(select(User).where(User.username == payload.username).with_for_update())

    if user is not None and user.locked_until is not None:
        if _as_utc(user.locked_until) > now:
            raise _locked_response(user.locked_until, now)
        user.failed_login_attempts = 0
        user.locked_until = None

    encoded_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_is_valid = verify_password(payload.password, encoded_hash)
    if user is None or not user.is_active or not password_is_valid:
        if user is not None and user.is_active and not password_is_valid:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.login_max_attempts:
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                db.commit()
                raise _locked_response(user.locked_until, now)
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        expires_in=settings.access_token_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
def current_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user
