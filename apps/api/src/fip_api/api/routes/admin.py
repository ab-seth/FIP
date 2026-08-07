from typing import Annotated

from fastapi import APIRouter, Depends

from fip_api.api.dependencies import require_roles
from fip_api.models import User, UserRole
from fip_api.schemas.auth import UserResponse

router = APIRouter(prefix="/admin", tags=["administration"])


@router.get("/status", response_model=UserResponse)
def admin_status(
    user: Annotated[User, Depends(require_roles(UserRole.ADMINISTRATOR))],
) -> User:
    return user
