from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from fip_api.api.dependencies import get_current_user
from fip_api.audit import build_audit_ledger
from fip_api.db.session import get_db
from fip_api.models import User
from fip_api.schemas.audit import (
    AuditCategory,
    AuditIntegrityFilter,
    AuditLedgerResponse,
)

router = APIRouter(prefix="/audit", tags=["audit"])
Database = Annotated[Session, Depends(get_db)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]


@router.get("/ledger", response_model=AuditLedgerResponse)
def get_audit_ledger(
    db: Database,
    user: AuthenticatedUser,
    category: AuditCategory | None = None,
    integrity: AuditIntegrityFilter = "all",
    query: Annotated[str | None, Query(alias="q", min_length=1, max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AuditLedgerResponse:
    del user
    return build_audit_ledger(
        db,
        category=category,
        integrity=integrity,
        query=query,
        page=page,
        page_size=page_size,
    )
