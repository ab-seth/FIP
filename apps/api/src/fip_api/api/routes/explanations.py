from typing import Annotated

from fastapi import APIRouter, Depends, Response

from fip_api.api.dependencies import get_current_user
from fip_api.explainability import build_case_brief_provider_status
from fip_api.models import User
from fip_api.schemas.explanation import CaseBriefProviderStatusResponse

router = APIRouter(prefix="/explanations", tags=["explanations"])
AuthenticatedUser = Annotated[User, Depends(get_current_user)]


@router.get("/provider-status", response_model=CaseBriefProviderStatusResponse)
def get_provider_status(
    response: Response,
    user: AuthenticatedUser,
) -> CaseBriefProviderStatusResponse:
    del user
    response.headers["Cache-Control"] = "no-store"
    return build_case_brief_provider_status()
