from typing import Annotated

from fastapi import APIRouter, Depends, Response

from fip_api.api.dependencies import get_current_user
from fip_api.models import User
from fip_api.research_ml.evidence import build_research_evidence_response
from fip_api.schemas.research_evidence import ResearchEvidenceResponse

router = APIRouter(prefix="/ml/research-evidence", tags=["ml-research-evidence"])
AuthenticatedUser = Annotated[User, Depends(get_current_user)]


@router.get("", response_model=ResearchEvidenceResponse)
def get_research_evidence(
    response: Response,
    user: AuthenticatedUser,
) -> ResearchEvidenceResponse:
    del user
    response.headers["Cache-Control"] = "no-store"
    return build_research_evidence_response()
