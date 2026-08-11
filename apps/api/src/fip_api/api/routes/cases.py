from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
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
    record_case_brief_event,
    review_case_outcome,
    start_case_review,
    verify_case_integrity,
)
from fip_api.db.session import get_db
from fip_api.explainability import (
    CaseBriefEvidenceViolation,
    CaseBriefNotFound,
    CaseBriefProvider,
    build_case_brief_response,
    create_case_brief,
    get_case_brief_provider,
    list_case_briefs,
)
from fip_api.models import AnalystCase, CaseStatus, User, UserRole
from fip_api.schemas.case import (
    CaseDetailResponse,
    CaseNoteCreate,
    CaseOutcomeCreate,
    CaseOutcomeReviewCreate,
    CaseReviewStart,
    CaseSummaryResponse,
)
from fip_api.schemas.explanation import (
    CaseBriefCreate,
    CaseBriefCreationResponse,
    CaseBriefResponse,
)

router = APIRouter(prefix="/cases", tags=["cases"])
Database = Annotated[Session, Depends(get_db)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]
CaseActor = Annotated[
    User,
    Depends(require_roles(UserRole.ADMINISTRATOR, UserRole.ANALYST)),
]
LabelReviewer = Annotated[User, Depends(require_roles(UserRole.EVALUATOR))]
CaseBriefActor = Annotated[
    User,
    Depends(require_roles(UserRole.ADMINISTRATOR, UserRole.ANALYST)),
]
BriefProvider = Annotated[CaseBriefProvider, Depends(get_case_brief_provider)]


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


@router.get("/{case_id}/briefs", response_model=list[CaseBriefResponse])
def get_case_briefs(
    case_id: str,
    db: Database,
    user: AuthenticatedUser,
) -> list[CaseBriefResponse]:
    del user
    if db.get(AnalystCase, case_id) is None:
        raise HTTPException(status_code=404, detail="Investigation case not found.")
    return [build_case_brief_response(db, brief) for brief in list_case_briefs(db, case_id)]


@router.post(
    "/{case_id}/briefs",
    response_model=CaseBriefCreationResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_case_brief(
    case_id: str,
    payload: CaseBriefCreate,
    response: Response,
    db: Database,
    user: CaseBriefActor,
    provider: BriefProvider,
) -> CaseBriefCreationResponse:
    case = db.get(AnalystCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Investigation case not found.")
    if not verify_case_integrity(db, case):
        raise HTTPException(status_code=409, detail="Case audit integrity verification failed.")
    try:
        brief, created = create_case_brief(
            db,
            case=case,
            hybrid_assessment_id=payload.hybrid_assessment_id,
            actor=user,
            provider=provider,
        )
        if created:
            record_case_brief_event(db, case, brief, user)
        db.commit()
    except CaseBriefNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (CaseBriefEvidenceViolation, CaseGovernanceViolation) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The case brief evidence changed concurrently.",
        ) from exc

    db.refresh(brief)
    if not created:
        response.status_code = status.HTTP_200_OK
    return CaseBriefCreationResponse(
        created=created,
        brief=build_case_brief_response(db, brief),
    )


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
