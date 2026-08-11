from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
    ShadowRuntimeMismatch,
    build_model_response,
    build_shadow_prediction_response,
    list_registered_models,
    register_model,
    transition_model,
)
from fip_api.model_runtime import (
    ArtifactIntegrityError,
    ArtifactNotInstalled,
    ModelArtifactStore,
    OperationalArtifactMismatch,
    get_model_artifact_store,
    install_registered_artifact,
    run_shadow_batch,
)
from fip_api.models import RegisteredModel, User, UserRole
from fip_api.schemas.model_evaluation import (
    ShadowEvaluationCreate,
    ShadowEvaluationCreationResponse,
    ShadowEvaluationReportResponse,
)
from fip_api.schemas.model_registry import (
    ModelArtifactInstallationResponse,
    ModelArtifactStatusResponse,
    ModelRegistrationCreate,
    ModelRegistrationResponse,
    ModelTransitionCreate,
    RegisteredModelResponse,
    ShadowRunCreate,
    ShadowRunResponse,
)

router = APIRouter(prefix="/models", tags=["models"])
Database = Annotated[Session, Depends(get_db)]
ArtifactStore = Annotated[ModelArtifactStore, Depends(get_model_artifact_store)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]
ModelRegistrar = Annotated[User, Depends(require_roles(UserRole.ADMINISTRATOR))]
LifecycleActor = Annotated[
    User,
    Depends(require_roles(UserRole.ADMINISTRATOR, UserRole.EVALUATOR)),
]
ModelEvaluator = Annotated[User, Depends(require_roles(UserRole.EVALUATOR))]
ArtifactOperator = Annotated[User, Depends(require_roles(UserRole.ADMINISTRATOR))]


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


@router.get("/{model_id}/artifact", response_model=ModelArtifactStatusResponse)
def get_model_artifact_status(
    model_id: str,
    db: Database,
    store: ArtifactStore,
    user: AuthenticatedUser,
) -> ModelArtifactStatusResponse:
    del user
    model = db.get(RegisteredModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model version not found.")
    artifact_status = store.status(model.artifact_sha256)
    return ModelArtifactStatusResponse(
        model_id=model.id,
        artifact_sha256=artifact_status.checksum,
        installed=artifact_status.installed,
        integrity_verified=artifact_status.integrity_verified,
        size_bytes=artifact_status.size_bytes,
    )


@router.put(
    "/{model_id}/artifact",
    response_model=ModelArtifactInstallationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def install_model_artifact(
    model_id: str,
    request: Request,
    response: Response,
    db: Database,
    store: ArtifactStore,
    user: ArtifactOperator,
) -> ModelArtifactInstallationResponse:
    del user
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/octet-stream":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Model artifacts must use application/octet-stream.",
        )
    content = await _read_artifact(request, store.max_bytes)
    try:
        installation = install_registered_artifact(
            db,
            model_id=model_id,
            content=content,
            store=store,
        )
    except ModelNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ArtifactIntegrityError, GovernanceViolation) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not installation.installed:
        response.status_code = status.HTTP_200_OK
    return ModelArtifactInstallationResponse(
        model_id=model_id,
        artifact_sha256=installation.checksum,
        size_bytes=installation.size_bytes,
        installed=installation.installed,
    )


@router.post(
    "/{model_id}/shadow-runs",
    response_model=ShadowRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_shadow_run(
    model_id: str,
    payload: ShadowRunCreate,
    response: Response,
    db: Database,
    store: ArtifactStore,
    user: LifecycleActor,
) -> ShadowRunResponse:
    del user
    try:
        result = run_shadow_batch(
            db,
            model_id=model_id,
            transaction_ids=(
                tuple(payload.transaction_ids) if payload.transaction_ids is not None else None
            ),
            limit=payload.limit,
            store=store,
        )
        db.commit()
    except ModelNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        ArtifactIntegrityError,
        ArtifactNotInstalled,
        GovernanceViolation,
        OperationalArtifactMismatch,
        ShadowRuntimeMismatch,
    ) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The shadow prediction set changed concurrently.",
        ) from exc

    selected_count = len(result.predictions)
    replayed_count = selected_count - result.created_count
    if result.created_count == 0:
        response.status_code = status.HTTP_200_OK
    return ShadowRunResponse(
        model_id=model_id,
        selected_count=selected_count,
        created_count=result.created_count,
        replayed_count=replayed_count,
        predictions=[
            build_shadow_prediction_response(db, prediction) for prediction in result.predictions
        ],
    )


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


async def _read_artifact(request: Request, max_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None and content_length.isdigit() and int(content_length) > max_bytes:
        raise _artifact_too_large(max_bytes)
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > max_bytes:
            raise _artifact_too_large(max_bytes)
        content.extend(chunk)
    return bytes(content)


def _artifact_too_large(max_bytes: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"The model artifact cannot exceed {max_bytes} bytes.",
    )
