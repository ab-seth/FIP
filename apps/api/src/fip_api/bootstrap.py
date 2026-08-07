from __future__ import annotations

from sqlalchemy import select

from fip_api.core.config import get_settings
from fip_api.core.security import hash_password
from fip_api.db.session import SessionLocal
from fip_api.models import User, UserRole


def bootstrap_admin() -> bool:
    settings = get_settings()
    username = settings.bootstrap_admin_username
    password = settings.bootstrap_admin_password
    if username is None or password is None:
        return False

    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == username))
        if existing is not None:
            return False
        db.add(
            User(
                username=username,
                password_hash=hash_password(password.get_secret_value()),
                role=UserRole.ADMINISTRATOR.value,
            )
        )
        db.commit()
    return True


def main() -> None:
    created = bootstrap_admin()
    outcome = "created" if created else "unchanged"
    print(f"Bootstrap administrator: {outcome}")


if __name__ == "__main__":
    main()
