from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from fip_api.api.dependencies import get_current_user
from fip_api.db.session import get_db
from fip_api.models import User
from fip_api.schemas.system_evaluation import SystemEvaluationRecordResponse
from fip_api.system_evaluation import build_system_evaluation_record

router = APIRouter(tags=["evaluation"])
Database = Annotated[Session, Depends(get_db)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]


@router.get("/evaluation/record", response_model=SystemEvaluationRecordResponse)
def get_evaluation_record(
    db: Database,
    user: AuthenticatedUser,
) -> SystemEvaluationRecordResponse:
    del user
    return build_system_evaluation_record(db)


@router.get("/metrics", response_model=SystemEvaluationRecordResponse)
def get_system_metrics(
    db: Database,
    user: AuthenticatedUser,
) -> SystemEvaluationRecordResponse:
    del user
    return build_system_evaluation_record(db)
