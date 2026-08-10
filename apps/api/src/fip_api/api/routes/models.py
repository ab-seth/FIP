from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fip_api.api.dependencies import get_current_user, require_roles
from fip_api.db.session import get_db
from fip_api.model_evaluation import (
    EvaluationConflict,
    EvaluationDataInsufficient,
    build_evaluation_response,
    create_shadow_evaluation,
    list_shadow_evaluations,
)
from fip_api.model_registry import (
    GovernanceViolation,
    ModelConflict,
    ModelNotFound,
    build_model_response,
    list_registered_models,
    register_model,
    transition_model,
)
from fip_api.models import RegisteredModel, User, UserRole
from fip_api.schemas.model_evaluation import (
    ShadowEvaluationCreate,
    ShadowEvaluationCreationResponse,
    ShadowEvaluationReportResponse,
)
from fip_api.schemas.model_registry import (
    ModelRegistrationCreate,
    ModelRegistrationResponse,
    ModelTransitionCreate,
    RegisteredModelResponse,
)

router = APIRouter(prefix="/models", tags=["models"])
Database = Annotated[Session, Depends(get_db)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]
ModelRegistrar = Annotated[User, Depends(require_roles(UserRole.ADMINISTRATOR))]
LifecycleActor = Annotated[
    User,
    Depends(require_roles(UserRole.ADMINISTRATOR, UserRole.EVALUATOR)),
]
ModelEvaluator = Annotated[User, Depends(require_roles(UserRole.EVALUATOR))]


@router.post("", response_model=ModelRegistrationResponse, status_code=status.HTTP_201_CREATED)
def create_model_registration(
    payload: ModelRegistrationCreate,
    response: Response,
    db: Database,
    user: ModelRegistrar,
) -> ModelRegistrationResponse:
    try:
        model, created = register_model(db, payload, user)
        db.commit()
    except ModelConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GovernanceViolation as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="The model version already exists.") from exc

    db.refresh(model)
    if not created:
        response.status_code = status.HTTP_200_OK
    return ModelRegistrationResponse(created=created, model=build_model_response(db, model))


@router.get("", response_model=list[RegisteredModelResponse])
def get_registered_models(
    db: Database,
    user: AuthenticatedUser,
) -> list[RegisteredModelResponse]:
    del user
    return [build_model_response(db, model) for model in list_registered_models(db)]


@router.get("/{model_id}", response_model=RegisteredModelResponse)
def get_registered_model(
    model_id: str,
    db: Database,
    user: AuthenticatedUser,
) -> RegisteredModelResponse:
    del user
    model = db.get(RegisteredModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model version not found.")
    return build_model_response(db, model)


@router.post("/{model_id}/transitions", response_model=RegisteredModelResponse)
def create_model_transition(
    model_id: str,
    payload: ModelTransitionCreate,
    db: Database,
    user: LifecycleActor,
) -> RegisteredModelResponse:
    try:
        model = transition_model(
            db,
            model_id,
            payload.target_status,
            payload.reason,
            user,
        )
        db.commit()
    except ModelNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GovernanceViolation as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="The model lifecycle changed concurrently."
        ) from exc

    db.refresh(model)
    return build_model_response(db, model)


@router.post(
    "/{model_id}/evaluations",
    response_model=ShadowEvaluationCreationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_model_evaluation(
    model_id: str,
    payload: ShadowEvaluationCreate,
    response: Response,
    db: Database,
    user: ModelEvaluator,
) -> ShadowEvaluationCreationResponse:
    try:
        report, created = create_shadow_evaluation(
            db,
            model_id=model_id,
            payload=payload,
            actor=user,
        )
        db.commit()
    except ModelNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvaluationDataInsufficient as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (EvaluationConflict, GovernanceViolation) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The shadow evaluation window was created concurrently.",
        ) from exc

    db.refresh(report)
    if not created:
        response.status_code = status.HTTP_200_OK
    return ShadowEvaluationCreationResponse(
        created=created,
        report=build_evaluation_response(db, report),
    )


@router.get(
    "/{model_id}/evaluations",
    response_model=list[ShadowEvaluationReportResponse],
)
def get_model_evaluations(
    model_id: str,
    db: Database,
    user: AuthenticatedUser,
) -> list[ShadowEvaluationReportResponse]:
    del user
    try:
        reports = list_shadow_evaluations(db, model_id)
    except ModelNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [build_evaluation_response(db, report) for report in reports]
