from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fip_api.api.dependencies import get_current_user, require_roles
from fip_api.cases import (
    CaseConflict,
    CaseGovernanceViolation,
    CaseNotFound,
    add_case_note,
    build_case_detail_response,
    build_case_summary_response,
    classify_case,
    list_cases,
    review_case_outcome,
    start_case_review,
)
from fip_api.db.session import get_db
from fip_api.models import AnalystCase, CaseStatus, User, UserRole
from fip_api.schemas.case import (
    CaseDetailResponse,
    CaseNoteCreate,
    CaseOutcomeCreate,
    CaseOutcomeReviewCreate,
    CaseReviewStart,
    CaseSummaryResponse,
)

router = APIRouter(prefix="/cases", tags=["cases"])
Database = Annotated[Session, Depends(get_db)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]
CaseActor = Annotated[
    User,
    Depends(require_roles(UserRole.ADMINISTRATOR, UserRole.ANALYST)),
]
LabelReviewer = Annotated[User, Depends(require_roles(UserRole.EVALUATOR))]


@router.get("", response_model=list[CaseSummaryResponse])
def get_cases(
    db: Database,
    user: AuthenticatedUser,
    status_filter: Annotated[CaseStatus | None, Query(alias="status")] = None,
) -> list[CaseSummaryResponse]:
    del user
    return [build_case_summary_response(db, case) for case in list_cases(db, status_filter)]


@router.get("/{case_id}", response_model=CaseDetailResponse)
def get_case(
    case_id: str,
    db: Database,
    user: AuthenticatedUser,
) -> CaseDetailResponse:
    del user
    case = db.get(AnalystCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Investigation case not found.")
    return build_case_detail_response(db, case)


@router.post("/{case_id}/review", response_model=CaseDetailResponse)
def begin_case_review(
    case_id: str,
    payload: CaseReviewStart,
    db: Database,
    user: CaseActor,
) -> CaseDetailResponse:
    return _mutate_case(
        db,
        lambda: start_case_review(db, case_id, payload.reason, user),
    )


@router.post("/{case_id}/notes", response_model=CaseDetailResponse)
def create_case_note(
    case_id: str,
    payload: CaseNoteCreate,
    db: Database,
    user: CaseActor,
) -> CaseDetailResponse:
    return _mutate_case(db, lambda: add_case_note(db, case_id, payload.note, user))


@router.post("/{case_id}/outcomes", response_model=CaseDetailResponse)
def create_case_outcome(
    case_id: str,
    payload: CaseOutcomeCreate,
    db: Database,
    user: CaseActor,
) -> CaseDetailResponse:
    return _mutate_case(
        db,
        lambda: classify_case(
            db,
            case_id,
            payload.classification,
            payload.rationale,
            user,
        ),
    )


@router.post(
    "/{case_id}/outcomes/{outcome_id}/review",
    response_model=CaseDetailResponse,
)
def create_outcome_review(
    case_id: str,
    outcome_id: str,
    payload: CaseOutcomeReviewCreate,
    db: Database,
    user: LabelReviewer,
) -> CaseDetailResponse:
    return _mutate_case(
        db,
        lambda: review_case_outcome(
            db,
            case_id,
            outcome_id,
            payload.status,
            payload.reason,
            user,
        ),
    )


def _mutate_case(
    db: Session,
    operation: Callable[[], AnalystCase],
) -> CaseDetailResponse:
    try:
        case = operation()
        db.commit()
    except CaseNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (CaseConflict, CaseGovernanceViolation) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The case changed concurrently.",
        ) from exc
    db.refresh(case)
    return build_case_detail_response(db, case)
